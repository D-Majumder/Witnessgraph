from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.service import timeline_service
from witnessgraph.store.case import Case

router = APIRouter(tags=["timeline"])


@router.get("/timeline")
def get_timeline(
    event_type: str | None = Query(None, description="Only include events of this type."),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(timeline_service.get_timeline(case, event_type=event_type))
