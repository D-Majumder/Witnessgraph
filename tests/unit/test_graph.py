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
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.relationships import Relationship
from witnessgraph.correlate.graph import (
    DEFAULT_NEIGHBORS_MAX_DEPTH,
    DEFAULT_PATH_MAX_DEPTH,
    MAX_ALLOWED_DEPTH,
    GraphDirection,
    find_neighbors,
    find_path,
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
