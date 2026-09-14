from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.service import relationships_service
from witnessgraph.store.case import Case

router = APIRouter(prefix="/relationships", tags=["relationships"])


@router.get("")
def list_relationships(
    entity_id: str | None = Query(
        None, description="Only include relationships where this entity is the source or target."
    ),
    relationship_type: str | None = Query(
        None, description="Only include relationships of this type."
    ),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(
        relationships_service.list_relationships(
            case, entity_id=entity_id, relationship_type=relationship_type
        )
    )


@router.get("/{relationship_id}")
def get_relationship(relationship_id: str, case: Case = Depends(get_case)) -> Response:
    """One relationship, with its evidence lineage always resolved -- see
    ``witnessgraph.service.relationships_service.get_relationship``."""
    return json_response(relationships_service.get_relationship(case, relationship_id))
