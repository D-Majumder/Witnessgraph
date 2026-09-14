"""correlate.graph: deterministic, bounded, directed graph traversal.

Builds small in-memory graphs directly against a real Case/SqliteStore
(cheap -- Case.create against tmp_path) rather than going through the
CLI, mirroring test_store.py's/test_relationships.py's style. CLI-level
behavior (error handling, --format, exit codes) is covered separately in
tests/integration/test_graph_cli.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.relationships import Relationship
from witnessgraph.correlate.graph import (
    DEFAULT_NEIGHBORS_MAX_DEPTH,
    DEFAULT_PATH_MAX_DEPTH,
    DEFAULT_PATHS_LIMIT,
    MAX_ALLOWED_DEPTH,
    MAX_ALLOWED_PATHS_LIMIT,
    GraphDirection,
    all_shortest_paths_result_to_json,
    analyze_paths_evidence_overlap,
    components_result_to_json,
    explain_relationship,
    find_all_shortest_paths,
    find_components,
    find_neighbors,
    find_path,
    neighbors_result_to_json,
    path_result_to_json,
    paths_evidence_overlap_to_json,
    resolve_entity,
    resolve_evidence_ref,
)
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Graph:
    """Small builder: an in-memory Case with named entities and directed
    relationships between them, referenced by their short names."""

    def __init__(self, tmp_path: Path) -> None:
        self.case = Case.create(tmp_path / "case")
        self._evidence = EvidenceItem.create(
            raw_bytes=b"synthetic",
            source_adapter="test",
            adapter_version="0.0.0",
            source_locator="test:1",
            collected_at=NOW,
        )
        self.case.store.put_evidence(self._evidence)
        self.entities: dict[str, str] = {}

    def entity(self, name: str) -> str:
        """Deterministic id per name (``entity-<name>``) -- not a random
        UUID -- so two separately-built graphs that use the same names
        are directly comparable (needed by the insertion-order-
        independence test, where two Cases must agree on entity identity
        while only the relationship insertion order differs)."""
        if name not in self.entities:
            entity_id = f"entity-{name}"
            ent = Entity(
                id=entity_id,
                entity_type="node",
                identifiers={"name": name},
                derived_from=(self._evidence.id,),
            )
            self.case.store.put_entity(ent)
            self.entities[name] = ent.id
        return self.entities[name]

    def edge(self, source: str, target: str, relationship_type: str = "connected_to") -> str:
        rel = Relationship.create(
            relationship_type=relationship_type,
            source_entity_id=self.entity(source),
            target_entity_id=self.entity(target),
            derived_from=(self._evidence.id,),
            created_at=NOW,
        )
        self.case.store.put_relationship(rel)
        return rel.id

    def edge_with_derived_from(
        self, source: str, target: str, derived_from: tuple[str, ...]
    ) -> Relationship:
        rel = Relationship.create(
            relationship_type="connected_to",
            source_entity_id=self.entity(source),
            target_entity_id=self.entity(target),
            derived_from=derived_from,
            created_at=NOW,
        )
        self.case.store.put_relationship(rel)
        return rel

    def normalized_event(self, event_type: str = "test_event") -> str:
        evt = NormalizedEvent.create(
            event_type=event_type, derived_from=(self._evidence.id,), created_at=NOW
        )
        self.case.store.put_normalized_event(evt)
        return evt.id

    @property
    def evidence_id(self) -> str:
        return self._evidence.id

    def close(self) -> None:
        self.case.close()


@pytest.fixture
def graph(tmp_path: Path) -> _Graph:
    g = _Graph(tmp_path)
    yield g
    g.close()


# -- neighbors ----------------------------------------------------------------


def test_neighbors_direct_only_by_default(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    result = find_neighbors(graph.case.store, graph.entity("A"))
    assert result.max_depth == DEFAULT_NEIGHBORS_MAX_DEPTH
    assert [r.entity_id for r in result.reached] == [graph.entity("B")]
    assert result.reached[0].hop_count == 1


def test_neighbors_bounded_traversal_reaches_further_hops(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "D")
    result = find_neighbors(graph.case.store, graph.entity("A"), max_depth=3)
    reached_ids = [r.entity_id for r in result.reached]
    assert reached_ids == [graph.entity("B"), graph.entity("C"), graph.entity("D")]
    assert [r.hop_count for r in result.reached] == [1, 2, 3]


def test_neighbors_does_not_exceed_max_depth(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "D")
    result = find_neighbors(graph.case.store, graph.entity("A"), max_depth=2)
    reached_ids = {r.entity_id for r in result.reached}
    assert reached_ids == {graph.entity("B"), graph.entity("C")}
    assert graph.entity("D") not in reached_ids


def test_neighbors_on_entity_with_no_relationships_is_empty(graph: _Graph) -> None:
    isolated = graph.entity("isolated")
    result = find_neighbors(graph.case.store, isolated)
    assert result.reached == ()


def test_neighbors_on_empty_graph_is_empty(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    result = find_neighbors(case.store, "no-such-entity")
    assert result.reached == ()
    case.close()


def test_neighbors_respects_direction_out_by_default(graph: _Graph) -> None:
    graph.edge("A", "B")
    result_from_b = find_neighbors(graph.case.store, graph.entity("B"))
    assert result_from_b.reached == ()  # B has no outgoing edges


def test_neighbors_direction_in_follows_edges_backward(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_neighbors(graph.case.store, graph.entity("B"), direction=GraphDirection.IN)
    assert [r.entity_id for r in result.reached] == [graph.entity("A")]
    assert result.reached[0].via.walked_direction == "backward"
    # The underlying relationship's own source/target are never swapped.
    assert result.reached[0].via.relationship.source_entity_id == graph.entity("A")
    assert result.reached[0].via.relationship.target_entity_id == graph.entity("B")


def test_neighbors_direction_both_follows_either_way(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("C", "B")
    result = find_neighbors(graph.case.store, graph.entity("B"), direction=GraphDirection.BOTH)
    reached_ids = {r.entity_id for r in result.reached}
    assert reached_ids == {graph.entity("A"), graph.entity("C")}


def test_neighbors_rejects_zero_depth(graph: _Graph) -> None:
    with pytest.raises(ValueError, match="max_depth"):
        find_neighbors(graph.case.store, graph.entity("A"), max_depth=0)


def test_neighbors_rejects_depth_above_ceiling(graph: _Graph) -> None:
    with pytest.raises(ValueError, match="max_depth"):
        find_neighbors(graph.case.store, graph.entity("A"), max_depth=MAX_ALLOWED_DEPTH + 1)


def test_neighbors_accepts_depth_at_ceiling(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_neighbors(graph.case.store, graph.entity("A"), max_depth=MAX_ALLOWED_DEPTH)
    assert len(result.reached) == 1


# -- path -----------------------------------------------------------------


def test_path_finds_direct_edge(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert result.found
    assert result.hop_count == 1
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.from_entity_id == graph.entity("A")
    assert step.to_entity_id == graph.entity("B")
    assert step.walked_direction == "forward"


def test_path_finds_multi_hop_chain_with_full_provenance(graph: _Graph) -> None:
    e1 = graph.edge("A", "B")
    e2 = graph.edge("B", "C")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("C"))
    assert result.found
    assert result.hop_count == 2
    assert [s.relationship.id for s in result.steps] == [e1, e2]
    # Ordering preserved source -> target.
    assert result.steps[0].from_entity_id == graph.entity("A")
    assert result.steps[0].to_entity_id == graph.entity("B")
    assert result.steps[1].from_entity_id == graph.entity("B")
    assert result.steps[1].to_entity_id == graph.entity("C")
    # Provenance: every step's relationship carries derived_from.
    for step in result.steps:
        assert len(step.relationship.derived_from) > 0


def test_path_same_source_and_target_is_trivially_found(graph: _Graph) -> None:
    a = graph.entity("A")
    result = find_path(graph.case.store, a, a)
    assert result.found
    assert result.hop_count == 0
    assert result.steps == ()


def test_path_not_found_between_disconnected_entities(graph: _Graph) -> None:
    graph.entity("A")
    graph.entity("B")  # no edge at all
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert not result.found
    assert result.hop_count is None
    assert result.steps == ()


def test_path_not_found_against_relationship_direction(graph: _Graph) -> None:
    """A --connected_to--> B must never be treated as B --connected_to--> A."""
    graph.edge("A", "B")
    forward = find_path(graph.case.store, graph.entity("A"), graph.entity("B"))
    backward = find_path(graph.case.store, graph.entity("B"), graph.entity("A"))
    assert forward.found
    assert not backward.found


def test_path_direction_in_finds_the_reverse_walk(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_path(
        graph.case.store, graph.entity("B"), graph.entity("A"), direction=GraphDirection.IN
    )
    assert result.found
    assert result.steps[0].walked_direction == "backward"
    assert result.steps[0].relationship.source_entity_id == graph.entity("A")
    assert result.steps[0].relationship.target_entity_id == graph.entity("B")


def test_path_direction_both_finds_either_way(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_path(
        graph.case.store, graph.entity("B"), graph.entity("A"), direction=GraphDirection.BOTH
    )
    assert result.found
    assert result.hop_count == 1


def test_path_not_found_beyond_max_depth(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "D")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("D"), max_depth=2)
    assert not result.found


def test_path_found_exactly_at_max_depth(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("C"), max_depth=2)
    assert result.found
    assert result.hop_count == 2


def test_path_default_max_depth_constant(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert result.max_depth == DEFAULT_PATH_MAX_DEPTH


def test_path_rejects_invalid_depth(graph: _Graph) -> None:
    with pytest.raises(ValueError, match="max_depth"):
        find_path(graph.case.store, graph.entity("A"), graph.entity("B"), max_depth=0)
    with pytest.raises(ValueError, match="max_depth"):
        find_path(
            graph.case.store, graph.entity("A"), graph.entity("B"), max_depth=MAX_ALLOWED_DEPTH + 1
        )


# -- find_all_shortest_paths --------------------------------------------------


def test_all_shortest_paths_trivial_source_equals_target(graph: _Graph) -> None:
    a = graph.entity("A")
    result = find_all_shortest_paths(graph.case.store, a, a)
    assert result.found
    assert result.hop_count == 0
    assert result.paths == ((),)
    assert not result.truncated


def test_all_shortest_paths_single_direct_edge(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert result.found
    assert result.hop_count == 1
    assert len(result.paths) == 1
    assert not result.truncated
    (chain,) = result.paths
    assert len(chain) == 1
    assert chain[0].from_entity_id == graph.entity("A")
    assert chain[0].to_entity_id == graph.entity("B")


def test_all_shortest_paths_finds_every_tied_shortest_chain(graph: _Graph) -> None:
    """Diamond A->B->D and A->C->D: both 2-hop chains are reported. A
    3-hop detour A->X->Y->D exists too but must never appear -- only
    chains tied for the *minimum* hop count are shortest paths."""
    graph.edge("A", "B")
    graph.edge("B", "D")
    graph.edge("A", "C")
    graph.edge("C", "D")
    graph.edge("A", "X")
    graph.edge("X", "Y")
    graph.edge("Y", "D")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("D"))
    assert result.found
    assert result.hop_count == 2
    assert not result.truncated
    assert len(result.paths) == 2
    midpoints = {chain[0].to_entity_id for chain in result.paths}
    assert midpoints == {graph.entity("B"), graph.entity("C")}
    for chain in result.paths:
        assert len(chain) == 2
        assert chain[-1].to_entity_id == graph.entity("D")


def test_all_shortest_paths_deterministic_ordering(graph: _Graph) -> None:
    """Three parallel 1-hop midpoints (A->{B,C,D}->E) must always be
    reported in ascending entity-id order, never storage/insertion order."""
    graph.edge("A", "D")
    graph.edge("D", "E")
    graph.edge("A", "B")
    graph.edge("B", "E")
    graph.edge("A", "C")
    graph.edge("C", "E")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("E"))
    midpoints = [chain[0].to_entity_id for chain in result.paths]
    assert midpoints == sorted(midpoints)
    assert midpoints == [graph.entity("B"), graph.entity("C"), graph.entity("D")]
    # Re-running against unchanged data reproduces the exact same order.
    again = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("E"))
    assert [chain[0].to_entity_id for chain in again.paths] == midpoints


def test_all_shortest_paths_parallel_relationships_are_both_reported(graph: _Graph) -> None:
    """Two distinct Relationships between the same pair of entities (e.g.
    two different pieces of evidence for the same connection) are two
    distinct shortest chains, not merged into one."""
    second_evidence = EvidenceItem.create(
        raw_bytes=b"second",
        source_adapter="test",
        adapter_version="0.0.0",
        source_locator="test:2",
        collected_at=NOW,
    )
    graph.case.store.put_evidence(second_evidence)
    r1 = graph.edge_with_derived_from("A", "B", (graph.evidence_id,))
    r2 = graph.edge_with_derived_from("A", "B", (second_evidence.id,))
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert result.hop_count == 1
    assert len(result.paths) == 2
    found_rel_ids = {chain[0].relationship.id for chain in result.paths}
    assert found_rel_ids == {r1.id, r2.id}


def test_all_shortest_paths_truncates_at_limit_and_reports_it(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "D")
    graph.edge("A", "C")
    graph.edge("C", "D")
    result = find_all_shortest_paths(
        graph.case.store, graph.entity("A"), graph.entity("D"), limit=1
    )
    assert result.found
    assert result.hop_count == 2
    assert len(result.paths) == 1
    assert result.truncated


def test_all_shortest_paths_not_truncated_when_exactly_at_limit(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "D")
    graph.edge("A", "C")
    graph.edge("C", "D")
    result = find_all_shortest_paths(
        graph.case.store, graph.entity("A"), graph.entity("D"), limit=2
    )
    assert len(result.paths) == 2
    assert not result.truncated


def test_all_shortest_paths_not_found_between_disconnected_entities(graph: _Graph) -> None:
    graph.entity("A")
    graph.entity("B")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert not result.found
    assert result.hop_count is None
    assert result.paths == ()
    assert not result.truncated


def test_all_shortest_paths_not_found_against_relationship_direction(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_all_shortest_paths(graph.case.store, graph.entity("B"), graph.entity("A"))
    assert not result.found


def test_all_shortest_paths_direction_in_follows_edges_backward(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_all_shortest_paths(
        graph.case.store, graph.entity("B"), graph.entity("A"), direction=GraphDirection.IN
    )
    assert result.found
    assert len(result.paths) == 1
    assert result.paths[0][0].walked_direction == "backward"
    assert result.paths[0][0].relationship.source_entity_id == graph.entity("A")


def test_all_shortest_paths_direction_both_finds_diamond_ignoring_arrow(graph: _Graph) -> None:
    """A->B->D and C->B (note: C points *into* B, not out of it) plus
    C->D: under direction=both, both 2-hop chains from A to D are found
    even though the A-side and C-side edges don't share an arrow sense."""
    graph.edge("A", "B")
    graph.edge("B", "D")
    result = find_all_shortest_paths(
        graph.case.store, graph.entity("A"), graph.entity("D"), direction=GraphDirection.BOTH
    )
    assert result.found
    assert result.hop_count == 2
    assert len(result.paths) == 1


