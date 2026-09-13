"""SqliteStore / FileBlobStore round-trip and content-addressing behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis, HypothesisStatus
from witnessgraph.core.relationships import Relationship
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.store.case import Case
from witnessgraph.store.sqlite_store import FileBlobStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_evidence_round_trips_through_store(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    item = EvidenceItem.create(
        raw_bytes=b"payload",
        source_adapter="test",
        adapter_version="0.0.0",
        source_locator="x",
        collected_at=NOW,
    )
    case.store.put_evidence(item)
    fetched = case.store.get_evidence(item.id)
    assert fetched == item
    case.close()


def test_relationship_round_trips_through_store(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    rel = Relationship.create(
        relationship_type="connected_to",
        source_entity_id="entity-a",
        target_entity_id="entity-b",
        derived_from=("ev-1",),
        created_at=NOW,
        attributes={"protocol": "tcp"},
    )
    case.store.put_relationship(rel)
    fetched = case.store.get_relationship(rel.id)
    assert fetched == rel
    case.close()


def test_relationship_put_is_idempotent_by_content_derived_id(tmp_path: Path) -> None:
    """Re-running `relationships create` with identical arguments must
    converge, not duplicate -- mirrors TimeAssertion's put semantics."""
    case = Case.create(tmp_path / "case")
    rel = Relationship.create(
        relationship_type="connected_to",
        source_entity_id="entity-a",
        target_entity_id="entity-b",
        derived_from=("ev-1",),
        created_at=NOW,
    )
    rel_again = Relationship.create(
        relationship_type="connected_to",
        source_entity_id="entity-a",
        target_entity_id="entity-b",
        derived_from=("ev-1",),
        created_at=NOW.replace(year=2030),  # different wall clock, same identity
    )
    assert rel.id == rel_again.id
    case.store.put_relationship(rel)
    case.store.put_relationship(rel_again)
    assert len(case.store.list_relationships()) == 1
    stored = case.store.get_relationship(rel.id)
    assert stored is not None
    assert stored.created_at == rel.created_at  # first write wins, no overwrite
    case.close()


def test_relationship_not_found_returns_none(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    assert case.store.get_relationship("no-such-id") is None
    case.close()


def test_hypothesis_upsert_reflects_status_change(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ref = EvidenceRef(kind="evidence_item", id="x" * 64)
    hyp = Hypothesis(
        statement="X", supporting_evidence=(ref,), inferred_by="analyst:a", created_at=NOW
    )
    case.store.put_hypothesis(hyp)

    updated = hyp.with_status(HypothesisStatus.SUPPORTED)
    case.store.put_hypothesis(updated)

    stored = case.store.get_hypothesis(hyp.id)
    assert stored is not None
    assert stored.status == HypothesisStatus.SUPPORTED
    assert len(case.store.list_hypotheses()) == 1  # same id, not duplicated
    case.close()


def test_blob_store_is_content_addressed(tmp_path: Path) -> None:
    blobs = FileBlobStore(tmp_path / "blobs")
    digest = blobs.put(b"some evidence bytes")
    assert blobs.has(digest)
    assert blobs.get(digest) == b"some evidence bytes"


def test_blob_store_put_is_idempotent(tmp_path: Path) -> None:
    blobs = FileBlobStore(tmp_path / "blobs")
    d1 = blobs.put(b"same content")
    d2 = blobs.put(b"same content")
    assert d1 == d2


def test_blob_store_different_content_different_address(tmp_path: Path) -> None:
    blobs = FileBlobStore(tmp_path / "blobs")
    assert blobs.put(b"a") != blobs.put(b"b")


def test_case_create_refuses_nonempty_directory(tmp_path: Path) -> None:
    import pytest

    target = tmp_path / "occupied"
    target.mkdir()
    (target / "file.txt").write_text("hi")
    with pytest.raises(FileExistsError):
        Case.create(target)


def test_duplicate_content_from_different_sources_preserves_both_provenance(
    tmp_path: Path,
) -> None:
    """C1 regression: re-ingesting identical bytes from a different source must
    not destroy the first source's identity or custody history -- it must merge.
    """
    case = Case.create(tmp_path / "case")
    later = datetime(2026, 1, 2, tzinfo=UTC)

    first = EvidenceItem.create(
        raw_bytes=b"identical payload",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="file1.jsonl:1",
        collected_at=NOW,
    )
    case.store.put_evidence(first)

    second = EvidenceItem.create(
        raw_bytes=b"identical payload",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="file2.jsonl:5",
        collected_at=later,
    )
    case.store.put_evidence(second)

    stored = case.store.get_evidence(first.id)
    assert stored is not None
    assert stored.id == first.id == second.id  # content-addressed identity unchanged

    # The first-known source identity is preserved, not overwritten by the second.
    assert stored.source_locator == "file1.jsonl:1"
    assert stored.collected_at == NOW

    # Both sources' provenance is represented in the merged custody history.
    assert len(stored.chain_of_custody) == 2
    locators = {record.source_locator for record in stored.chain_of_custody}
    assert locators == {"file1.jsonl:1", "file2.jsonl:5"}

    assert len(case.store.list_evidence()) == 1  # still one logical evidence item
    case.close()


def test_get_time_assertion_returns_none_for_unknown_id(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    assert case.store.get_time_assertion("nonexistent") is None
    case.close()


def test_time_assertion_round_trips_through_get(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    evidence = EvidenceItem.create(
        raw_bytes=b"payload", source_adapter="test", adapter_version="0.0.0",
        source_locator="x", collected_at=NOW,
    )
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line", attributes={}, derived_from=(evidence.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    assertion = TimeAssertion.create(
        subject_event_id=event.id, value=NOW, precision=TimePrecision.SECOND,
        source_evidence_id=evidence.id, asserted_by="analyst:jane", created_at=NOW,
    )
    case.store.put_time_assertion(assertion)

    fetched = case.store.get_time_assertion(assertion.id)
    assert fetched == assertion
    case.close()


def test_reingesting_same_source_does_not_duplicate_custody(tmp_path: Path) -> None:
    """C1 regression: re-running ingestion of the *same* source (e.g. re-running
    the tool) must be a safe no-op, not a second custody record.
    """
    case = Case.create(tmp_path / "case")

    def make() -> EvidenceItem:
        return EvidenceItem.create(
            raw_bytes=b"same content, same source",
            source_adapter="jsonl",
            adapter_version="0.1.0",
            source_locator="file1.jsonl:1",
            collected_at=NOW,
        )

    case.store.put_evidence(make())
    case.store.put_evidence(make())
    case.store.put_evidence(make())

    stored = case.store.get_evidence(make().id)
    assert stored is not None
    assert len(stored.chain_of_custody) == 1
    case.close()
