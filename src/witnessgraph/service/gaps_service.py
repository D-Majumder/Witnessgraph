"""Coverage-gap analysis + tracking -- thin wrappers over ``correlate.gaps``/``correlate.tracking``.

Mirrors ``cli.main.gaps``'s own validation and read-then-persist
ordering exactly: the full, read-only analysis always completes before
any persistence is attempted, and tracking happens inside one
transaction so a partial failure never leaves half the findings
persisted.
"""

from __future__ import annotations

from witnessgraph.correlate.gaps import (
    DEFAULT_MIN_CORROBORATING_EVENTS,
    find_gaps,
    gap_analysis_to_json,
)
from witnessgraph.correlate.tracking import track_findings
from witnessgraph.service.errors import ValidationError
from witnessgraph.store.case import Case


def _validate_min_corroborating_events(min_corroborating_events: int) -> None:
    if min_corroborating_events < 1:
        raise ValidationError(
            "min_corroborating_events must be at least 1 -- a gap can never be reported on "
            "zero corroborating evidence"
        )


def analyze_gaps(
    case: Case,
    *,
    min_gap_seconds: float,
    min_corroborating_events: int = DEFAULT_MIN_CORROBORATING_EVENTS,
    refine_source_by_attribute: str | None = None,
) -> dict[str, object]:
    """Structural coverage-gap findings -- read-only, never persists anything."""
    _validate_min_corroborating_events(min_corroborating_events)
    result = find_gaps(
        case.store,
        min_gap_seconds=min_gap_seconds,
        min_corroborating_events=min_corroborating_events,
        refine_source_by_attribute=refine_source_by_attribute,
    )
    return gap_analysis_to_json(result)


def track_gaps(
    case: Case,
    *,
    min_gap_seconds: float,
    min_corroborating_events: int = DEFAULT_MIN_CORROBORATING_EVENTS,
    refine_source_by_attribute: str | None = None,
) -> dict[str, object]:
    """Re-run the same analysis and persist each finding as a
    TrackedGapFinding (insert-if-absent -- see ``correlate.tracking.track_findings``).

    Returns ``{"new": N, "already_tracked": M}``, mirroring the CLI's own
    ``--track`` summary exactly.
    """
    _validate_min_corroborating_events(min_corroborating_events)
    result = find_gaps(
        case.store,
        min_gap_seconds=min_gap_seconds,
        min_corroborating_events=min_corroborating_events,
        refine_source_by_attribute=refine_source_by_attribute,
    )
    with case.transaction():
        outcomes = track_findings(
            case.store,
            result,
            min_gap_seconds=min_gap_seconds,
            min_corroborating_events=min_corroborating_events,
        )
    new_count = sum(1 for o in outcomes if o.newly_created)
    return {"new": new_count, "already_tracked": len(outcomes) - new_count}
