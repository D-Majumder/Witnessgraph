"""docs/phase3-v0.3-design.md §8/§9/§15: SQLite transaction atomicity for
ingestion, and idempotent re-ingestion.

Covers: the atomic unit (one ingest_source call), failure-injection at
every position in a multi-record source (assert full rollback -- zero
partial writes survive), repeated ingestion converging instead of
duplicating (the exact empirical regression the design doc names in
§1/§15), and that EvidenceItem's existing merge-custody behavior is
unaffected by the new transaction wrapping.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.store.case import Case

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _RaisingAdapter:
    """Wraps a real adapter but raises partway through, after N records have
    already been yielded -- used to simulate a crash mid-ingest at every
    possible position in a multi-record source."""

    adapter_id = "jsonl"
    adapter_version = "0.1.0"

    def __init__(self, inner: JsonlAdapter, fail_after: int) -> None:
        self._inner = inner
        self._fail_after = fail_after

    def can_handle(self, source: SourceDescriptor) -> bool:
        return self._inner.can_handle(source)

    def ingest(
        self, source: SourceDescriptor, *, collected_at: datetime
    ) -> Iterator[tuple[EvidenceItem, NormalizedEvent | None, bytes]]:
        for i, record in enumerate(self._inner.ingest(source, collected_at=collected_at)):
            if i >= self._fail_after:
                raise RuntimeError(f"simulated crash after {self._fail_after} record(s)")
            yield record


@pytest.mark.parametrize("fail_after", [0, 1, 2, 3, 4])
def test_crash_mid_ingest_leaves_zero_partial_writes(tmp_path: Path, fail_after: int) -> None:
    """For every possible crash position in the 5-record fixture, the case
    must contain either everything the crashed attempt would have written,
    or nothing from it -- never a partial slice."""
    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    adapter = _RaisingAdapter(JsonlAdapter(), fail_after=fail_after)

    with pytest.raises(RuntimeError, match="simulated crash"):
        ingest_source(case, adapter, source, collected_at=NOW)

    assert case.store.list_evidence() == []
    assert case.store.list_normalized_events() == []
    assert case.store.list_time_assertions() == []
    case.close()


def test_successful_ingest_after_a_crash_still_succeeds_and_is_complete(tmp_path: Path) -> None:
    """The documented recovery procedure -- just re-run the same ingest
    command -- must actually work: a crashed attempt must not leave
    anything behind that would interfere with a clean retry."""
    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")

    with pytest.raises(RuntimeError):
        ingest_source(case, _RaisingAdapter(JsonlAdapter(), fail_after=2), source, collected_at=NOW)
    assert case.store.list_evidence() == []

    result = ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    assert result.evidence_count == 5
    assert result.normalized_event_count == 4
    assert len(case.store.list_evidence()) == 5
    assert len(case.store.list_normalized_events()) == 4
    case.close()


def test_reingesting_same_source_does_not_duplicate_normalized_events_or_time_assertions(
    tmp_path: Path,
) -> None:
    """The exact empirical regression from docs/phase3-v0.3-design.md §1:
    re-running ingestion of an already-ingested source must converge, not
    double, evidence/normalized-event/time-assertion counts."""
    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")

    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    after_first = (
        len(case.store.list_evidence()),
        len(case.store.list_normalized_events()),
        len(case.store.list_time_assertions()),
    )

    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    after_second = (
        len(case.store.list_evidence()),
        len(case.store.list_normalized_events()),
        len(case.store.list_time_assertions()),
    )

    assert after_first == (5, 4, 4)
    assert after_second == after_first  # converged, not duplicated
    case.close()


def test_reingesting_same_source_at_different_wall_clock_times_yields_same_manifest(
    tmp_path: Path,
) -> None:
    """docs/phase3-v0.3-design.md §1's second empirical finding: ingesting the
    same source into two fresh cases at two different wall-clock times must
    now produce identical manifest hashes."""
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    later = datetime(2026, 3, 1, tzinfo=UTC)

    case_a = Case.create(tmp_path / "a")
    ingest_source(case_a, JsonlAdapter(), source, collected_at=NOW)
    hash_a = case_a.compute_manifest().manifest_hash
    case_a.close()

    case_b = Case.create(tmp_path / "b")
    ingest_source(case_b, JsonlAdapter(), source, collected_at=later)
    hash_b = case_b.compute_manifest().manifest_hash
    case_b.close()

    assert hash_a == hash_b


def test_store_transaction_rolls_back_evidence_merge_writes_too(tmp_path: Path) -> None:
    """The transaction boundary must cover put_evidence's merge path too, not
    just the insert-if-absent paths for normalized events/time assertions."""
    case = Case.create(tmp_path / "case")
    first = EvidenceItem.create(
        raw_bytes=b"payload",
        source_adapter="test",
        adapter_version="0.0.0",
        source_locator="a",
        collected_at=NOW,
    )
    case.store.put_evidence(first)

    with pytest.raises(RuntimeError):
        with case.transaction():
            second = EvidenceItem.create(
                raw_bytes=b"payload",
                source_adapter="test",
                adapter_version="0.0.0",
                source_locator="b",
                collected_at=NOW,
            )
            case.store.put_evidence(second)  # merges custody in-memory, not yet committed
            raise RuntimeError("simulated failure before commit")

    stored = case.store.get_evidence(first.id)
    assert stored is not None
    assert len(stored.chain_of_custody) == 1  # the merge from inside the failed block did not stick
    case.close()


def test_transaction_context_manager_nests_without_double_committing(tmp_path: Path) -> None:
    """A nested transaction() call (library code calling into another
    function that also opens one) must join the outer transaction rather
    than committing early -- exercises the re-entrancy guard directly."""
    case = Case.create(tmp_path / "case")
    ev1 = EvidenceItem.create(
        raw_bytes=b"one", source_adapter="t", adapter_version="0", source_locator="a",
        collected_at=NOW,
    )
    ev2 = EvidenceItem.create(
        raw_bytes=b"two", source_adapter="t", adapter_version="0", source_locator="b",
        collected_at=NOW,
    )

    with case.transaction():
        case.store.put_evidence(ev1)
        with case.transaction():  # nested -- must not commit yet
            case.store.put_evidence(ev2)

    assert len(case.store.list_evidence()) == 2
    case.close()
