"""Graph endpoints.

Every endpoint here always resolves the corresponding
``correlate.graph``'s explainability augmentation (participating
entities, evidence lineage, and -- for ``/graph/paths`` -- evidence-
independence analysis) -- there is no ``?explain=`` toggle in this API.
The CLI's own ``--explain`` flag exists only to keep a human-scale text
listing short by default; a machine JSON caller has no equivalent reason
to receive a deliberately incomplete provenance answer, exactly as
``docs/phase-ui-v1-architecture-design.md`` §14 already decides for the
single-relationship-by-id endpoint (generalized here to every graph
result for the same reason).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from witnessgraph.api.deps import get_case
from witnessgraph.api.responses import json_response
from witnessgraph.correlate.graph import (
    DEFAULT_NEIGHBORS_MAX_DEPTH,
    DEFAULT_PATH_MAX_DEPTH,
    DEFAULT_PATHS_LIMIT,
    GraphDirection,
)
from witnessgraph.service import graph_service
from witnessgraph.store.case import Case

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("/neighbors")
def neighbors(
    entity_id: str = Query(..., description="Entity id to find neighbors of."),
    max_depth: int = Query(DEFAULT_NEIGHBORS_MAX_DEPTH, description="Maximum hops to traverse."),
    direction: GraphDirection = Query(GraphDirection.OUT, description="out | in | both."),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(
        graph_service.neighbors(
            case, entity_id, max_depth=max_depth, direction=direction, explain=True
        )
    )


@router.get("/path")
def path(
    source_entity_id: str = Query(..., description="Entity id to search from."),
    target_entity_id: str = Query(..., description="Entity id to search for."),
    max_depth: int = Query(DEFAULT_PATH_MAX_DEPTH, description="Maximum hops to search."),
    direction: GraphDirection = Query(GraphDirection.OUT, description="out | in | both."),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(
        graph_service.path(
            case,
            source_entity_id,
            target_entity_id,
            max_depth=max_depth,
            direction=direction,
            explain=True,
        )
    )


@router.get("/paths")
def paths(
    source_entity_id: str = Query(..., description="Entity id to search from."),
    target_entity_id: str = Query(..., description="Entity id to search for."),
    max_depth: int = Query(DEFAULT_PATH_MAX_DEPTH, description="Maximum hops to search."),
    direction: GraphDirection = Query(GraphDirection.OUT, description="out | in | both."),
    limit: int = Query(DEFAULT_PATHS_LIMIT, description="Maximum tied-shortest chains to return."),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(
        graph_service.paths(
            case,
            source_entity_id,
            target_entity_id,
            max_depth=max_depth,
            direction=direction,
            limit=limit,
            explain=True,
        )
    )


@router.get("/components")
def components(
    min_size: int = Query(1, description="Only show components with at least this many entities."),
    case: Case = Depends(get_case),
) -> Response:
    return json_response(graph_service.components(case, min_size=min_size, explain=True))