def test_all_shortest_paths_not_found_beyond_max_depth(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "D")
    result = find_all_shortest_paths(
        graph.case.store, graph.entity("A"), graph.entity("D"), max_depth=2
    )
    assert not result.found


def test_all_shortest_paths_found_exactly_at_max_depth(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    result = find_all_shortest_paths(
        graph.case.store, graph.entity("A"), graph.entity("C"), max_depth=2
    )
    assert result.found
    assert result.hop_count == 2


def test_all_shortest_paths_default_constants(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert result.max_depth == DEFAULT_PATH_MAX_DEPTH
    assert result.limit == DEFAULT_PATHS_LIMIT


def test_all_shortest_paths_rejects_invalid_depth(graph: _Graph) -> None:
    with pytest.raises(ValueError, match="max_depth"):
        find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"), max_depth=0)
    with pytest.raises(ValueError, match="max_depth"):
        find_all_shortest_paths(
            graph.case.store,
            graph.entity("A"),
            graph.entity("B"),
            max_depth=MAX_ALLOWED_DEPTH + 1,
        )


def test_all_shortest_paths_rejects_invalid_limit(graph: _Graph) -> None:
    with pytest.raises(ValueError, match="limit"):
        find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"), limit=0)
    with pytest.raises(ValueError, match="limit"):
        find_all_shortest_paths(
            graph.case.store,
            graph.entity("A"),
            graph.entity("B"),
            limit=MAX_ALLOWED_PATHS_LIMIT + 1,
        )


def test_all_shortest_paths_terminates_on_a_cycle(graph: _Graph) -> None:
    """A -> B -> C -> A: a shortest path from A to C (2 hops via B) must
    still be found, and the pruned shortest-path DAG must never include
    the C -> A back-edge (it is not on any shortest A -> C chain)."""
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "A")
    result = find_all_shortest_paths(
        graph.case.store, graph.entity("A"), graph.entity("C"), max_depth=10
    )
    assert result.found
    assert result.hop_count == 2
    assert len(result.paths) == 1


def test_all_shortest_paths_on_empty_graph_is_not_found(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    result = find_all_shortest_paths(case.store, "no-such-a", "no-such-b")
    assert not result.found
    case.close()


def test_all_shortest_paths_provenance_every_step_has_derived_from(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("C"))
    for chain in result.paths:
        for step in chain:
            assert len(step.relationship.derived_from) > 0


def test_all_shortest_paths_to_json_structure(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "D")
    graph.edge("A", "C")
    graph.edge("C", "D")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("D"))
    doc = all_shortest_paths_result_to_json(result)
    assert doc["found"] is True
    assert doc["hop_count"] == 2
    assert doc["truncated"] is False
    assert doc["limit"] == DEFAULT_PATHS_LIMIT
    assert isinstance(doc["paths"], list)
    assert len(doc["paths"]) == 2
    assert "entities" not in doc  # additive-only, opt-in via store=


def test_all_shortest_paths_to_json_explain_is_additive(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    plain = all_shortest_paths_result_to_json(result)
    explained = all_shortest_paths_result_to_json(result, store=graph.case.store)
    assert "entities" not in plain
    assert "entities" in explained
    assert graph.entity("A") in explained["entities"]  # type: ignore[operator]
    assert graph.entity("B") in explained["entities"]  # type: ignore[operator]
    first_step_rel = explained["paths"][0][0]["relationship"]  # type: ignore[index]
    assert "evidence_lineage" in first_step_rel


# -- analyze_paths_evidence_overlap -------------------------------------------


def test_evidence_overlap_disjoint_evidence_is_fully_independent(graph: _Graph) -> None:
    """Two structurally distinct chains, each derived_from a different
    EvidenceItem: structurally distinct AND evidence-independent."""
    ev2 = EvidenceItem.create(
        raw_bytes=b"second", source_adapter="test", adapter_version="0.0.0",
        source_locator="test:2", collected_at=NOW,
    )
    graph.case.store.put_evidence(ev2)
    graph.edge_with_derived_from("A", "B", (graph.evidence_id,))
    graph.edge_with_derived_from("B", "D", (graph.evidence_id,))
    graph.edge_with_derived_from("A", "C", (ev2.id,))
    graph.edge_with_derived_from("C", "D", (ev2.id,))

    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("D"))
    assert len(result.paths) == 2
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.fully_evidence_independent is True
    assert overlap.shared_evidence_ids == ()
    assert {c.root_evidence_ids for c in overlap.chains} == {(graph.evidence_id,), (ev2.id,)}


def test_evidence_overlap_shared_raw_derived_from_is_not_independent(graph: _Graph) -> None:
    """Two structurally distinct chains that both cite the exact same
    EvidenceItem id directly: structurally distinct but NOT
    evidence-independent."""
    graph.edge_with_derived_from("A", "B", (graph.evidence_id,))
    graph.edge_with_derived_from("B", "D", (graph.evidence_id,))
    graph.edge_with_derived_from("A", "C", (graph.evidence_id,))
    graph.edge_with_derived_from("C", "D", (graph.evidence_id,))

    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("D"))
    assert len(result.paths) == 2
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.fully_evidence_independent is False
    assert overlap.shared_evidence_ids == (graph.evidence_id,)
    for chain_evidence in overlap.chains:
        assert chain_evidence.root_evidence_ids == (graph.evidence_id,)


