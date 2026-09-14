"""Entity: a real-world thing (host, user, ip, hash, domain, process, ...) referenced by evidence.

See DESIGN.md principles 1 and 2. Witnessgraph v0.1 does not attempt
automatic entity resolution/merging (explicitly out of scope, see
DESIGN.md and the project README) -- callers are responsible for reusing
an existing Entity id when they know two observations refer to the same
real-world entity.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from witnessgraph.core.ids import new_object_id


class Entity(BaseModel):
    """A real-world thing referenced by evidence. Immutable once created.

    ``derived_from`` must be non-empty -- an Entity that isn't traceable
    to at least one EvidenceItem/NormalizedEvent cannot be constructed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=new_object_id)
    entity_type: str
    identifiers: dict[str, str] = Field(default_factory=dict)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    derived_from: tuple[str, ...]

    @field_validator("derived_from")
    @classmethod
    def _must_have_lineage(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) == 0:
            raise ValueError(
                "Entity.derived_from must reference at least one EvidenceItem/NormalizedEvent id"
            )
        return v

    @field_validator("entity_type")
    @classmethod
    def _entity_type_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Entity.entity_type must not be blank")
        return v


def entity_to_json(entity: Entity) -> dict[str, object]:
    """A plain dict/list tree for ``entity`` -- the same field shape
    ``report.render_json._build_entities`` already produces per entity,
    exposed publicly so callers other than the whole-case report (the
    service layer, in particular) can serialize a single ``Entity``
    without going through Pydantic's own (non-canonical) JSON encoding.
    """
    return {
        "id": entity.id,
        "entity_type": entity.entity_type,
        "identifiers": dict(entity.identifiers),
        "first_seen": entity.first_seen,
        "last_seen": entity.last_seen,
        "derived_from": list(entity.derived_from),
    }
