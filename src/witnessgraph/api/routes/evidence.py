from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.service import evidence_service
from witnessgraph.store.case import Case

router = APIRouter(prefix="/evidence", tags=["evidence"])


@router.get("")
def list_evidence(
    source_adapter: str | None = Query(None, description="Only include items from this adapter."),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(evidence_service.list_evidence(case, source_adapter=source_adapter))


@router.get("/{ref_id}")
def resolve_evidence(ref_id: str, case: Case = Depends(get_case)) -> Response:
    """Resolve one EvidenceItem/NormalizedEvent id.

    Always 200: the response body's own ``kind`` field distinguishes
    ``"evidence_item"``/``"normalized_event"``/``"not_found"`` -- see
    ``witnessgraph.service.evidence_service.resolve_evidence``.
    """
    return json_response(evidence_service.resolve_evidence(case, ref_id))
