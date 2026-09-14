"""Graph traversal service functions -- thin wrappers over ``correlate.graph``.

Every function here mirrors the corresponding ``cli.main.graph_*``
command's own case-opening/entity-existence/validation sequence exactly,
so the CLI and the API produce identical error distinctions
("no such entity" vs. an out-of-range parameter vs. success) for
identical input. No traversal, sorting, or explainability logic is
reimplemented here -- everything delegates to ``correlate.graph``.
"""

from __future__ import annotations

from witnessgraph.correlate.graph import (
    GraphDirection,
    all_shortest_paths_result_to_json,
    components_result_to_json,
    find_all_shortest_paths,
    find_components,
    find_neighbors,
    find_path,
    neighbors_result_to_json,
    path_result_to_json,
    validate_max_depth,
    validate_min_size,
    validate_paths_limit,
)
from witnessgraph.service.errors import EntityNotFoundError, ValidationError
from witnessgraph.store.case import Case


def _require_entity(case: Case, entity_id: str) -> None:
    if case.store.get_entity(entity_id) is None:
        raise EntityNotFoundError(entity_id)


def neighbors(
    case: Case,
    entity_id: str,
    *,
    max_depth: int,
    direction: GraphDirection,
    explain: bool,
) -> dict[str, object]:
    """Every entity reachable from ``entity_id`` within ``max_depth`` hops."""
    try:
        validate_max_depth(max_depth)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    _require_entity(case, entity_id)
    result = find_neighbors(case.store, entity_id, max_depth=max_depth, direction=direction)
    return neighbors_result_to_json(result, store=case.store if explain else None)


def path(
    case: Case,
    source_entity_id: str,
    target_entity_id: str,
    *,
    max_depth: int,
    direction: GraphDirection,
    explain: bool,
) -> dict[str, object]:
    """One deterministic, shortest relationship chain between two entities."""
    try:
        validate_max_depth(max_depth)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    _require_entity(case, source_entity_id)
    _require_entity(case, target_entity_id)
    result = find_path(
        case.store, source_entity_id, target_entity_id, max_depth=max_depth, direction=direction
    )
    return path_result_to_json(result, store=case.store if explain else None)


def paths(
    case: Case,
    source_entity_id: str,
    target_entity_id: str,
    *,
    max_depth: int,
    direction: GraphDirection,
    limit: int,
    explain: bool,
) -> dict[str, object]:
    """Every distinct chain tied for shortest between two entities, up to
    ``limit`` -- with evidence-independence analysis when ``explain`` is
    set (never turning a `null`/indeterminate verdict into `true`; see
    ``correlate.graph.PathsEvidenceOverlap``)."""
    try:
        validate_max_depth(max_depth)
        validate_paths_limit(limit)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    _require_entity(case, source_entity_id)
    _require_entity(case, target_entity_id)
    result = find_all_shortest_paths(
        case.store,
        source_entity_id,
        target_entity_id,
        max_depth=max_depth,
        direction=direction,
        limit=limit,
    )
    return all_shortest_paths_result_to_json(result, store=case.store if explain else None)


def components(case: Case, *, min_size: int, explain: bool) -> dict[str, object]:
    """Weakly-connected clusters of entities/relationships in ``case``."""
    try:
        validate_min_size(min_size)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    result = find_components(case.store, min_size=min_size)
    return components_result_to_json(result, store=case.store if explain else None)
