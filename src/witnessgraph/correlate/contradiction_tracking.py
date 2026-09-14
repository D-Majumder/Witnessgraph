"""Caller-side orchestration that persists TimeContradiction results as
TrackedTimeContradiction rows (v0.8).

``detect_time_contradictions`` itself (``correlate.contradictions``)
remains fully pure and unpersisted -- this module only converts an
already-computed list of ``TimeContradiction`` into store writes. No new
detection logic is introduced here; ``subject_event_id`` and the two
assertion ids are always read directly from the ``TimeContradiction``
object, never independently supplied -- ``core/`` has no I/O and cannot
cross-check that a caller-supplied anchor actually matches some real
pair of assertions, so this orchestration is the one place that
guarantee is upheld.
"""

from __future__ import annotations

from dataclasses import dataclass

from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction
from witnessgraph.correlate.contradictions import TimeContradiction
from witnessgraph.store.base import Store


def contradiction_identity(contradiction: TimeContradiction) -> str:
    """The TrackedTimeContradiction id ``contradiction`` would have."""
    return TrackedTimeContradiction.identity_hash(
        subject_event_id=contradiction.subject_event_id,
        assertion_ids=(contradiction.assertion_a.id, contradiction.assertion_b.id),
    )


@dataclass(frozen=True)
class ContradictionTrackingOutcome:
    contradiction: TrackedTimeContradiction
    newly_created: bool


def track_contradictions(
    store: Store, contradictions: list[TimeContradiction]
) -> tuple[ContradictionTrackingOutcome, ...]:
    """Persist every contradiction in ``contradictions`` as a
    ``TrackedTimeContradiction``.

    Insert-if-absent per contradiction (``Store.create_tracked_contradiction``):
    a contradiction already tracked from a prior run is returned
    unchanged, with its existing annotation untouched --
    ``ContradictionTrackingOutcome.newly_created`` is ``False`` in that
    case, distinguishing "already tracked" from "created by this call"
    without relying on annotation state (an already-tracked-but-never-
    annotated contradiction must not be misreported as newly created).
    Every newly created row starts ``status=OPEN`` with no annotation --
    no analyst identity is invented or required here.

    Callers are responsible for wrapping this call in
    ``case.transaction()`` so that a failure partway through rolls back
    every insert made by this call, and for running the full, read-only
    ``detect_time_contradictions()`` call that produced ``contradictions``
    *before* opening that transaction.
    """
    outcomes: list[ContradictionTrackingOutcome] = []
    for contradiction in contradictions:
        id_ = contradiction_identity(contradiction)
        pre_existing = store.get_tracked_contradiction(id_) is not None
        first, second = sorted((contradiction.assertion_a.id, contradiction.assertion_b.id))
        candidate = TrackedTimeContradiction(
            id=id_,
            subject_event_id=contradiction.subject_event_id,
            assertion_ids=(first, second),
        )
        stored = store.create_tracked_contradiction(candidate)
        outcomes.append(
            ContradictionTrackingOutcome(contradiction=stored, newly_created=not pre_existing)
        )
    return tuple(outcomes)


def tracked_contradiction_to_json(contradiction: TrackedTimeContradiction) -> dict[str, object]:
    """A plain dict tree for one ``TrackedTimeContradiction`` -- pass to
    ``core.ids.canonical_json_bytes`` for encoding, exactly like
    ``correlate.graph``'s own ``*_to_json`` builders.

    Deliberately no ``still_reproduced`` field -- see this class's own
    module docstring and ``correlate.tracking.tracked_finding_to_json``'s
    docstring for the parallel case that DOES have one: a genuinely
    detected contradiction is reproducible with certainty by every
    future run, so such a field would always read ``true`` and convey no
    information.
    """
    return {
        "id": contradiction.id,
        "subject_event_id": contradiction.subject_event_id,
        "assertion_ids": list(contradiction.assertion_ids),
        "status": contradiction.status.value,
        "annotated_by": contradiction.annotated_by,
        "annotated_at": contradiction.annotated_at,
        "note": contradiction.note,
    }
