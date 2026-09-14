from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.api.schemas import AckRequest
from witnessgraph.service import findings_service
from witnessgraph.store.case import Case

router = APIRouter(prefix="/findings", tags=["findings"])


@router.get("")
def list_findings(case: Case = Depends(get_case)) -> Response:
    return json_response(findings_service.list_findings(case))


@router.get("/{finding_id}")
def get_finding(finding_id: str, case: Case = Depends(get_case)) -> Response:
    return json_response(findings_service.get_finding(case, finding_id))


@router.post("/{finding_id}/ack")
def ack_finding(finding_id: str, body: AckRequest, case: Case = Depends(get_case)) -> Response:
    """Replace this finding's review annotation -- the one write
    operation, requiring an explicit, non-blank analyst identity."""
    return json_response(
        findings_service.ack_finding(
            case, finding_id, status=body.status, by=body.by, note=body.note
        )
    )
