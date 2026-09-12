"""TrackedGapFinding: a persisted, stable identity for a GapFinding, with
an optional, explicitly analyst-attributed review annotation.

Structurally distinct from Hypothesis (DESIGN.md principle 3): a
TrackedGapFinding's analytical content (every field except
status/annotated_by/annotated_at/note) is a deterministic, mechanical
re-derivation from evidence -- never an analyst claim -- while its
annotation, when present, is Hypothesis-shaped (explicit attribution,
never silently authoritative). A ``status`` of ``reviewed`` means only
that an analyst examined this finding; it is never a claim that the
underlying finding was validated, or that the absent event should have
existed -- see ``correlate.gaps``'s module docstring for the epistemic
contract this must never violate.

v0.7 provides CURRENT-STATE tracking only. There is no history table:
``with_annotation()``/the store's ``annotate_tracked_finding`` permanently
replace the previous status/annotated_by/annotated_at/note with no record
of what it was before. If an audit trail of review history is ever
needed, that is a future, separately-justified design -- not something
v0.7 provides even partially.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, model_validator

from witnessgraph.core.ids import content_hash


class FindingStatus(str, Enum):
    OPEN = "open"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


def _validate_annotation(annotated_by: str | None, annotated_at: datetime | None) -> None:
    """Enforce the annotation-pairing/non-blank invariant.

    Shared by the model's own ``@model_validator`` (construction path) and
    ``with_annotation()`` (update path) -- the two are NOT the same code
    path in Pydantic v2: ``model_copy(update=...)`` deliberately does not
    re-run validators (this is documented Pydantic behavior, not a bug),
    so relying on the model validator alone would silently let
    ``with_annotation()`` produce an invalid object (e.g. a whitespace-only
    ``annotated_by``) that the constructor would have rejected. Calling
    this function explicitly from both places is what actually closes
    that gap -- found and fixed during adversarial implementation review.
    """
    has_by = annotated_by is not None
    has_at = annotated_at is not None
    if has_by != has_at:
        raise ValueError(
            "annotated_by and annotated_at must both be set or both be "
            "None -- a never-annotated finding has neither"
        )
    if has_by and not annotated_by.strip():  # type: ignore[union-attr]
        raise ValueError("annotated_by must not be blank when present")


class TrackedGapFinding(BaseModel):
    """A persisted, content-addressed anchor to one GapFinding, plus an
    optional analyst annotation.

    ``id`` is never randomly minted (contrast Hypothesis/Entity) -- it is
    :meth:`identity_hash` of the eight anchor fields below, exactly
    mirroring GapFinding's own fields. Two independently-run analyses
    that produce the "same" GapFinding always produce the same id here,
    by construction.

    A finding whose ``corroborating_time_assertion_ids`` changes (e.g.
    new evidence is ingested that adds a corroborating TimeAssertion
    inside an already-tracked gap window) receives a *different* id --
    this is intentional, not a defect: the corroborating assertions are
    the evidentiary basis for the finding's claim, not incidental
    metadata (see docs/phase5-v0.5-gap-analysis-design.md §18). The
    accepted trade-off is re-review churn: a finding that looks
    unchanged (same sources, same interval) can require fresh analyst
    review if its cited evidence set changes. This is deliberate and is
    not mitigated by this design.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str

    # -- Anchor: fixed for the life of this id (denormalized copy of the
    #    GapFinding's own fields, so a row is self-describing). NEVER
    #    accepted as a parameter to any update operation -- see
    #    with_annotation() below and Store.annotate_tracked_finding. --
    absent_source: str
    present_source: str
    absent_source_refinement: str | None
    present_source_refinement: str | None
    interval_start: datetime
    interval_end: datetime
    corroborating_time_assertion_ids: tuple[str, ...]
    bounding_absent_assertion_ids: tuple[str, str]

    # -- Analysis parameters in effect when this row was first created.
    #    Historical facts about the tracking event, never refreshed on
    #    re-discovery. refine_source_by_attribute is str | None, using
    #    None as the sole no-refinement sentinel -- no empty-string
    #    sentinel is used anywhere in this model. --
    min_gap_seconds: float
    min_corroborating_events: int
    refine_source_by_attribute: str | None

    # -- Mutable annotation. Absent (all None) until an analyst
    #    explicitly runs `findings ack`; `gaps --track` never populates
    #    these, and never invents an analyst identity to do so. --
    status: FindingStatus = FindingStatus.OPEN
    annotated_by: str | None = None
    annotated_at: datetime | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _annotation_is_paired(self) -> TrackedGapFinding:
        _validate_annotation(self.annotated_by, self.annotated_at)
        return self

    @staticmethod
    def identity_hash(
        *,
        absent_source: str,
        present_source: str,
        absent_source_refinement: str | None,
        present_source_refinement: str | None,
        interval_start: datetime,
        interval_end: datetime,
        corroborating_time_assertion_ids: tuple[str, ...],
        bounding_absent_assertion_ids: tuple[str, str],
    ) -> str:
        """The deterministic id a TrackedGapFinding anchoring this exact
        GapFinding content would have. Domain-separated from
        NormalizedEvent/TimeAssertion's identity_hash via the ``_type``
        tag, exactly mirroring their existing convention.

        Every GapFinding field participates -- there is no wall-clock
        field on GapFinding to exclude (unlike ``created_at`` on the
        other two types). Analysis parameters, timestamps, status,
        attribution, and note are deliberately excluded (see the class
        docstring and Store.create_tracked_finding).
        """
        return content_hash(
            {
                "_type": "GapFinding",
                "absent_source": absent_source,
                "present_source": present_source,
                "absent_source_refinement": absent_source_refinement,
                "present_source_refinement": present_source_refinement,
                "interval_start": interval_start,
                "interval_end": interval_end,
                "corroborating_time_assertion_ids": list(corroborating_time_assertion_ids),
                "bounding_absent_assertion_ids": list(bounding_absent_assertion_ids),
            }
        )

    def with_annotation(
        self,
        *,
        status: FindingStatus,
        annotated_by: str,
        annotated_at: datetime,
        note: str | None,
    ) -> TrackedGapFinding:
        """Return a new object with the same id and anchor; only
        status/annotated_by/annotated_at/note change. Every analytical
        field is copied from ``self`` unconditionally -- this method's
        ``update=`` mapping names exactly these four keys and no others,
        so there is no code path through which calling this can alter
        the anchor. There is no history: the previous annotation is
        permanently discarded by this call, not archived.

        Explicitly validates ``annotated_by``/``annotated_at`` before
        calling ``model_copy`` -- ``model_copy(update=...)`` does not
        re-run the model's own validators, so this call is what actually
        enforces the non-blank/paired invariant on this path (see
        ``_validate_annotation``); it must never be assumed to happen
        automatically.
        """
        _validate_annotation(annotated_by, annotated_at)
        return self.model_copy(
            update={
                "status": status,
                "annotated_by": annotated_by,
                "annotated_at": annotated_at,
                "note": note,
            }
        )
