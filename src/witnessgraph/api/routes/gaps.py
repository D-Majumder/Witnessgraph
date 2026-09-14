from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.correlate.gaps import DEFAULT_MIN_CORROBORATING_EVENTS
from witnessgraph.service import gaps_service
from witnessgraph.store.case import Case

router = APIRouter(prefix="/gaps", tags=["gaps"])


@router.get("")
def analyze_gaps(
    min_gap_seconds: float = Query(
        ...,
        description=(
            "Minimum gap duration (seconds) to report. Required -- no default is claimed "
            "to be objectively correct; choose per case."
        ),
    ),
    min_corroborating_events: int = Query(DEFAULT_MIN_CORROBORATING_EVENTS),
    refine_source_by_attribute: str | None = Query(
        None, description="Optional NormalizedEvent attribute to subdivide each declared source by."
    ),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(
        gaps_service.analyze_gaps(
            case,
            min_gap_seconds=min_gap_seconds,
            min_corroborating_events=min_corroborating_events,
            refine_source_by_attribute=refine_source_by_attribute,
        )
    )


@router.post("/track")
def track_gaps(
    min_gap_seconds: float = Query(...),
    min_corroborating_events: int = Query(DEFAULT_MIN_CORROBORATING_EVENTS),
    refine_source_by_attribute: str | None = Query(None),
    case: Case = Depends(get_case),
) -> Response:
    """Re-run the same analysis and persist each finding found -- write.
    See ``witnessgraph.service.gaps_service.track_gaps``."""
    return json_response(
        gaps_service.track_gaps(
            case,
            min_gap_seconds=min_gap_seconds,
            min_corroborating_events=min_corroborating_events,
            refine_source_by_attribute=refine_source_by_attribute,
        )
    )
