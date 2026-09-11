"""Hypothesis: an explicit, evidence-backed claim about the evidence.

See DESIGN.md principles 3 and 7. This module is the structural
enforcement point for "evidence and inference are different types, and
inference can never become authoritative": a Hypothesis cannot be
constructed without referencing at least one piece of evidence, and it
always records who or what proposed it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from witnessgraph.core.ids import new_object_id


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    WITHDRAWN = "withdrawn"


_VALID_REF_KINDS = ("evidence_item", "normalized_event")


class EvidenceRef(BaseModel):
    """A reference to a piece of evidence or a normalized event -- never a bare claim.

    Intentional boundary: this model validates its own *shape* (``kind``
    is one of the known kinds, ``id`` is present) but does not, and
    cannot, verify that ``id`` actually exists in some case's store.
    ``core/`` is pure and has no I/O (DESIGN.md principle 6), so
    referential-existence checking necessarily lives one layer up, at the
    point where a store is actually available -- see
    ``witnessgraph.cli.main._resolve_evidence_ref``, which is where every
    CLI-driven ``Hypothesis`` construction is required to go through this
    check today. A hand-written script calling this constructor directly
    can still build an ``EvidenceRef``/``Hypothesis`` pointing at a
    nonexistent id; that is a deliberate, documented tradeoff (keeping
    core models storage-independent), not an oversight.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str
    id: str

    @model_validator(mode="after")
    def _kind_is_known(self) -> EvidenceRef:
        if self.kind not in _VALID_REF_KINDS:
            raise ValueError(f"EvidenceRef.kind must be one of {_VALID_REF_KINDS}")
        return self


class Hypothesis(BaseModel):
    """An analyst's (or, in a future version, an assistant's) claim about the evidence.

    Cannot be constructed without at least one EvidenceRef (supporting or
    contradicting) -- see the class-level validator below. ``inferred_by``
    must always be non-blank, so there is no code path that lets a
    Hypothesis exist without explicit attribution. Witnessgraph v0.1 has
    no AI assistant, so in practice ``inferred_by`` is always an analyst
    identity; the field is designed now so a future assistant integration
    has no way to bypass attribution or become authoritative (principle 7).

    Status changes never mutate an existing Hypothesis; use
    :meth:`with_status` to obtain a new one with the same id.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=new_object_id)
    statement: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    supporting_evidence: tuple[EvidenceRef, ...] = Field(default_factory=tuple)
    contradicting_evidence: tuple[EvidenceRef, ...] = Field(default_factory=tuple)
    inferred_by: str
    created_at: datetime

    @model_validator(mode="after")
    def _must_be_evidence_backed(self) -> Hypothesis:
        if not self.statement.strip():
            raise ValueError("Hypothesis.statement must not be empty")
        if not self.inferred_by.strip():
            raise ValueError("Hypothesis.inferred_by must not be empty")
        if len(self.supporting_evidence) + len(self.contradicting_evidence) == 0:
            raise ValueError(
                "Hypothesis must reference at least one EvidenceRef (supporting or "
                "contradicting) -- a hypothesis cannot exist disconnected from evidence"
            )
        return self

    def with_status(
        self,
        status: HypothesisStatus,
        *,
        add_supporting: tuple[EvidenceRef, ...] = (),
        add_contradicting: tuple[EvidenceRef, ...] = (),
    ) -> Hypothesis:
        """Return a *new* Hypothesis reflecting a status change; never mutates self."""
        return self.model_copy(
            update={
                "status": status,
                "supporting_evidence": (*self.supporting_evidence, *add_supporting),
                "contradicting_evidence": (*self.contradicting_evidence, *add_contradicting),
            }
        )
