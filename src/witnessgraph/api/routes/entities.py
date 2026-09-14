from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.service import entities_service
from witnessgraph.store.case import Case

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("")
def list_entities(
    entity_type: str | None = Query(None, description="Only include entities of this type."),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(entities_service.list_entities(case, entity_type=entity_type))


@router.get("/{entity_id}")
def get_entity(entity_id: str, case: Case = Depends(get_case)) -> Response:
    return json_response(entities_service.get_entity(case, entity_id))