def test_evidence_overlap_resolves_shared_root_through_normalized_event(graph: _Graph) -> None:
    """Structural path multiplicity is NOT evidence independence: chain 1
    derived_from the EvidenceItem directly, chain 2 derived_from a
    NormalizedEvent built from that *same* EvidenceItem -- the raw
    derived_from ids differ, but both resolve to the same root
    EvidenceItem, so this must be reported as NOT independent."""
    normalized = graph.normalized_event()
    graph.edge_with_derived_from("A", "B", (graph.evidence_id,))
    graph.edge_with_derived_from("B", "D", (graph.evidence_id,))
    graph.edge_with_derived_from("A", "C", (normalized,))
    graph.edge_with_derived_from("C", "D", (normalized,))

    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("D"))
    assert len(result.paths) == 2
    # The raw derived_from ids genuinely differ...
    raw_ids = {step.relationship.derived_from for chain in result.paths for step in chain}
    assert raw_ids == {(graph.evidence_id,), (normalized,)}
    # ...but the root evidence resolves to the same underlying EvidenceItem.
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.fully_evidence_independent is False
    assert overlap.shared_evidence_ids == (graph.evidence_id,)
    for chain_evidence in overlap.chains:
        assert chain_evidence.root_evidence_ids == (graph.evidence_id,)


