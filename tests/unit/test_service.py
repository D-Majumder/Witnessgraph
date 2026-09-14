"""witnessgraph.service: the thin application/service boundary (UI v1).

Verifies the service layer is a pure delegation to the exact same
``correlate``/``store`` functions the CLI already calls -- never a
second implementation -- and that it preserves the CLI's own error
distinctions ("no such entity"/"no such relationship" vs. an
out-of-range parameter vs. success) as typed exceptions a caller (CLI or
API) can translate into its own idiom. Builds small in-memory graphs
directly against a real Case/SqliteStore, mirroring test_graph.py's own
style; API-level behavior (status codes, JSON bodies, CORS) is covered
separately in tests/integration/test_api.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from witnessgraph.core.entities import Entity
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.relationships import Relationship
from witnessgraph.correlate.graph import GraphDirection
from witnessgraph.service import (
    case_service,
    contradictions_service,
    entities_service,
    evidence_service,
    graph_service,
    relationships_service,
)
from witnessgraph.service.errors import (
    CaseNotFoundError,
    CaseUnreadableError,
    EntityNotFoundError,
    RelationshipNotFoundError,
    ValidationError,
)
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Fixture:
    """A small Case with one shared EvidenceItem and helpers to add
    entities/relationships by short id -- mirrors test_graph.py's ``_Graph``."""

    def __init__(self, tmp_path: Path) -> None:
        self.case = Case.create(tmp_path / "case")
        self.evidence = EvidenceItem.create(
            raw_bytes=b"synthetic",
            source_adapter="test",
            adapter_version="0.0.0",
            source_locator="test:1",
            collected_at=NOW,
        )
        self.case.store.put_evidence(self.evidence)

    def entity(self, entity_id: str, entity_type: str = "host", **identifiers: str) -> Entity:
        ent = Entity(
            id=entity_id,
            entity_type=entity_type,
            identifiers=identifiers,
            derived_from=(self.evidence.id,),
        )
        self.case.store.put_entity(ent)
        return ent

    def edge(
        self, source: str, target: str, relationship_type: str = "connected_to"
    ) -> Relationship:
        rel = Relationship.create(
            relationship_type=relationship_type,
            source_entity_id=source,
            target_entity_id=target,
            derived_from=(self.evidence.id,),
            created_at=NOW,
        )
        self.case.store.put_relationship(rel)
        return rel


# -- case_service -------------------------------------------------------


def test_open_case_missing_directory_raises_case_not_found(tmp_path: Path) -> None:
    with pytest.raises(CaseNotFoundError):
        case_service.open_case(tmp_path / "nope")


def test_open_case_corrupted_database_raises_case_unreadable(tmp_path: Path) -> None:
    case_dir = tmp_path / "corrupted"
    case_dir.mkdir()
    (case_dir / "case.db").write_bytes(b"not a sqlite database")
    with pytest.raises(CaseUnreadableError):
        case_service.open_case(case_dir)


