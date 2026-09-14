from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.api.schemas import AckRequest
from witnessgraph.service import contradiction_findings_service
from witnessgraph.store.case import Case

router = APIRouter(prefix="/contradiction-findings", tags=["contradiction-findings"])


@router.get("")
def list_contradiction_findings(case: Case = Depends(get_case)) -> Response:
    return json_response(contradiction_findings_service.list_contradiction_findings(case))


@router.get("/{contradiction_id}")
def get_contradiction_finding(contradiction_id: str, case: Case = Depends(get_case)) -> Response:
    return json_response(
        contradiction_findings_service.get_contradiction_finding(case, contradiction_id)
    )


@router.post("/{contradiction_id}/ack")
def ack_contradiction_finding(
    contradiction_id: str, body: AckRequest, case: Case = Depends(get_case)
) -> Response:
    """Replace this tracked contradiction's review annotation -- see
    ``findings.ack_finding``. Never implies either disagreeing assertion
    was determined to be true."""
    return json_response(
        contradiction_findings_service.ack_contradiction_finding(
            case, contradiction_id, status=body.status, by=body.by, note=body.note
        )
    )
