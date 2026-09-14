"""witnessgraph.api: the local-only FastAPI backend (UI v1).

Exercises the API through Starlette's TestClient against a real Case
directory (a temporary SqliteStore-backed case, same style as
test_graph_cli.py's own CLI-subprocess-free fixtures) -- never a mock of
the service layer, so these tests also validate the API-to-service wiring
itself. Covers: JSON contract stability, the case-binding security
boundary (no request ever supplies a filesystem path), error-code
mapping, and the evidence-independence/provenance semantics the
architecture calls out as load-bearing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from witnessgraph.api.app import create_app
from witnessgraph.core.entities import Entity
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.relationships import Relationship
from witnessgraph.service.errors import CaseNotFoundError
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Fixture:
    """Builds a small case directory and hands back a bound TestClient."""

    def __init__(self, tmp_path: Path) -> None:
        self.case_dir = tmp_path / "case"
        self.case = Case.create(self.case_dir)
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

    def client(self) -> TestClient:
        """Close the write handle used to build the fixture, then bind a
        fresh app -- mirrors how a real server only ever opens the case
        per-request, never holding one long-lived write connection open
        alongside the API's own per-request Case."""
        self.case.record_manifest()
        self.case.close()
        return TestClient(create_app(self.case_dir))


@pytest.fixture
def diamond(tmp_path: Path) -> TestClient:
    """a -> b -> d and a -> c -> d, every edge citing the same EvidenceItem."""
    f = _Fixture(tmp_path)
    for name in ("e-a", "e-b", "e-c", "e-d"):
        f.entity(name)
    f.edge("e-a", "e-b")
    f.edge("e-b", "e-d")
    f.edge("e-a", "e-c")
    f.edge("e-c", "e-d")
    return f.client()


# -- server construction / security boundary --------------------------------


def test_create_app_rejects_missing_case_directory(tmp_path: Path) -> None:
    with pytest.raises(CaseNotFoundError):
        create_app(tmp_path / "does-not-exist")


def test_no_route_accepts_a_case_directory_parameter(tmp_path: Path) -> None:
    """The one real risk a server introduces over the CLI: an endpoint
    that accepts a filesystem path. None of this API's routes do --
    every route's only inputs are entity/relationship ids and small
    bounded integers/enums; the case directory is fixed at server
    startup (app.state.case_dir) and never appears in a URL or body."""
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    openapi = client.get("/openapi.json").json()
    for _path, methods in openapi["paths"].items():
        for _method, spec in methods.items():
            for param in spec.get("parameters", []):
                name = param["name"].lower()
                assert "path" not in name or name in ("entity_id", "relationship_id")
                assert name not in ("dir", "case_dir", "directory")
                assert "file" not in name


