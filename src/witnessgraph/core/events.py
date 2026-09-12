"""NormalizedEvent: a structured interpretation of one or more EvidenceItems.

See DESIGN.md principles 1 and 2: immutable once created, and carries
explicit, validated lineage back to the raw evidence it came from.

See docs/phase3-v0.3-design.md §7 for the v0.3 content-addressing
design: construct via :meth:`create`, not the bare constructor, so that
``id`` is a deterministic function of the event's identity fields
(``event_type``, ``attributes``, ``derived_from``) rather than a random
UUID. This makes re-deriving the *same* logical event from the *same*
evidence -- e.g. re-running ``witnessgraph ingest`` after an
interruption -- converge to the same id instead of creating a
duplicate. The bare constructor (random id via ``new_object_id``)
remains available for direct/test use and for reading v0.1/v0.2-era
objects, exactly as for ``EvidenceItem``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from witnessgraph.core.ids import content_hash, new_object_id


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

    @staticmethod
    def identity_hash(
        *,
        event_type: str,
        attributes: dict[str, str],
        derived_from: tuple[str, ...],
    ) -> str:
        """The deterministic id a NormalizedEvent with these identity fields would have.

        Identity fields per docs/phase3-v0.3-design.md §7: ``event_type``,
        ``attributes``, and ``derived_from`` (order preserved, not
        sorted -- see the design doc's open question §18.1). Excluded:
        ``created_at`` (ingest-time wall clock, not observational
        content) and ``entity_ids`` (never populated by any current
        adapter). A ``_type`` tag domain-separates this from
        ``TimeAssertion``'s identity hash so the two can never collide.
        """
        return content_hash(
            {
                "_type": "NormalizedEvent",
                "event_type": event_type,
                "attributes": attributes,
                "derived_from": list(derived_from),
            }
        )

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        derived_from: tuple[str, ...],
        created_at: datetime,
        attributes: dict[str, str] | None = None,
        entity_ids: tuple[str, ...] = (),
    ) -> NormalizedEvent:
        """Build a NormalizedEvent with a deterministic, content-derived id.

        Two calls with identical ``event_type``/``attributes``/
        ``derived_from`` always produce the same id, regardless of
        ``created_at`` -- see :meth:`identity_hash`.
        """
        attrs = attributes or {}
        return cls(
            id=cls.identity_hash(
                event_type=event_type, attributes=attrs, derived_from=derived_from
            ),
            event_type=event_type,
            entity_ids=entity_ids,
            attributes=attrs,
            derived_from=derived_from,
            created_at=created_at,
        )
