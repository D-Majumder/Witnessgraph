"""Caller-side orchestration that persists GapFinding results as
TrackedGapFinding rows (v0.7).

``find_gaps`` itself (``correlate.gaps``) remains fully pure and
unpersisted -- this module only converts an already-computed
``GapAnalysisResult`` into store writes. No new analytical or grouping
logic is introduced here; every anchor field is copied verbatim from the
``GapFinding`` it anchors.
"""

from __future__ import annotations

from dataclasses import dataclass

from witnessgraph.core.tracked_finding import TrackedGapFinding
from witnessgraph.correlate.gaps import GapAnalysisResult, GapFinding, find_gaps
from witnessgraph.store.base import Store


def finding_identity(finding: GapFinding) -> str:
    """The TrackedGapFinding id ``finding`` would have, per its anchor fields."""
    return TrackedGapFinding.identity_hash(
        absent_source=finding.absent_source,
        present_source=finding.present_source,
        absent_source_refinement=finding.absent_source_refinement,
        present_source_refinement=finding.present_source_refinement,
        interval_start=finding.interval_start,
        interval_end=finding.interval_end,
        corroborating_time_assertion_ids=finding.corroborating_time_assertion_ids,
        bounding_absent_assertion_ids=finding.bounding_absent_assertion_ids,
    )


@dataclass(frozen=True)
class TrackingOutcome:
    finding: TrackedGapFinding
    newly_created: bool


def track_findings(
    store: Store,
    result: GapAnalysisResult,
    *,
    min_gap_seconds: float,
    min_corroborating_events: int,
) -> tuple[TrackingOutcome, ...]:
    """Persist every finding in ``result`` as a ``TrackedGapFinding``.

    Insert-if-absent per finding (``Store.create_tracked_finding``): a
    finding already tracked from a prior run is returned unchanged, with
    its existing annotation untouched -- ``TrackingOutcome.newly_created``
    is ``False`` in that case, distinguishing "already tracked before this
    call" from "created by this call" without relying on annotation state
    (an already-tracked-but-never-annotated finding must not be
    misreported as newly created). Every newly created row starts
    ``status=OPEN`` with no annotation -- no analyst identity is invented
    or required here. ``min_gap_seconds``/``min_corroborating_events``
    are the analysis parameters that produced ``result`` and are recorded
    on newly created rows only; ``result.refine_source_by_attribute`` is
    read directly from ``result``.

    Callers are responsible for wrapping this call in ``case.transaction()``
    so that a failure partway through rolls back every insert made by
    this call, and for running the full, read-only ``find_gaps()`` call
    that produced ``result`` *before* opening that transaction.
    """
    outcomes: list[TrackingOutcome] = []
    for finding in result.findings:
        id_ = finding_identity(finding)
        pre_existing = store.get_tracked_finding(id_) is not None
        candidate = TrackedGapFinding(
            id=id_,
            absent_source=finding.absent_source,
            present_source=finding.present_source,
            absent_source_refinement=finding.absent_source_refinement,
            present_source_refinement=finding.present_source_refinement,
            interval_start=finding.interval_start,
            interval_end=finding.interval_end,
            corroborating_time_assertion_ids=finding.corroborating_time_assertion_ids,
            bounding_absent_assertion_ids=finding.bounding_absent_assertion_ids,
            min_gap_seconds=min_gap_seconds,
            min_corroborating_events=min_corroborating_events,
            refine_source_by_attribute=result.refine_source_by_attribute,
        )
        stored = store.create_tracked_finding(candidate)
        outcomes.append(TrackingOutcome(finding=stored, newly_created=not pre_existing))
    return tuple(outcomes)


def is_still_reproduced(store: Store, tracked: TrackedGapFinding) -> bool:
    """Whether ``tracked``'s id still appears in a fresh analysis run
    using its own originally recorded parameters.

    Purely derived, never persisted (v0.7 scope §7): this must never be
    written back to the store, and a ``False`` result must never be
    interpreted as, or automatically converted into, a status change --
    the tool has no basis to say *why* a finding stopped reproducing
    (evidence changed, the gap genuinely closed, or a corroborating set
    changed -- see TrackedGapFinding's docstring on intentional identity
    churn), so it asserts nothing beyond the bare fact.
    """
    fresh = find_gaps(
        store,
        min_gap_seconds=tracked.min_gap_seconds,
        min_corroborating_events=tracked.min_corroborating_events,
        refine_source_by_attribute=tracked.refine_source_by_attribute,
    )
    current_ids = {finding_identity(f) for f in fresh.findings}
    return tracked.id in current_ids
