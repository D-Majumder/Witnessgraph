"""ingest_source: run one adapter over one source, storing everything into a Case.

This is the only place a timestamp string is interpreted into a
TimeAssertion -- adapters themselves never guess at time (DESIGN.md
principle 3). A timestamp is only accepted if it parses as a
timezone-aware ISO-8601 datetime; an ambiguous (naive) timestamp is left
unparsed rather than assumed to be in some particular timezone.

See docs/phase3-v0.3-design.md §8/§9 for the crash/transaction model
this function now implements:

- **Atomic unit**: one call to ``ingest_source`` (i.e. one ``witnessgraph
  ingest <case> <adapter> <source>`` invocation) is the unit that either
  fully succeeds or leaves the case's SQLite metadata exactly as it was
  before the call started. Every ``put_evidence``/``put_normalized_event``/
  ``put_time_assertion`` write the adapter's records produce is grouped
  into one ``case.transaction()`` block; an exception anywhere in the
  loop (an adapter raising, a store write failing) rolls all of them
  back together.
- **Blob-write ordering (§6.7/§8)**: ``case.blobs.put(raw_bytes)`` is
  called for every record *before* that record's SQLite writes, and
  outside the SQL transaction (a filesystem write cannot participate in
  a SQLite transaction). ``FileBlobStore.put`` is self-idempotent
  (content-addressed, stage-to-temp-then-atomic-rename), so if the
  process crashes after a blob write but before the SQL transaction
  commits, the result is a harmless orphaned blob file with no metadata
  row pointing at it yet -- safe to leave; a retry re-ingest simply
  writes the same blob again as a no-op. The reverse ordering (SQL
  first) is rejected because it could leave a committed
  ``EvidenceItem.raw_content_hash`` with no corresponding stored blob --
  a real integrity gap, not just an orphaned file.
- **Retry semantics**: because both the blob write and (as of v0.3) the
  ``NormalizedEvent``/``TimeAssertion`` writes are idempotent, re-running
  ``ingest_source`` with the same source after an interruption is always
  safe: already-committed records are re-derived to the same ids/blobs
  and are no-ops; only genuinely new records (from the point where the
  previous attempt stopped) are newly written.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.ingest.base import EvidenceAdapter, SourceDescriptor
from witnessgraph.store.case import Case


@dataclass(frozen=True)
class IngestResult:
    evidence_count: int
    normalized_event_count: int
    time_assertion_count: int


def ingest_source(
    case: Case,
    adapter: EvidenceAdapter,
    source: SourceDescriptor,
    *,
    collected_at: datetime,
    asserted_by: str = "analyst",
) -> IngestResult:
    """Run ``adapter`` over ``source``, storing everything it yields into ``case``.

    All-or-nothing at the SQLite level: see this module's docstring for
    the transaction/blob-ordering model.
    """
    evidence_count = 0
    normalized_event_count = 0
    time_assertion_count = 0

    with case.transaction():
        for evidence, normalized, raw_bytes in adapter.ingest(source, collected_at=collected_at):
            case.blobs.put(raw_bytes)  # blob-first ordering -- see module docstring

            case.store.put_evidence(evidence)
            evidence_count += 1

            if normalized is not None:
                case.store.put_normalized_event(normalized)
                normalized_event_count += 1

                assertion = _derive_time_assertion(normalized, evidence)
                if assertion is not None:
                    case.store.put_time_assertion(assertion)
                    time_assertion_count += 1

    return IngestResult(evidence_count, normalized_event_count, time_assertion_count)


def _derive_time_assertion(event: NormalizedEvent, evidence: EvidenceItem) -> TimeAssertion | None:
    raw_ts = event.attributes.get("timestamp")
    if not raw_ts:
        return None
    try:
        value = datetime.fromisoformat(raw_ts)
    except ValueError:
        return None
    if value.tzinfo is None:
        return None  # ambiguous timezone; do not guess (DESIGN.md principle 3)
    return TimeAssertion.create(
        subject_event_id=event.id,
        value=value,
        precision=TimePrecision.SECOND,
        source_evidence_id=evidence.id,
        asserted_by=f"adapter:{evidence.source_adapter}",
        created_at=evidence.collected_at,
    )