def test_evidence_overlap_single_chain_is_not_applicable(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert len(result.paths) == 1
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.fully_evidence_independent is None
    assert overlap.shared_evidence_ids == ()
    assert len(overlap.chains) == 1
    assert overlap.chains[0].root_evidence_ids == (graph.evidence_id,)


def test_evidence_overlap_no_paths_found_is_not_applicable(graph: _Graph) -> None:
    graph.entity("A")
    graph.entity("B")
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    assert not result.found
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.chains == ()
    assert overlap.shared_evidence_ids == ()
    assert overlap.fully_evidence_independent is None


def test_evidence_overlap_trivial_same_entity_path_has_no_evidence(graph: _Graph) -> None:
    a = graph.entity("A")
    result = find_all_shortest_paths(graph.case.store, a, a)
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert len(overlap.chains) == 1
    assert overlap.chains[0].root_evidence_ids == ()
    assert overlap.fully_evidence_independent is None


def test_evidence_overlap_dangling_derived_from_contributes_nothing(graph: _Graph) -> None:
    """A derived_from id naming neither an EvidenceItem nor a
    NormalizedEvent (core/ does not enforce referential integrity at
    construction time) resolves to no root evidence, never a crash."""
    graph.edge_with_derived_from("A", "B", ("no-such-evidence-id",))
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.chains[0].root_evidence_ids == ()


def test_evidence_overlap_terminates_on_malformed_normalized_event_cycle(graph: _Graph) -> None:
    """core/ does not enforce that a NormalizedEvent's derived_from names
    an EvidenceItem (only that a Relationship/NormalizedEvent's
    derived_from is non-empty) -- a hypothetically malformed pair of
    NormalizedEvents citing each other must not hang resolution."""
    ne_a = NormalizedEvent(id="ne-a", event_type="t", derived_from=("ne-b",), created_at=NOW)
    ne_b = NormalizedEvent(id="ne-b", event_type="t", derived_from=("ne-a",), created_at=NOW)
    graph.case.store.put_normalized_event(ne_a)
    graph.case.store.put_normalized_event(ne_b)
    graph.edge_with_derived_from("A", "B", ("ne-a",))
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.chains[0].root_evidence_ids == ()  # no root EvidenceItem ever found


def test_evidence_overlap_deterministic_ordering_of_ids(graph: _Graph) -> None:
    ev_z = EvidenceItem.create(
        raw_bytes=b"z", source_adapter="test", adapter_version="0.0.0",
        source_locator="test:z", collected_at=NOW,
    )
    graph.case.store.put_evidence(ev_z)
    graph.edge_with_derived_from("A", "B", (ev_z.id, graph.evidence_id))
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("B"))
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    ids = overlap.chains[0].root_evidence_ids
    assert ids == tuple(sorted(ids))


