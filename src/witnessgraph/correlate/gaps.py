"""Deterministic detection of cross-source evidence coverage gaps.

See docs/phase5-v0.5-gap-analysis-design.md. Pure and deterministic --
no ML/statistical heuristics, no assumption about what a source
"should" contain (DESIGN.md principle 7 and this design's core
requirement: "no observed evidence" is never treated as proof "nothing
happened").

A ``GapFinding`` is a *relative*, evidence-grounded inference -- never
persisted, never part of the provenance manifest, structurally distinct
from observed evidence exactly as ``TimeContradiction`` already is (see
``witnessgraph.correlate.contradictions``). Source identity is resolved
exclusively via ``EvidenceItem.declared_source_ids()`` (v0.4, explicit
analyst-declared identity) -- never inferred from ``source_locator``,
``source_adapter``, ``adapter_version``, or ``collected_at``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.store.base import Store

#: Deliberately conservative floor: a single corroborating event is too
#: weak a basis to call anything a "gap" against it. A policy choice, not
#: derived from any data -- see docs/phase5-v0.5-gap-analysis-design.md §7/§23.
DEFAULT_MIN_CORROBORATING_EVENTS = 2


@dataclass(frozen=True)
class GapFinding:
    """One structural finding: ``absent_source`` has no observed evidence
    in ``[interval_start, interval_end)`` while ``present_source`` does.

    Never a claim that an event *should* have existed -- see the module
    docstring. Every field is independently re-verifiable against the
    store: ``bounding_absent_assertion_ids`` are the two TimeAssertions
    of ``absent_source`` that bracket the gap;
    ``corroborating_time_assertion_ids`` are ``present_source``'s
    TimeAssertions whose widened interval overlaps the gap window.
    """

    absent_source: str
    present_source: str
    interval_start: datetime
    interval_end: datetime
    corroborating_time_assertion_ids: tuple[str, ...]
    bounding_absent_assertion_ids: tuple[str, str]


@dataclass(frozen=True)
class GapAnalysisResult:
    """The full result of one ``find_gaps`` call.

    The three ``excluded_*`` counts exist so that evidence silently
    excluded from analysis (never grouped by guesswork, per
    docs/phase4-v0.4-gap-analysis-design.md's rejected fallbacks) is
    still visibly accounted for, not silently dropped without a trace.
    ``excluded_no_time_assertion`` counts ``NormalizedEvent``s that have
    no ``TimeAssertion`` at all (there is nothing to count *as* an
    assertion in that case); ``excluded_no_declared_source`` and
    ``excluded_ambiguous_source`` count ``TimeAssertion``s whose
    underlying evidence's source identity could not be resolved.
    """

    findings: tuple[GapFinding, ...]
    excluded_no_time_assertion: int
    excluded_no_declared_source: int
    excluded_ambiguous_source: int


def _resolve_source(evidence: EvidenceItem) -> str | None:
    """Resolve ``evidence``'s source identity, or ``None`` if unresolved.

    ``None`` covers both "no source_id was ever declared for this
    evidence" and "declared under two different source_ids" (an
    ambiguous, byte-identical-content case) -- callers must not guess
    between them. Never falls back to source_adapter/source_locator/
    collected_at -- see docs/phase5-v0.5-gap-analysis-design.md §5.
    """
    declared = evidence.declared_source_ids()
    if len(declared) == 1:
        return next(iter(declared))
    return None


def find_gaps(
    store: Store,
    *,
    min_gap_seconds: float,
    min_corroborating_events: int = DEFAULT_MIN_CORROBORATING_EVENTS,
) -> GapAnalysisResult:
    """Find cross-source coverage gaps across every pair of resolved sources.

    ``min_gap_seconds`` has no default claimed as objectively correct
    (docs/phase5-v0.5-gap-analysis-design.md §7/§23) and must be
    explicitly chosen by the caller. Deterministic and order-independent:
    every collection is sorted by content, never relied upon for
    insertion order (mirrors ``compute_manifest``/
    ``detect_time_contradictions``'s existing pattern).
    """
    events_by_id = {e.id: e for e in store.list_normalized_events()}
    evidence_by_id = {e.id: e for e in store.list_evidence()}
    all_assertions = store.list_time_assertions()

    events_with_assertion = {a.subject_event_id for a in all_assertions}
    excluded_no_time_assertion = sum(
        1 for event_id in events_by_id if event_id not in events_with_assertion
    )

    intervals: dict[str, list[tuple[datetime, datetime, str]]] = {}
    excluded_no_declared_source = 0
    excluded_ambiguous_source = 0

    for assertion in all_assertions:
        event = events_by_id.get(assertion.subject_event_id)
        if event is None:
            continue  # dangling reference; not this detector's concern
        source_evidence = evidence_by_id.get(assertion.source_evidence_id)
        if source_evidence is None:
            continue

        declared = source_evidence.declared_source_ids()
        if len(declared) == 0:
            excluded_no_declared_source += 1
            continue
        if len(declared) > 1:
            excluded_ambiguous_source += 1
            continue
        source = _resolve_source(source_evidence)
        assert source is not None  # guaranteed by the len(declared) == 1 branch above

        tolerance = timedelta(seconds=assertion.tolerance_seconds())
        widened = (assertion.value - tolerance, assertion.value + tolerance, assertion.id)
        intervals.setdefault(source, []).append(widened)

    for widened_list in intervals.values():
        widened_list.sort(key=lambda w: (w[0], w[2]))

    sources = sorted(intervals.keys())
    findings: list[GapFinding] = []

    for absent_source in sources:
        absent_events = intervals[absent_source]
        if len(absent_events) < 2:
            continue  # nothing to bracket a gap between -- see §10
        absent_span_start = min(w[0] for w in absent_events)
        absent_span_end = max(w[1] for w in absent_events)

        for present_source in sources:
            if present_source == absent_source:
                continue
            present_events = intervals[present_source]
            present_span_start = min(w[0] for w in present_events)
            present_span_end = max(w[1] for w in present_events)

            # Pair-level early exit only -- these two sources' overall
            # observed spans don't overlap at all, so no candidate window
            # from absent_source could ever be corroborated by
            # present_source. This does NOT clip individual gap windows
            # below (see the note on that below) -- it is purely "is it
            # even possible for this pair to produce a finding."
            if present_span_start >= absent_span_end or absent_span_start >= present_span_end:
                continue  # no overlap at all -- correctly silent, see §7/§24

            # Track the furthest widened-interval end seen so far, not just
            # the immediately-preceding element's end: intervals are sorted
            # by *start*, so a coarse-precision (wide) interval can extend
            # past its immediate successor's end. Using only the previous
            # element's end would wrongly report a "gap" already covered by
            # that earlier, wider interval -- found during adversarial
            # review, see docs/phase5-v0.5-gap-analysis-design.md §23.
            running_end = absent_events[0][1]
            running_end_id = absent_events[0][2]
            for k in range(1, len(absent_events)):
                gap_start = running_end
                gap_end = absent_events[k][0]
                bracket_start_id = running_end_id
                if absent_events[k][1] > running_end:
                    running_end = absent_events[k][1]
                    running_end_id = absent_events[k][2]
                if gap_start >= gap_end:
                    continue
                duration = (gap_end - gap_start).total_seconds()
                if duration < min_gap_seconds:
                    continue

                # Strict interior overlap: a present-source assertion must
                # fall *strictly inside* (gap_start, gap_end) to establish
                # activity *during* the gap. A present-source assertion
                # landing exactly on gap_start/gap_end coincides with an
                # instant absent_source itself already has evidence for
                # (that's why it's a boundary, not a gap) -- it does not
                # establish present-source activity during the silence and
                # must not count, or two sources with identical, fully
                # overlapping timelines would wrongly generate a "gap"
                # between every consecutive pair of their own shared points.
                corroborating = tuple(
                    sorted(
                        w[2]
                        for w in present_events
                        if w[0] < gap_end and w[1] > gap_start
                    )
                )
                if len(corroborating) < min_corroborating_events:
                    continue

                findings.append(
                    GapFinding(
                        absent_source=absent_source,
                        present_source=present_source,
                        interval_start=gap_start,
                        interval_end=gap_end,
                        corroborating_time_assertion_ids=corroborating,
                        bounding_absent_assertion_ids=(bracket_start_id, absent_events[k][2]),
                    )
                )

    findings.sort(
        key=lambda f: (f.interval_start, f.interval_end, f.absent_source, f.present_source)
    )
    return GapAnalysisResult(
        findings=tuple(findings),
        excluded_no_time_assertion=excluded_no_time_assertion,
        excluded_no_declared_source=excluded_no_declared_source,
        excluded_ambiguous_source=excluded_ambiguous_source,
    )
