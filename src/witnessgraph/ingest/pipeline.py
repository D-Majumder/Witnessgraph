"""ingest_source: run one adapter over one source, storing everything into a Case.

This is the only place a timestamp string is interpreted into a
TimeAssertion -- adapters themselves never guess at time (DESIGN.md
principle 3). A timestamp is only accepted if it parses as a
timezone-aware ISO-8601 datetime; an ambiguous (naive) timestamp is left
unparsed rather than assumed to be in some particular timezone.
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
    """Run ``adapter`` over ``source``, storing everything it yields into ``case``."""
    evidence_count = 0
    normalized_event_count = 0
    time_assertion_count = 0

    for evidence, normalized in adapter.ingest(source, collected_at=collected_at):
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
    return TimeAssertion(
        subject_event_id=event.id,
        value=value,
        precision=TimePrecision.SECOND,
        source_evidence_id=evidence.id,
        asserted_by=f"adapter:{evidence.source_adapter}",
        created_at=evidence.collected_at,
    )