def test_evidence_overlap_three_chains_partial_overlap(graph: _Graph) -> None:
    """Chain 1 and chain 2 share evidence; chain 3 is disjoint from both --
    shared_evidence_ids reports exactly the id shared by 2+, and the
    overall verdict is correctly False (not fully independent)."""
    ev2 = EvidenceItem.create(
        raw_bytes=b"second", source_adapter="test", adapter_version="0.0.0",
        source_locator="test:2", collected_at=NOW,
    )
    graph.case.store.put_evidence(ev2)
    graph.edge_with_derived_from("A", "B", (graph.evidence_id,))
    graph.edge_with_derived_from("B", "E", (graph.evidence_id,))
    graph.edge_with_derived_from("A", "C", (graph.evidence_id,))
    graph.edge_with_derived_from("C", "E", (graph.evidence_id,))
    graph.edge_with_derived_from("A", "D", (ev2.id,))
    graph.edge_with_derived_from("D", "E", (ev2.id,))

    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("E"))
    assert len(result.paths) == 3
    overlap = analyze_paths_evidence_overlap(graph.case.store, result)
    assert overlap.fully_evidence_independent is False
    assert overlap.shared_evidence_ids == (graph.evidence_id,)


def test_evidence_overlap_to_json_structure(graph: _Graph) -> None:
    graph.edge_with_derived_from("A", "B", (graph.evidence_id,))
    graph.edge_with_derived_from("B", "D", (graph.evidence_id,))
    graph.edge_with_derived_from("A", "C", (graph.evidence_id,))
    graph.edge_with_derived_from("C", "D", (graph.evidence_id,))
    diamond = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("D"))
    overlap = analyze_paths_evidence_overlap(graph.case.store, diamond)
    doc = paths_evidence_overlap_to_json(overlap)
    assert doc["fully_evidence_independent"] is False
    assert doc["shared_evidence_ids"] == [graph.evidence_id]
    assert isinstance(doc["chains"], list)
    assert len(doc["chains"]) == 2
    assert doc["chains"][0]["chain_index"] == 0
    assert doc["chains"][0]["root_evidence_ids"] == [graph.evidence_id]


def test_all_shortest_paths_json_explain_includes_evidence_independence(graph: _Graph) -> None:
    """all_shortest_paths_result_to_json wires evidence_independence into
    its output automatically whenever store (--explain) is given --
    additive and opt-in, exactly like `entities`."""
    ev2 = EvidenceItem.create(
        raw_bytes=b"second", source_adapter="test", adapter_version="0.0.0",
        source_locator="test:2", collected_at=NOW,
    )
    graph.case.store.put_evidence(ev2)
    graph.edge_with_derived_from("A", "B", (graph.evidence_id,))
    graph.edge_with_derived_from("B", "D", (graph.evidence_id,))
    graph.edge_with_derived_from("A", "C", (ev2.id,))
    graph.edge_with_derived_from("C", "D", (ev2.id,))
    result = find_all_shortest_paths(graph.case.store, graph.entity("A"), graph.entity("D"))
    plain = all_shortest_paths_result_to_json(result)
    explained = all_shortest_paths_result_to_json(result, store=graph.case.store)
    assert "evidence_independence" not in plain
    assert "evidence_independence" in explained
    assert explained["evidence_independence"]["fully_evidence_independent"] is True  # type: ignore[index]


