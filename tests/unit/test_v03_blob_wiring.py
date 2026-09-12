"""docs/phase3-v0.3-design.md §6.7/§8/§9/§15: wiring FileBlobStore into
ingestion.

Covers: every EvidenceItem produced by a real ingest has a corresponding
blob in the case's blob store whose bytes hash to that item's
raw_content_hash; duplicate/re-ingested content is a safe blob no-op;
missing-blob behavior; the blob-before-SQL ordering's crash-recovery
property (a blob written with no corresponding metadata row is a safe,
recoverable state, and a subsequent retry still succeeds); and a focused
failure-injection test where FileBlobStore.put() itself raises during
ingestion (not just the adapter, as in test_v03_transaction_atomicity.py).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from witnessgraph.core.ids import sha256_hex
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.store.case import Case
from witnessgraph.store.sqlite_store import FileBlobStore

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_every_ingested_evidence_item_has_a_matching_blob(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)

    items = case.store.list_evidence()
    assert len(items) == 5
    for item in items:
        assert case.blobs.has(item.raw_content_hash)
        stored_bytes = case.blobs.get(item.raw_content_hash)
        assert sha256_hex(stored_bytes) == item.raw_content_hash
    case.close()


def test_reingesting_same_source_does_not_duplicate_or_corrupt_blobs(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")

    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    first_bytes = {
        item.raw_content_hash: case.blobs.get(item.raw_content_hash)
        for item in case.store.list_evidence()
    }

    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    for item in case.store.list_evidence():
        assert case.blobs.get(item.raw_content_hash) == first_bytes[item.raw_content_hash]
    case.close()


def test_missing_blob_is_distinguishable_from_present_blob(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    assert case.blobs.has("0" * 64) is False
    with pytest.raises(FileNotFoundError):
        case.blobs.get("0" * 64)
    case.close()


def test_orphaned_blob_with_no_metadata_row_is_safe_and_retry_still_succeeds(
    tmp_path: Path,
) -> None:
    """Simulates a crash that happens after the blob write but before the
    SQLite transaction commits (docs/phase3-v0.3-design.md §8/§9): the
    result is an orphaned blob with no matching evidence row. That state
    must not corrupt anything, and re-ingesting the same source afterward
    must still succeed and produce the normal, complete result."""
    case = Case.create(tmp_path / "case")

    # Simulate the orphan directly: a blob written with no metadata row,
    # exactly the reachable post-crash state per the design's ordering rule.
    orphan_hash = case.blobs.put(b"content that will be orphaned")
    assert case.blobs.has(orphan_hash)
    assert case.store.get_evidence(orphan_hash) is None  # no metadata row for it

    # A real ingest afterward is unaffected by the pre-existing orphan.
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    result = ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    assert result.evidence_count == 5
    assert len(case.store.list_evidence()) == 5

    # The orphan itself is untouched, still present, still safe.
    assert case.blobs.has(orphan_hash)
    case.close()


def test_blob_write_ordering_survives_a_crash_partway_through_ingest(tmp_path: Path) -> None:
    """A crash during ingest_source's SQL transaction (after some blobs were
    already written for earlier records) must still leave the case openable
    and safely re-ingestible -- the orphaned blobs from the rolled-back
    attempt do not block a clean retry."""
    from collections.abc import Iterator

    from witnessgraph.core.events import NormalizedEvent
    from witnessgraph.core.evidence import EvidenceItem

    class _RaisesOnThird:
        adapter_id = "jsonl"
        adapter_version = "0.1.0"

        def can_handle(self, source: SourceDescriptor) -> bool:
            return True

        def ingest(
            self, source: SourceDescriptor, *, collected_at: datetime
        ) -> Iterator[tuple[EvidenceItem, NormalizedEvent | None, bytes]]:
            for i, record in enumerate(JsonlAdapter().ingest(source, collected_at=collected_at)):
                if i == 2:
                    raise RuntimeError("simulated crash")
                yield record

    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")

    with pytest.raises(RuntimeError):
        ingest_source(case, _RaisesOnThird(), source, collected_at=NOW)

    # SQL rolled back completely...
    assert case.store.list_evidence() == []
    # ...but the two blobs written before the crash are harmless orphans,
    # and don't prevent a clean, complete retry.
    result = ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    assert result.evidence_count == 5
    for item in case.store.list_evidence():
        assert case.blobs.has(item.raw_content_hash)
    case.close()


class _RaisingBlobStore:
    """Wraps a real FileBlobStore but raises OSError on put() from a given
    call onward -- used to simulate the blob write itself failing (a disk
    error, a permissions problem), as distinct from an adapter raising."""

    def __init__(self, inner: FileBlobStore, fail_from_call: int = 0) -> None:
        self._inner = inner
        self._fail_from_call = fail_from_call
        self._calls = 0

    def put(self, data: bytes) -> str:
        self._calls += 1
        if self._calls > self._fail_from_call:
            raise OSError("simulated blob write failure")
        return self._inner.put(data)

    def get(self, content_hash: str) -> bytes:
        return self._inner.get(content_hash)

    def has(self, content_hash: str) -> bool:
        return self._inner.has(content_hash)


def test_blob_write_failure_rolls_back_and_retry_still_succeeds(tmp_path: Path) -> None:
    """docs/phase3-v0.3-design.md §8/§9 + the adversarial review's requested
    coverage gap: a failure in FileBlobStore.put() itself (not the adapter)
    must propagate, roll back the whole SQL transaction (no invalid
    evidence reference left behind), and a subsequent retry with a working
    blob store must still succeed and produce a complete, correct case."""
    case = Case.create(tmp_path / "case")
    real_blobs = case.blobs
    case.blobs = _RaisingBlobStore(real_blobs, fail_from_call=2)  # type: ignore[assignment]

    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    with pytest.raises(OSError, match="simulated blob write failure"):
        ingest_source(case, JsonlAdapter(), source, collected_at=NOW)

    # No invalid evidence reference: the SQL transaction rolled back fully.
    assert case.store.list_evidence() == []
    assert case.store.list_normalized_events() == []
    assert case.store.list_time_assertions() == []

    # Restore a working blob store; retry must succeed completely.
    case.blobs = real_blobs
    result = ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    assert result.evidence_count == 5
    for item in case.store.list_evidence():
        assert case.blobs.has(item.raw_content_hash)
        assert sha256_hex(case.blobs.get(item.raw_content_hash)) == item.raw_content_hash
    case.close()


def test_blob_write_failure_does_not_corrupt_a_preexisting_valid_blob(tmp_path: Path) -> None:
    """An already-written, valid blob must be untouched by a later, unrelated
    blob-write failure during ingestion -- the failure must not reach or
    modify content that was already safely committed to the blob store."""
    case = Case.create(tmp_path / "case")
    preexisting_hash = case.blobs.put(b"a pre-existing, already-valid blob")
    original_bytes = case.blobs.get(preexisting_hash)

    case.blobs = _RaisingBlobStore(case.blobs, fail_from_call=0)  # type: ignore[assignment]
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    with pytest.raises(OSError, match="simulated blob write failure"):
        ingest_source(case, JsonlAdapter(), source, collected_at=NOW)

    assert case.blobs.get(preexisting_hash) == original_bytes  # untouched, uncorrupted
    case.close()
