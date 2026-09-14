from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.service import contradictions_service
from witnessgraph.store.case import Case

router = APIRouter(tags=["contradictions"])


@router.get("/contradictions")
def list_contradictions(case: Case = Depends(get_case)) -> Response:
    return json_response(contradictions_service.list_contradictions(case))