def test_cors_does_not_allow_wildcard_origin(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    response = client.options(
        "/case",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "*"
    assert "evil.example" not in response.headers.get("access-control-allow-origin", "")


def test_cors_allows_the_default_frontend_dev_origin(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    response = client.options(
        "/case",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


# -- /case --------------------------------------------------------------


def test_case_overview_shape(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    client = f.client()
    response = client.get("/case")
    assert response.status_code == 200
    doc = response.json()
    assert doc["entity_count"] == 2
    assert doc["relationship_count"] == 1
    assert doc["manifest_verdict"] == "MATCH"


# -- /entities ------------------------------------------------------------


def test_list_and_get_entity(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a", entity_type="host", hostname="a")
    client = f.client()

    listing = client.get("/entities")
    assert listing.status_code == 200
    assert [e["id"] for e in listing.json()] == ["e-a"]

    detail = client.get("/entities/e-a")
    assert detail.status_code == 200
    assert detail.json()["identifiers"] == {"hostname": "a"}


def test_get_unknown_entity_is_404_not_500(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    response = client.get("/entities/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "no such entity: nope"}


def test_list_entities_filtered_by_type(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a", entity_type="host")
    f.entity("e-b", entity_type="user")
    client = f.client()
    response = client.get("/entities", params={"entity_type": "user"})
    assert [e["id"] for e in response.json()] == ["e-b"]


# -- /relationships -------------------------------------------------------


def test_list_and_get_relationship_with_lineage(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    rel = f.edge("e-a", "e-b")
    client = f.client()

    listing = client.get("/relationships")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    detail = client.get(f"/relationships/{rel.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["evidence_lineage"][0]["kind"] == "evidence_item"
    assert body["evidence_lineage"][0]["evidence_item"]["source_adapter"] == "test"


def test_get_unknown_relationship_is_404(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    response = client.get("/relationships/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "no such relationship: nope"}


def test_list_relationships_filtered_by_entity(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    for name in ("e-a", "e-b", "e-c"):
        f.entity(name)
    f.edge("e-a", "e-b")
    f.edge("e-b", "e-c")
    client = f.client()
    response = client.get("/relationships", params={"entity_id": "e-a"})
    assert len(response.json()) == 1


# -- /graph -----------------------------------------------------------------


def test_graph_neighbors(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    client = f.client()
    response = client.get("/graph/neighbors", params={"entity_id": "e-a"})
    assert response.status_code == 200
    doc = response.json()
    assert [r["entity_id"] for r in doc["reached"]] == ["e-b"]
    assert "entities" in doc  # always resolved for the API -- see §14


def test_graph_neighbors_unknown_entity_is_404(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    client = f.client()
    response = client.get("/graph/neighbors", params={"entity_id": "nope"})
    assert response.status_code == 404


def test_graph_neighbors_invalid_max_depth_is_400_not_500(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    response = client.get(
        "/graph/neighbors", params={"entity_id": "e-a", "max_depth": 9999}
    )
    assert response.status_code == 400
    assert "max_depth" in response.json()["detail"]


def test_graph_path_found_and_not_found_are_distinguished(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.entity("e-c")
    f.edge("e-a", "e-b")
    client = f.client()

    found = client.get(
        "/graph/path", params={"source_entity_id": "e-a", "target_entity_id": "e-b"}
    )
    assert found.json()["found"] is True

    not_found = client.get(
        "/graph/path", params={"source_entity_id": "e-a", "target_entity_id": "e-c"}
    )
    assert not_found.status_code == 200  # a valid, negative result -- never an error
    assert not_found.json()["found"] is False
    assert not_found.json()["steps"] == []


def test_graph_paths_evidence_independence_never_defaults_to_true(diamond: TestClient) -> None:
    response = diamond.get(
        "/graph/paths", params={"source_entity_id": "e-a", "target_entity_id": "e-d"}
    )
    assert response.status_code == 200
    doc = response.json()
    assert len(doc["paths"]) == 2  # structural fact: 2 distinct chains
    overlap = doc["evidence_independence"]
    assert overlap["fully_evidence_independent"] is False  # evidence fact: shared evidence
    assert len(overlap["shared_evidence_ids"]) == 1


def test_graph_paths_single_chain_independence_is_indeterminate_not_true(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    client = f.client()
    response = client.get(
        "/graph/paths", params={"source_entity_id": "e-a", "target_entity_id": "e-b"}
    )
    doc = response.json()
    assert len(doc["paths"]) == 1
    assert doc["evidence_independence"]["fully_evidence_independent"] is None


def test_graph_components(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    f.edge("e-a", "e-b")
    client = f.client()
    response = client.get("/graph/components")
    assert response.status_code == 200
    doc = response.json()
    assert doc["total_components_found"] == 1


# -- /contradictions ----------------------------------------------------


def test_contradictions_empty_case_returns_empty_list_not_error(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    response = client.get("/contradictions")
    assert response.status_code == 200
    assert response.json() == []


# -- /evidence ------------------------------------------------------------


def test_resolve_evidence_by_id(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    evidence_id = f.evidence.id
    f.entity("e-a")
    client = f.client()
    response = client.get(f"/evidence/{evidence_id}")
    assert response.status_code == 200
    assert response.json()["kind"] == "evidence_item"


def test_resolve_unknown_evidence_is_200_not_404(tmp_path: Path) -> None:
    """A dangling derived_from id is a documented, reportable outcome of
    this engine, not a 404 -- resolve_evidence is a resolution report,
    not a resource lookup."""
    f = _Fixture(tmp_path)
    f.entity("e-a")
    client = f.client()
    response = client.get("/evidence/dangling-id")
    assert response.status_code == 200
    assert response.json()["kind"] == "not_found"


# -- datetime encoding contract -------------------------------------------


def test_datetimes_are_z_suffixed_utc(tmp_path: Path) -> None:
    """Every timestamp the API returns must match the CLI's own
    canonical_json_bytes encoding: UTC, 'Z'-suffixed, never '+00:00'."""
    f = _Fixture(tmp_path)
    f.entity("e-a")
    f.entity("e-b")
    rel = f.edge("e-a", "e-b")
    client = f.client()
    response = client.get(f"/relationships/{rel.id}")
    collected_at = response.json()["evidence_lineage"][0]["evidence_item"]["collected_at"]
    assert collected_at == "2026-01-01T00:00:00Z"
