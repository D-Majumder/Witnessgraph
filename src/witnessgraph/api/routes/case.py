from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.service import case_service
from witnessgraph.store.case import Case

router = APIRouter(tags=["case"])


@router.get("/case")
def read_case_overview(case: Case = Depends(get_case)) -> Response:
    """Case identity, counts, and manifest verdict -- the Overview view's data."""
    return json_response(case_service.get_case_overview(case))