# -- cycles -----------------------------------------------------------------


def test_path_terminates_on_a_cycle(graph: _Graph) -> None:
    """A -> B -> C -> A must not infinite-loop; a path from A to C is
    still found via the forward chain."""
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "A")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("C"), max_depth=10)
    assert result.found
    assert result.hop_count == 2


def test_neighbors_terminates_on_a_cycle_and_never_revisits_origin(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "A")
    result = find_neighbors(graph.case.store, graph.entity("A"), max_depth=10)
    reached_ids = [r.entity_id for r in result.reached]
    # Exactly B and C -- A (the origin) is never reported as its own neighbor.
    assert set(reached_ids) == {graph.entity("B"), graph.entity("C")}
    assert len(reached_ids) == 2


def test_diamond_cycle_terminates(graph: _Graph) -> None:
    """A -> B, A -> C, B -> C (a shared-successor cycle-adjacent shape)
    must not cause repeated expansion of C."""
    graph.edge("A", "B")
    graph.edge("A", "C")
    graph.edge("B", "C")
    result = find_neighbors(graph.case.store, graph.entity("A"), max_depth=5)
    reached_ids = [r.entity_id for r in result.reached]
    assert reached_ids.count(graph.entity("C")) == 1
    # C is discovered at hop 1 (direct A->C), not hop 2 via B.
    c_entry = next(r for r in result.reached if r.entity_id == graph.entity("C"))
    assert c_entry.hop_count == 1


# -- branching / multiple equal-length paths: deterministic tie-break --------


def test_multiple_equal_length_paths_are_broken_deterministically(graph: _Graph) -> None:
    """A -> B -> D and A -> C -> D: two equal-length paths to D. The
    chosen path must be stable across repeated calls and independent of
    edge-creation order."""
    e_ab = graph.edge("A", "B")
    e_ac = graph.edge("A", "C")
    e_bd = graph.edge("B", "D")
    e_cd = graph.edge("C", "D")

    result1 = find_path(graph.case.store, graph.entity("A"), graph.entity("D"))
    result2 = find_path(graph.case.store, graph.entity("A"), graph.entity("D"))
    assert result1.found and result2.found
    assert result1.hop_count == 2
    ids1 = [s.relationship.id for s in result1.steps]
    ids2 = [s.relationship.id for s in result2.steps]
    assert ids1 == ids2  # repeated calls agree

    # The tie-break is: at the first hop, the smaller-id of {e_ab, e_ac}
    # wins (both are candidates from A); the second hop is then forced.
    first_hop_id = min(e_ab, e_ac)
    expected_second = e_bd if first_hop_id == e_ab else e_cd
    assert ids1 == [first_hop_id, expected_second]


