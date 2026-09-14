"""List/get relationships -- a thin wrapper over ``Store.list_relationships``/``get_relationship``.

Mirrors ``cli.main.relationships_list``/``relationships_show``, with one
deliberate API-specific difference documented in
``docs/phase-ui-v1-architecture-design.md`` §14: a single relationship
fetched by id always has its ``evidence_lineage`` resolved (there is no
CLI-style ``--explain`` opt-in for a single JSON object returned to a
machine caller -- the CLI's opt-in exists only to keep a human-scale text
listing short).
"""

from __future__ import annotations

from witnessgraph.correlate.graph import relationship_to_json
from witnessgraph.service.errors import RelationshipNotFoundError
from witnessgraph.store.case import Case


def list_relationships(
    case: Case,
    *,
    entity_id: str | None = None,
    relationship_type: str | None = None,
) -> list[dict[str, object]]:
    """Every relationship in ``case``, sorted by id, optionally filtered
    to one participating ``entity_id`` and/or ``relationship_type``."""
    relationships = sorted(case.store.list_relationships(), key=lambda r: r.id)
    if entity_id is not None:
        relationships = [
            r for r in relationships if entity_id in (r.source_entity_id, r.target_entity_id)
        ]
    if relationship_type is not None:
        relationships = [r for r in relationships if r.relationship_type == relationship_type]
    return [relationship_to_json(r) for r in relationships]


def get_relationship(case: Case, relationship_id: str) -> dict[str, object]:
    """One relationship by id, with its evidence lineage always resolved,
    or raise :class:`RelationshipNotFoundError`."""
    relationship = case.store.get_relationship(relationship_id)
    if relationship is None:
        raise RelationshipNotFoundError(relationship_id)
    return relationship_to_json(relationship, store=case.store)
