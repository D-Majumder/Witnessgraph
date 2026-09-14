"""List/get entities -- a thin wrapper over ``Store.list_entities``/``get_entity``.

Mirrors ``cli.main.entities_list``/``entities_show`` exactly, returning
``core.entities.entity_to_json``'s dict shape instead of a text line or
``model_dump_json()`` -- see
``docs/phase-ui-v1-architecture-design.md`` §5 gap #2.
"""

from __future__ import annotations

from witnessgraph.core.entities import entity_to_json
from witnessgraph.service.errors import EntityNotFoundError
from witnessgraph.store.case import Case


def list_entities(case: Case, *, entity_type: str | None = None) -> list[dict[str, object]]:
    """Every entity in ``case``, sorted by id, optionally filtered to one
    ``entity_type``."""
    entities = sorted(case.store.list_entities(), key=lambda e: e.id)
    if entity_type is not None:
        entities = [e for e in entities if e.entity_type == entity_type]
    return [entity_to_json(e) for e in entities]


def get_entity(case: Case, entity_id: str) -> dict[str, object]:
    """One entity by id, or raise :class:`EntityNotFoundError`."""
    entity = case.store.get_entity(entity_id)
    if entity is None:
        raise EntityNotFoundError(entity_id)
    return entity_to_json(entity)