def test_branching_graph_neighbors_are_all_reported(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("A", "C")
    result = find_neighbors(graph.case.store, graph.entity("A"))
    reached_ids = {r.entity_id for r in result.reached}
    assert reached_ids == {graph.entity("B"), graph.entity("C")}


# -- determinism / insertion-order independence ------------------------------


def test_result_independent_of_relationship_insertion_order(tmp_path: Path) -> None:
    def _build(order: list[tuple[str, str]]) -> tuple[str, str, list[str]]:
        g = _Graph(tmp_path / "".join(f"{a}{b}" for a, b in order))
        # Force identical entity ids across both builds by creating all
        # four entities up front in the same order first.
        for name in ("A", "B", "C", "D"):
            g.entity(name)
        edge_ids = []
        for a, b in order:
            edge_ids.append(g.edge(a, b))
        result = find_path(g.case.store, g.entity("A"), g.entity("D"))
        g.close()
        assert result.found
        return g.entity("A"), g.entity("D"), [s.relationship.id for s in result.steps]

    _, _, path_a = _build([("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")])
    _, _, path_b = _build([("C", "D"), ("B", "D"), ("A", "C"), ("A", "B")])
    assert path_a == path_b


# -- disconnected components --------------------------------------------------


def test_disconnected_components_do_not_reach_each_other(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("X", "Y")
    result = find_neighbors(graph.case.store, graph.entity("A"), max_depth=10)
    reached_ids = {r.entity_id for r in result.reached}
    assert reached_ids == {graph.entity("B")}
    path = find_path(graph.case.store, graph.entity("A"), graph.entity("X"))
    assert not path.found


# -- find_components ----------------------------------------------------------


def test_components_on_empty_graph(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    result = find_components(case.store)
    assert result.components == ()
    assert result.total_entities_in_graph == 0
    assert result.total_relationships == 0
    assert result.total_components_found == 0
    case.close()


def test_entity_with_no_relationships_is_not_a_component(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.entity("isolated")  # created but never related to anything
    result = find_components(graph.case.store)
    all_ids = {eid for c in result.components for eid in c.entity_ids}
    assert graph.entity("isolated") not in all_ids
    assert result.total_entities_in_graph == 2  # only A and B


def test_single_edge_is_one_component_of_two(graph: _Graph) -> None:
    rel_id = graph.edge("A", "B")
    result = find_components(graph.case.store)
    assert len(result.components) == 1
    component = result.components[0]
    assert component.index == 0
    assert component.entity_ids == tuple(sorted([graph.entity("A"), graph.entity("B")]))
    assert component.relationships[0].id == rel_id


def test_direction_is_irrelevant_to_component_membership(graph: _Graph) -> None:
    """Unlike find_neighbors/find_path, component membership must ignore
    relationship direction -- A --connected_to--> B still joins A and B
    into one component even though `direction="out"` from B would find
    nothing via find_neighbors."""
    graph.edge("A", "B")
    assert find_neighbors(graph.case.store, graph.entity("B")).reached == ()
    result = find_components(graph.case.store)
    assert len(result.components) == 1
    assert set(result.components[0].entity_ids) == {graph.entity("A"), graph.entity("B")}


def test_chain_is_one_component(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "D")
    result = find_components(graph.case.store)
    assert len(result.components) == 1
    assert set(result.components[0].entity_ids) == {
        graph.entity(n) for n in ("A", "B", "C", "D")
    }
    assert len(result.components[0].relationships) == 3


def test_disconnected_clusters_are_separate_components(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("X", "Y")
    graph.edge("Y", "Z")
    result = find_components(graph.case.store)
    assert len(result.components) == 2
    sizes = sorted(len(c.entity_ids) for c in result.components)
    assert sizes == [2, 3]


def test_components_are_ordered_by_smallest_member_entity_id(graph: _Graph) -> None:
    graph.edge("X", "Y")  # cluster with larger ids
    graph.edge("A", "B")  # cluster with smaller ids ("entity-A" < "entity-X")
    result = find_components(graph.case.store)
    assert len(result.components) == 2
    assert result.components[0].index == 0
    assert result.components[1].index == 1
    assert min(result.components[0].entity_ids) < min(result.components[1].entity_ids)


def test_entities_and_relationships_within_a_component_are_sorted_by_id(
    graph: _Graph,
) -> None:
    graph.edge("C", "A")
    graph.edge("A", "B")
    result = find_components(graph.case.store)
    component = result.components[0]
    assert list(component.entity_ids) == sorted(component.entity_ids)
    rel_ids = [r.id for r in component.relationships]
    assert rel_ids == sorted(rel_ids)


def test_cycle_resolves_to_one_component_not_a_hang(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    graph.edge("C", "A")
    result = find_components(graph.case.store)
    assert len(result.components) == 1
    assert len(result.components[0].entity_ids) == 3
    assert len(result.components[0].relationships) == 3


def test_parallel_relationships_between_same_pair_both_counted(graph: _Graph) -> None:
    """Two distinct relationships (different types) between the same pair
    of entities must both appear in the component's relationship list --
    neither is a duplicate of the other."""
    rel1 = graph.edge("A", "B", relationship_type="connected_to")
    rel2 = graph.edge("A", "B", relationship_type="authenticated_as")
    result = find_components(graph.case.store)
    assert len(result.components) == 1
    rel_ids = {r.id for r in result.components[0].relationships}
    assert rel_ids == {rel1, rel2}


def test_diamond_graph_is_one_component(graph: _Graph) -> None:
    """A -> B, A -> C, B -> D, C -> D: a diamond shape must not be
    double-counted or split."""
    graph.edge("A", "B")
    graph.edge("A", "C")
    graph.edge("B", "D")
    graph.edge("C", "D")
    result = find_components(graph.case.store)
    assert len(result.components) == 1
    assert len(result.components[0].entity_ids) == 4
    assert len(result.components[0].relationships) == 4


def test_min_size_filters_smaller_components(graph: _Graph) -> None:
    graph.edge("A", "B")  # size 2
    graph.edge("X", "Y")
    graph.edge("Y", "Z")  # size 3
    result = find_components(graph.case.store, min_size=3)
    assert len(result.components) == 1
    assert len(result.components[0].entity_ids) == 3
    assert result.total_components_found == 2  # both exist, only one displayed
    assert result.total_entities_in_graph == 5  # unaffected by the filter


def test_min_size_excluding_everything_reports_zero_displayed(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_components(graph.case.store, min_size=10)
    assert result.components == ()
    assert result.total_components_found == 1


def test_min_size_rejects_less_than_one(graph: _Graph) -> None:
    graph.edge("A", "B")
    with pytest.raises(ValueError, match="min_size"):
        find_components(graph.case.store, min_size=0)


def test_components_result_independent_of_relationship_insertion_order(
    tmp_path: Path,
) -> None:
    def _build(order: list[tuple[str, str]]) -> list[tuple[str, ...]]:
        g = _Graph(tmp_path / "".join(f"{a}{b}" for a, b in order))
        for name in ("A", "B", "C", "X", "Y"):
            g.entity(name)
        for a, b in order:
            g.edge(a, b)
        result = find_components(g.case.store)
        g.close()
        return [c.entity_ids for c in result.components]

    layout_a = _build([("A", "B"), ("B", "C"), ("X", "Y")])
    layout_b = _build([("X", "Y"), ("B", "C"), ("A", "B")])
    assert layout_a == layout_b


# -- explainability: resolve_evidence_ref / resolve_entity / explain_relationship --------


def test_resolve_evidence_ref_finds_evidence_item(graph: _Graph) -> None:
    ref = resolve_evidence_ref(graph.case.store, graph.evidence_id)
    assert ref.kind == "evidence_item"
    assert ref.evidence_item is not None
    assert ref.evidence_item.id == graph.evidence_id
    assert ref.normalized_event is None


def test_resolve_evidence_ref_finds_normalized_event(graph: _Graph) -> None:
    event_id = graph.normalized_event(event_type="logon")
    ref = resolve_evidence_ref(graph.case.store, event_id)
    assert ref.kind == "normalized_event"
    assert ref.normalized_event is not None
    assert ref.normalized_event.event_type == "logon"
    assert ref.evidence_item is None


def test_resolve_evidence_ref_reports_not_found_without_crashing(graph: _Graph) -> None:
    ref = resolve_evidence_ref(graph.case.store, "no-such-id")
    assert ref.kind == "not_found"
    assert ref.evidence_item is None
    assert ref.normalized_event is None


def test_resolve_entity_found_and_not_found(graph: _Graph) -> None:
    graph.entity("A")
    found = resolve_entity(graph.case.store, graph.entity("A"))
    assert found.entity is not None
    assert found.entity.entity_type == "node"

    missing = resolve_entity(graph.case.store, "no-such-entity")
    assert missing.entity is None


def test_explain_relationship_preserves_derived_from_order(graph: _Graph) -> None:
    event_id = graph.normalized_event()
    rel = graph.edge_with_derived_from("A", "B", (event_id, graph.evidence_id))
    refs = explain_relationship(graph.case.store, rel)
    assert [r.id for r in refs] == [event_id, graph.evidence_id]
    assert refs[0].kind == "normalized_event"
    assert refs[1].kind == "evidence_item"


def test_explain_relationship_handles_dangling_derived_from_id(graph: _Graph) -> None:
    """derived_from ids are not referentially enforced at construction
    (see Relationship's module docstring); explaining a dangling one must
    report it as not_found, never raise."""
    rel = graph.edge_with_derived_from("A", "B", ("dangling-id",))
    refs = explain_relationship(graph.case.store, rel)
    assert len(refs) == 1
    assert refs[0].kind == "not_found"
    assert refs[0].id == "dangling-id"


def test_explain_relationship_multiple_evidence_ids(graph: _Graph) -> None:
    second_evidence = EvidenceItem.create(
        raw_bytes=b"second", source_adapter="test", adapter_version="0.0.0",
        source_locator="test:2", collected_at=NOW,
    )
    graph.case.store.put_evidence(second_evidence)
    rel = graph.edge_with_derived_from("A", "B", (graph.evidence_id, second_evidence.id))
    refs = explain_relationship(graph.case.store, rel)
    assert len(refs) == 2
    assert {r.id for r in refs} == {graph.evidence_id, second_evidence.id}


# -- explainability: JSON augmentation is additive and opt-in ----------------------------


def test_path_json_without_store_omits_evidence_lineage_and_entities(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("B"))
    doc = path_result_to_json(result)
    assert "entities" not in doc
    assert "evidence_lineage" not in doc["steps"][0]["relationship"]


def test_path_json_with_store_adds_evidence_lineage_and_entities(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("B"))
    doc = path_result_to_json(result, store=graph.case.store)
    lineage = doc["steps"][0]["relationship"]["evidence_lineage"]
    assert lineage[0]["id"] == graph.evidence_id
    assert lineage[0]["kind"] == "evidence_item"
    assert lineage[0]["evidence_item"]["source_adapter"] == "test"
    assert set(doc["entities"].keys()) == {graph.entity("A"), graph.entity("B")}
    assert doc["entities"][graph.entity("A")]["entity_type"] == "node"


def test_neighbors_json_with_store_resolves_all_reached_entities(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("A", "C")
    result = find_neighbors(graph.case.store, graph.entity("A"))
    doc = neighbors_result_to_json(result, store=graph.case.store)
    assert set(doc["entities"].keys()) == {graph.entity("A"), graph.entity("B"), graph.entity("C")}


def test_components_json_with_store_resolves_member_entities(graph: _Graph) -> None:
    graph.edge("A", "B")
    result = find_components(graph.case.store)
    doc = components_result_to_json(result, store=graph.case.store)
    assert set(doc["entities"].keys()) == {graph.entity("A"), graph.entity("B")}
    for component in doc["components"]:
        for rel in component["relationships"]:
            assert "evidence_lineage" in rel


def test_json_with_store_reports_not_found_entity_without_crashing(tmp_path: Path) -> None:
    """A dangling relationship endpoint (constructed directly, bypassing
    the CLI's referential-existence check) must not crash JSON rendering."""
    case = Case.create(tmp_path / "case")
    evidence = EvidenceItem.create(
        raw_bytes=b"x", source_adapter="t", adapter_version="0", source_locator="x",
        collected_at=NOW,
    )
    case.store.put_evidence(evidence)
    rel = Relationship.create(
        relationship_type="connected_to",
        source_entity_id="ghost-a",
        target_entity_id="ghost-b",
        derived_from=(evidence.id,),
        created_at=NOW,
    )
    case.store.put_relationship(rel)
    result = find_components(case.store)
    doc = components_result_to_json(result, store=case.store)
    assert doc["entities"]["ghost-a"]["found"] is False
    assert doc["entities"]["ghost-b"]["found"] is False
    case.close()


def test_explain_json_is_deterministic_across_repeated_calls(graph: _Graph) -> None:
    graph.edge("A", "B")
    graph.edge("B", "C")
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("C"))
    doc1 = path_result_to_json(result, store=graph.case.store)
    doc2 = path_result_to_json(result, store=graph.case.store)
    assert doc1 == doc2


def test_explain_evidence_lineage_order_matches_derived_from(graph: _Graph) -> None:
    event_id = graph.normalized_event()
    graph.edge_with_derived_from("A", "B", (graph.evidence_id, event_id))
    result = find_path(graph.case.store, graph.entity("A"), graph.entity("B"))
    doc = path_result_to_json(result, store=graph.case.store)
    lineage = doc["steps"][0]["relationship"]["evidence_lineage"]
    assert [entry["id"] for entry in lineage] == [graph.evidence_id, event_id]
    assert lineage[0]["kind"] == "evidence_item"
    assert lineage[1]["kind"] == "normalized_event"
