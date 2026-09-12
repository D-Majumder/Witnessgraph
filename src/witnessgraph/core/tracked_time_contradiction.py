"""TrackedTimeContradiction: a persisted, stable identity for a
TimeContradiction, with an optional, explicitly analyst-attributed review
annotation (v0.8).

Structurally disjoint from TrackedGapFinding by design -- see
docs/phase4-v0.4-gap-analysis-design.md §9: "TimeContradiction and
GapFinding are structurally disjoint and never merged into one type or
one collection." This module introduces a separate model, a separate
SQLite table, a separate Store API family, and a separate CLI namespace
(``contradiction-findings``, distinct from ``findings``). The only
intentional coupling with ``core.tracked_finding`` is importing the
``FindingStatus`` enum and ``core.annotation.validate_annotation_pairing``
verbatim -- both are narrow, stable, contradiction-agnostic/gap-agnostic
primitives, not a shared model/table/base class.

A ``status`` of ``reviewed``/``dismissed`` is workflow metadata only: it
never means the contradiction is resolved, adjudicated, or that either
assertion is more correct. Witnessgraph never determines which of two
disagreeing assertions is true (DESIGN.md principle 3) -- see
``correlate.contradictions``'s module docstring for the epistemic
contract this must never violate. No "resolved" status exists.

There is no history table: ``with_annotation()``/the store's
``annotate_tracked_contradiction`` permanently replace the previous
status/annotated_by/annotated_at/note with no record of what it was
before -- exactly the v0.7 posture, not something this milestone
provides even partially.

Unlike ``TrackedGapFinding``, this model has no analysis-parameter
fields at all: ``detect_time_contradictions(store)`` takes no
thresholds, so there is nothing to record beyond the anchor and the
annotation. There is also no "still reproduced" indicator: TimeAssertion
is frozen, content-addressed, and append-only (no code path in this
codebase deletes or mutates one once stored), so a genuinely detected
contradiction is reproducible by every future analysis run with
certainty -- a live "still reproduced" check would either always read
"yes" (conveying no information) or risk being misread as some kind of
live re-validation signal. Exposing it would be dishonest by omission
of that certainty, so it is deliberately not implemented.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from witnessgraph.core.annotation import validate_annotation_pairing
from witnessgraph.core.ids import content_hash
from witnessgraph.core.tracked_finding import FindingStatus


class TrackedTimeContradiction(BaseModel):
    """A persisted, content-addressed anchor to one TimeContradiction,
    plus an optional analyst annotation.

    ``id`` is never randomly minted -- it is :meth:`identity_hash` of
    ``subject_event_id`` and the two assertion ids, mirroring
    ``TrackedGapFinding``'s content-derived-identity convention.

    ``assertion_ids`` is always exactly two DISTINCT ids in canonical
    sorted order (``assertion_ids[0] < assertion_ids[1]``) -- unlike
    GapFinding's ``absent_source``/``present_source`` (semantically
    asymmetric roles that must never be reordered), the two assertions
    in a contradiction are symmetric peers (``TimeAssertion.disagrees_with``
    is commutative), so canonical sorting is required here to make
    identity independent of which assertion a caller happened to label
    first -- a distinction v0.7's GapFinding never needed to make.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str

    # -- Anchor: fixed for the life of this id. NEVER accepted as a
    #    parameter to any update operation -- see with_annotation()
    #    below and Store.annotate_tracked_contradiction. --
    subject_event_id: str
    assertion_ids: tuple[str, str]

    # -- Mutable annotation. Absent (all None) until an analyst
    #    explicitly runs `contradiction-findings ack`;
    #    `contradictions --track` never populates these, and never
    #    invents an analyst identity to do so. --
    status: FindingStatus = FindingStatus.OPEN
    annotated_by: str | None = None
    annotated_at: datetime | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _anchor_and_annotation_are_valid(self) -> TrackedTimeContradiction:
        first, second = self.assertion_ids
        if first == second:
            raise ValueError(
                "assertion_ids must be two DISTINCT ids -- a contradiction "
                "requires two different assertions"
            )
        if first > second:
            raise ValueError(
                "assertion_ids must be stored in canonical sorted order "
                "(assertion_ids[0] < assertion_ids[1])"
            )
        validate_annotation_pairing(self.annotated_by, self.annotated_at)
        return self

    @staticmethod
    def identity_hash(*, subject_event_id: str, assertion_ids: tuple[str, str]) -> str:
        """The deterministic id a TrackedTimeContradiction anchoring this
        exact TimeContradiction content would have. Domain-separated via
        the ``_type`` tag, exactly mirroring the existing convention.

        The EXACT, normative, complete hash payload:
            {"_type": "TimeContradiction",
             "subject_event_id": subject_event_id,
             "assertion_ids": [min(a, b), max(a, b)]}
        Nothing else participates -- no annotation field, no timestamp,
        no analysis parameter (there are none for contradictions; see
        the module docstring).

        Sorts its own input, so a caller may pass the pair in either
        order and always receive the same id (required: the two
        assertions are symmetric peers, unlike GapFinding's asymmetric
        source roles). Raises ``ValueError`` if the two ids are equal --
        a degenerate, impossible "self-contradiction" must never be
        silently assigned an id, whether that identity is requested via
        this staticmethod directly or via the model's own constructor.
        """
        first, second = sorted(assertion_ids)
        if first == second:
            raise ValueError(
                "assertion_ids must be two DISTINCT ids -- identity_hash "
                "refuses to mint an id for a degenerate (self-)contradiction"
            )
        return content_hash(
            {
                "_type": "TimeContradiction",
                "subject_event_id": subject_event_id,
                "assertion_ids": [first, second],
            }
        )

    def with_annotation(
        self,
        *,
        status: FindingStatus,
        annotated_by: str,
        annotated_at: datetime,
        note: str | None,
    ) -> TrackedTimeContradiction:
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
        ``validate_annotation_pairing``); it must never be assumed to
        happen automatically.
        """
        validate_annotation_pairing(annotated_by, annotated_at)
        return self.model_copy(
            update={
                "status": status,
                "annotated_by": annotated_by,
                "annotated_at": annotated_at,
                "note": note,
            }
        )