def test_case_overview_counts_and_manifest_match(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    f.case.record_manifest()
    overview = case_service.get_case_overview(f.case)
    assert overview["entity_count"] == 2
    assert overview["relationship_count"] == 1
    assert overview["evidence_count"] == 1
    assert overview["hypothesis_count"] == 0
    assert overview["manifest_verdict"] == "MATCH"
    assert isinstance(overview["manifest_hash"], str) and overview["manifest_hash"]
    f.case.close()


def test_case_overview_no_recorded_manifest_is_distinct_from_match(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    overview = case_service.get_case_overview(f.case)
    assert overview["manifest_verdict"] == "NO_RECORDED_MANIFEST"
    f.case.close()


def test_case_overview_mismatch_when_case_changes_after_recording(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.case.record_manifest()
    f.entity("e-a")  # case content changes after the manifest was recorded
    overview = case_service.get_case_overview(f.case)
    assert overview["manifest_verdict"] == "MISMATCH"
    f.case.close()


# -- entities_service -----------------------------------------------------


def test_list_entities_sorted_by_id_and_filterable_by_type(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-b", entity_type="host")
    f.entity("e-a", entity_type="user")
    everything = entities_service.list_entities(f.case)
    assert [e["id"] for e in everything] == ["e-a", "e-b"]
    only_hosts = entities_service.list_entities(f.case, entity_type="host")
    assert [e["id"] for e in only_hosts] == ["e-b"]
    f.case.close()


def test_get_entity_returns_full_shape(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a", entity_type="host", hostname="a")
    doc = entities_service.get_entity(f.case, "e-a")
    assert doc["id"] == "e-a"
    assert doc["entity_type"] == "host"
    assert doc["identifiers"] == {"hostname": "a"}
    assert doc["derived_from"] == [f.evidence.id]
    f.case.close()


def test_get_entity_unknown_id_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(EntityNotFoundError):
        entities_service.get_entity(f.case, "nope")
    f.case.close()


# -- relationships_service -------------------------------------------------


def test_list_relationships_filtered_by_entity_and_type(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    for name in ("e-a", "e-b", "e-c"):
        f.entity(name)
    f.edge("e-a", "e-b", "connected_to")
    f.edge("e-b", "e-c", "authenticated_as")
    by_entity = relationships_service.list_relationships(f.case, entity_id="e-b")
    assert len(by_entity) == 2
    by_type = relationships_service.list_relationships(f.case, relationship_type="authenticated_as")
    assert len(by_type) == 1
    assert by_type[0]["relationship_type"] == "authenticated_as"
    f.case.close()


def test_get_relationship_always_resolves_evidence_lineage(tmp_path: Path) -> None:
    """API-facing single-object fetch always resolves lineage -- no
    CLI-style --explain opt-in for a machine JSON caller (§14)."""
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    rel = f.edge("e-a", "e-b")
    doc = relationships_service.get_relationship(f.case, rel.id)
    assert "evidence_lineage" in doc
    assert doc["evidence_lineage"][0]["kind"] == "evidence_item"
    assert doc["evidence_lineage"][0]["evidence_item"]["id"] == f.evidence.id
    f.case.close()


def test_get_relationship_unknown_id_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(RelationshipNotFoundError):
        relationships_service.get_relationship(f.case, "nope")
    f.case.close()


# -- graph_service ----------------------------------------------------------


def test_neighbors_unknown_entity_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(EntityNotFoundError):
        graph_service.neighbors(
            f.case, "nope", max_depth=1, direction=GraphDirection.OUT, explain=False
        )
    f.case.close()


def test_neighbors_invalid_max_depth_raises_validation_error(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    with pytest.raises(ValidationError):
        graph_service.neighbors(
            f.case, "e-a", max_depth=0, direction=GraphDirection.OUT, explain=False
        )
    f.case.close()


def test_neighbors_invalid_max_depth_reported_even_for_unknown_entity(tmp_path: Path) -> None:
    """Mirrors the CLI's own ordering: --max-depth is validated before the
    case's entities are even consulted (cli.main.graph_neighbors validates
    max_depth before opening the case at all)."""
    f = _Fixture(tmp_path)
    with pytest.raises(ValidationError):
        graph_service.neighbors(
            f.case, "nope", max_depth=0, direction=GraphDirection.OUT, explain=False
        )
    f.case.close()


def test_path_found_with_explain_resolves_participating_entities(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    doc = graph_service.path(
        f.case, "e-a", "e-b", max_depth=10, direction=GraphDirection.OUT, explain=True
    )
    assert doc["found"] is True
    assert doc["hop_count"] == 1
    assert set(doc["entities"].keys()) == {"e-a", "e-b"}
    f.case.close()


def test_path_not_found_reported_honestly_not_silenced(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    doc = graph_service.path(
        f.case, "e-a", "e-b", max_depth=10, direction=GraphDirection.OUT, explain=False
    )
    assert doc["found"] is False
    assert doc["hop_count"] is None
    assert doc["steps"] == []
    f.case.close()


def test_path_without_explain_omits_entities_key(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    doc = graph_service.path(
        f.case, "e-a", "e-b", max_depth=10, direction=GraphDirection.OUT, explain=False
    )
    assert "entities" not in doc


def test_paths_evidence_independence_null_for_single_chain(tmp_path: Path) -> None:
    """fully_evidence_independent must be None (not False, and never a
    default True) when fewer than 2 chains exist -- see
    correlate.graph.PathsEvidenceOverlap's own docstring."""
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    doc = graph_service.paths(
        f.case,
        "e-a",
        "e-b",
        max_depth=10,
        direction=GraphDirection.OUT,
        limit=10,
        explain=True,
    )
    assert len(doc["paths"]) == 1
    assert doc["evidence_independence"]["fully_evidence_independent"] is None


def test_paths_evidence_independence_detects_shared_evidence(tmp_path: Path) -> None:
    """A diamond (a->b->d, a->c->d) where every edge cites the same
    EvidenceItem: two structurally distinct chains, but NOT evidence-
    independent -- the structural fact and the evidence fact must stay
    separate, never collapsed into "independently corroborated"."""
    f = _Fixture(tmp_path)
    for name in ("e-a", "e-b", "e-c", "e-d"):
        f.entity(name)
    f.edge("e-a", "e-b")
    f.edge("e-b", "e-d")
    f.edge("e-a", "e-c")
    f.edge("e-c", "e-d")
    doc = graph_service.paths(
        f.case,
        "e-a",
        "e-d",
        max_depth=10,
        direction=GraphDirection.OUT,
        limit=10,
        explain=True,
    )
    assert len(doc["paths"]) == 2  # structurally distinct: yes
    overlap = doc["evidence_independence"]
    assert overlap["fully_evidence_independent"] is False  # evidence-independent: no
    assert overlap["shared_evidence_ids"] == [f.evidence.id]
    f.case.close()


def test_paths_invalid_limit_raises_validation_error(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    with pytest.raises(ValidationError):
        graph_service.paths(
            f.case,
            "e-a",
            "e-b",
            max_depth=10,
            direction=GraphDirection.OUT,
            limit=0,
            explain=False,
        )
    f.case.close()


def test_components_groups_weakly_connected_entities(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    for name in ("e-a", "e-b", "e-c"):
        f.entity(name)
    f.edge("e-a", "e-b")
    doc = graph_service.components(f.case, min_size=1, explain=False)
    assert doc["total_components_found"] == 1
    assert doc["components"][0]["entity_ids"] == ["e-a", "e-b"]
    f.case.close()


def test_components_invalid_min_size_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(ValidationError):
        graph_service.components(f.case, min_size=0, explain=False)
    f.case.close()


# -- contradictions_service --------------------------------------------------


def test_list_contradictions_empty_when_no_conflicts(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    assert contradictions_service.list_contradictions(f.case) == []
    f.case.close()


# -- evidence_service ------------------------------------------------------


def test_resolve_evidence_finds_evidence_item(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    doc = evidence_service.resolve_evidence(f.case, f.evidence.id)
    assert doc["kind"] == "evidence_item"
    assert doc["evidence_item"]["source_adapter"] == "test"
    f.case.close()


def test_resolve_evidence_unknown_id_is_not_found_not_an_error(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    doc = evidence_service.resolve_evidence(f.case, "dangling-id")
    assert doc["kind"] == "not_found"
    assert doc["evidence_item"] is None
    assert doc["normalized_event"] is None
    f.case.close()
