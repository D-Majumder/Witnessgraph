"""NormalizedEvent: a structured interpretation of one or more EvidenceItems.

See DESIGN.md principles 1 and 2: immutable once created, and carries
explicit, validated lineage back to the raw evidence it came from.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from witnessgraph.core.ids import new_object_id


class NormalizedEvent(BaseModel):
    """A structured interpretation of one or more EvidenceItems.

    ``derived_from`` must be non-empty -- a NormalizedEvent that isn't
    traceable to at least one EvidenceItem cannot be constructed.
    Re-normalizing evidence produces a *new* NormalizedEvent; existing
    ones are never edited in place.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=new_object_id)
    event_type: str
    entity_ids: tuple[str, ...] = Field(default_factory=tuple)
    attributes: dict[str, str] = Field(default_factory=dict)
    derived_from: tuple[str, ...]
    created_at: datetime

    @field_validator("derived_from")
    @classmethod
    def _must_have_lineage(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) == 0:
            raise ValueError(
                "NormalizedEvent.derived_from must reference at least one EvidenceItem id"
            )
        return v

    @field_validator("event_type")
    @classmethod
    def _event_type_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("NormalizedEvent.event_type must not be blank")
        return v
