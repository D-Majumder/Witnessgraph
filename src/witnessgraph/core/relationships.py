"""Relationship: an explicit, evidence-backed edge between two Entities.

See DESIGN.md principles 1-3: immutable once created, carries explicit
validated lineage back to the evidence it was derived from, and -- like
every other derived object in this codebase -- is an observed claim, not
an inference Witnessgraph invented. A Relationship is Witnessgraph's
graph *edge*; ``Entity`` is its node. Every version through v1.0 had
entities only as isolated nodes, each linked back to its own evidence,
with no way to represent that two entities were observed to be
connected. This (v1.1) is the first version that closes that gap.

Constructed via :meth:`create`, mirroring ``NormalizedEvent``/
``TimeAssertion``: ``id`` is a deterministic function of the
relationship's identity fields, so re-deriving the same claim from the
same evidence converges to the same id instead of duplicating (unlike
``Entity``, whose v1.0 identity is a random id -- see
``core.entities``'s module docstring for why that is a deliberate,
separate, deferred decision, not something this module casually departs
from for its own type).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from witnessgraph.core.ids import content_hash, new_object_id


class Relationship(BaseModel):
    """A claim, grounded in evidence, that two Entities are connected.

    Directed: ``source_entity_id`` -> ``target_entity_id``. Witnessgraph
    does not infer a reverse relationship or any notion of symmetry --
    an analyst who means "connected both ways" creates two Relationships.
    ``relationship_type`` is a free-form, analyst-declared label (e.g.
    ``"connected_to"``, ``"authenticated_as"``, ``"communicated_with"`");
    Witnessgraph does not constrain or interpret its vocabulary, exactly
    as ``Entity.entity_type`` is not constrained.

    ``derived_from`` must be non-empty -- a Relationship that isn't
    traceable to at least one EvidenceItem/NormalizedEvent cannot be
    constructed (DESIGN.md principle 2). ``source_entity_id`` and
    ``target_entity_id`` are validated only for shape (non-blank, not
    equal to each other) here; ``core/`` has no I/O (principle 6), so
    confirming both ids actually name existing Entities happens one
    layer up, at the CLI, exactly like ``Hypothesis``'s ``EvidenceRef``
    existence check.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=new_object_id)
    relationship_type: str
    source_entity_id: str
    target_entity_id: str
    attributes: dict[str, str] = Field(default_factory=dict)
    derived_from: tuple[str, ...]
    created_at: datetime

    @model_validator(mode="after")
    def _validate(self) -> Relationship:
        if not self.relationship_type.strip():
            raise ValueError("Relationship.relationship_type must not be blank")
        if not self.source_entity_id.strip() or not self.target_entity_id.strip():
            raise ValueError("Relationship.source_entity_id/target_entity_id must not be blank")
        if self.source_entity_id == self.target_entity_id:
            raise ValueError(
                "Relationship.source_entity_id and target_entity_id must differ -- "
                "an entity is not considered related to itself"
            )
        if len(self.derived_from) == 0:
            raise ValueError(
                "Relationship.derived_from must reference at least one "
                "EvidenceItem/NormalizedEvent id"
            )
        return self

    @staticmethod
    def identity_hash(
        *,
        relationship_type: str,
        source_entity_id: str,
        target_entity_id: str,
        attributes: dict[str, str],
        derived_from: tuple[str, ...],
    ) -> str:
        """The deterministic id a Relationship with these identity fields would have.

        Identity fields: ``relationship_type``, ``source_entity_id``,
        ``target_entity_id``, ``attributes``, and ``derived_from`` (order
        preserved, not sorted -- mirrors ``NormalizedEvent.identity_hash``).
        Excluded: ``created_at`` (ingest-time wall clock, not
        observational content). A ``_type`` tag domain-separates this
        from every other content-hashed type's identity hash.
        """
        return content_hash(
            {
                "_type": "Relationship",
                "relationship_type": relationship_type,
                "source_entity_id": source_entity_id,
                "target_entity_id": target_entity_id,
                "attributes": attributes,
                "derived_from": list(derived_from),
            }
        )

    @classmethod
    def create(
        cls,
        *,
        relationship_type: str,
        source_entity_id: str,
        target_entity_id: str,
        derived_from: tuple[str, ...],
        created_at: datetime,
        attributes: dict[str, str] | None = None,
    ) -> Relationship:
        """Build a Relationship with a deterministic, content-derived id.

        Two calls with identical ``relationship_type``/``source_entity_id``/
        ``target_entity_id``/``attributes``/``derived_from`` always produce
        the same id, regardless of ``created_at`` -- so re-running
        ``witnessgraph relationships create`` with the same arguments is a
        safe, idempotent no-op rather than a duplicate.
        """
        attrs = attributes or {}
        return cls(
            id=cls.identity_hash(
                relationship_type=relationship_type,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                attributes=attrs,
                derived_from=derived_from,
            ),
            relationship_type=relationship_type,
            source_entity_id=source_entity_id,
            target_entity_id=target_entity_id,
            attributes=attrs,
            derived_from=derived_from,
            created_at=created_at,
        )
