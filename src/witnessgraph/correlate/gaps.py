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

v0.6 adds optional, analysis-time per-record source-identity refinement
(the ``refine_source_by_attribute`` parameter). This is a v0.6 *design
extension*, not part of v0.5's original scope -- it subdivides an
already-resolved coarse source using an existing
``NormalizedEvent.attributes`` key, never overrides, replaces, or invents
a coarse source identity, and is fully opt-in: ``refine_source_by_attribute
=None`` (the default) reproduces v0.5 behavior exactly, unchanged. The
refining attribute value is ingested, untrusted content -- unlike
``source_id`` (analyst-declared, validated at ingestion), it receives no
input-time validation; it is neutralized (see ``_neutralize_for_grouping``)
before being used as a grouping key or displayed, but this does not make
it trustworthy as proof of physical source identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.store.base import Store

#: Deliberately conservative floor: a single corroborating event is too
#: weak a basis to call anything a "gap" against it. A policy choice, not
#: derived from any data -- see docs/phase5-v0.5-gap-analysis-design.md §7/§23.
DEFAULT_MIN_CORROBORATING_EVENTS = 2

#: Code points neutralized (never silently dropped) in a refinement
#: attribute value before it is used as a grouping key or displayed.
#: Deliberately the same fixed set ``core.evidence._SOURCE_ID_FORBIDDEN_CODEPOINTS``
#: / ``report.render._NEUTRALIZE`` use, duplicated here rather than
#: imported (module-layering reasons identical to ``core.evidence``'s own
#: duplication -- see that module's comment). Unlike ``source_id``, this
#: value is *ingested, untrusted content* with no input-time validation,
#: so it cannot be rejected the way a bad ``source_id`` can be -- it is
#: neutralized instead, so a hidden zero-width/bidi character can never
#: silently make two visually-identical grouping keys compare unequal
#: (or vice versa) without a visible, deterministic trace.
_REFINEMENT_NEUTRALIZE_CODEPOINTS: frozenset[int] = (
    frozenset(
        {
            0x061C,
            0x200E,
            0x200F,
            0x202A,
            0x202B,
            0x202C,
            0x202D,
            0x202E,
            0x2066,
            0x2067,
            0x2068,
            0x2069,
            0x200B,
            0x200C,
            0x200D,
            0x2060,
            0xFEFF,
        }
    )
    | frozenset(range(0x00, 0x09))
    | frozenset(range(0x0B, 0x20))
    | frozenset({0x7F})
)


def _neutralize_for_grouping(value: str) -> str:
    """Replace every targeted code point with a fixed, visible ``\\uXXXX`` placeholder.

    Every literal backslash already present in ``value`` is escaped
    (doubled) *before* any code-point substitution happens -- without
    this, an actual forbidden character (e.g. U+200B) and a raw string
    that merely *spells out* its placeholder text (the literal 6
    characters ``\\u200B``) would neutralize to the exact same output,
    letting two genuinely different attribute values silently collide
    into one grouping key (found during adversarial review). Escaping
    the escape character first is what makes this encoding injective:
    the one substring `_neutralize_for_grouping` can ever produce on its
    own (a single backslash followed by ``u`` and four hex digits) can
    now only mean "a real substituted code point," never "input that
    happened to already look like one," since any literal backslash in
    the input is guaranteed to appear doubled in the output.
    """
    escaped_backslashes = value.replace("\\", "\\\\")
    return "".join(
        f"\\u{ord(ch):04X}" if ord(ch) in _REFINEMENT_NEUTRALIZE_CODEPOINTS else ch
        for ch in escaped_backslashes
    )


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

    ``absent_source``/``present_source`` are always the coarse, declared
    ``source_id`` -- v0.6 refinement never overrides or replaces them.
    ``absent_source_refinement``/``present_source_refinement`` are
    additive: ``None`` when refinement was not requested, or when the
    specific record(s) behind this finding had no value for the
    requested attribute (falls back to the coarse identity alone, per
    v0.6 scope); otherwise the neutralized attribute value that
    subdivided this side of the finding.
    """

    absent_source: str
    present_source: str
    interval_start: datetime
    interval_end: datetime
    corroborating_time_assertion_ids: tuple[str, ...]
    bounding_absent_assertion_ids: tuple[str, str]
    absent_source_refinement: str | None = None
    present_source_refinement: str | None = None


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

    ``excluded_unrefined_fallback_with_refined_sibling`` counts
    TimeAssertions belonging to a coarse source's unrefined-fallback
    bucket (records with no value for the requested attribute) when that
    *same* coarse source also has at least one successfully refined
    subgroup. Such a bucket is never compared against its refined
    siblings as though it were an independent source -- doing so would
    silently compare a coarse source against a strict subset of itself
    (the very same underlying records, minus the ones that happened to
    carry the attribute), producing a nonsensical self-comparison
    finding (found during adversarial review). It is still eligible to
    be compared against genuinely different coarse sources. Always 0
    when ``refine_source_by_attribute`` is ``None``.

    ``refine_source_by_attribute`` records exactly what was requested
    (or ``None``) for this call, purely so callers (CLI, report
    rendering) can transparently disclose it -- v0.6 scope, §5:
    "a user must not mistake refined output for ordinary v0.5 semantics."
    """

    findings: tuple[GapFinding, ...]
    excluded_no_time_assertion: int
    excluded_no_declared_source: int
    excluded_ambiguous_source: int
    excluded_unrefined_fallback_with_refined_sibling: int = 0
    refine_source_by_attribute: str | None = None


def _resolve_source(evidence: EvidenceItem) -> str | None:
    """Resolve ``evidence``'s coarse source identity, or ``None`` if unresolved.

    ``None`` covers both "no source_id was ever declared for this
    evidence" and "declared under two different source_ids" (an
    ambiguous, byte-identical-content case) -- callers must not guess
    between them. Never falls back to source_adapter/source_locator/
    collected_at -- see docs/phase5-v0.5-gap-analysis-design.md §5.
    Unchanged by v0.6: refinement (below) only ever subdivides what this
    function resolves, never replaces it.
    """
    declared = evidence.declared_source_ids()
    if len(declared) == 1:
        return next(iter(declared))
    return None


def _resolve_refinement(
    event: NormalizedEvent, refine_source_by_attribute: str | None
) -> str | None:
    """Resolve the v0.6 refinement value for ``event``, or ``None``.

    ``None`` means "no refinement requested" or "the requested attribute
    key is absent from this record" -- both fall back to the coarse
    source identity alone, per v0.6 scope §2. Never infers, guesses, or
    falls back to any other field -- exactly the one named attribute key,
    or nothing. The returned value (when not ``None``) is neutralized
    (§4/security) before being used as a grouping key.
    """
    if refine_source_by_attribute is None:
        return None
    raw_value = event.attributes.get(refine_source_by_attribute)
    if raw_value is None:
        return None
    return _neutralize_for_grouping(raw_value)


#: Internal grouping key: (coarse_source_id, is_refined, refined_value).
#: A 3-tuple rather than ``tuple[str, str | None]`` deliberately -- sorting
#: keys that mix a real refined value with "no refinement" would otherwise
#: compare ``None`` against ``str`` for ties on the coarse id, which
#: raises ``TypeError`` in Python. Using a ``bool`` discriminant plus an
#: always-``str`` third element keeps every key fully, safely orderable.
_SourceGroupKey = tuple[str, bool, str]


def find_gaps(
    store: Store,
    *,
    min_gap_seconds: float,
    min_corroborating_events: int = DEFAULT_MIN_CORROBORATING_EVENTS,
    refine_source_by_attribute: str | None = None,
) -> GapAnalysisResult:
    """Find cross-source coverage gaps across every pair of resolved sources.

    ``min_gap_seconds`` has no default claimed as objectively correct
    (docs/phase5-v0.5-gap-analysis-design.md §7/§23) and must be
    explicitly chosen by the caller. Deterministic and order-independent:
    every collection is sorted by content, never relied upon for
    insertion order (mirrors ``compute_manifest``/
    ``detect_time_contradictions``'s existing pattern).

    ``refine_source_by_attribute`` (v0.6, optional): when ``None`` (the
    default), behavior is byte-for-byte identical to v0.5 -- this
    parameter changes nothing about coarse source resolution, ordering,
    exclusions, or thresholds. When given a ``NormalizedEvent.attributes``
    key, each coarse source is additionally subdivided by that
    attribute's (neutralized) value for records that have it; records
    without it fall back to the coarse identity alone. Refinement never
    overrides, replaces, or invents a coarse source identity -- it only
    ever subdivides one. The attribute value is ingested, untrusted
    content and does not establish physical source identity.
    """
    events_by_id = {e.id: e for e in store.list_normalized_events()}
    evidence_by_id = {e.id: e for e in store.list_evidence()}
    all_assertions = store.list_time_assertions()

    events_with_assertion = {a.subject_event_id for a in all_assertions}
    excluded_no_time_assertion = sum(
        1 for event_id in events_by_id if event_id not in events_with_assertion
    )

    intervals: dict[_SourceGroupKey, list[tuple[datetime, datetime, str]]] = {}
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
        coarse_source = _resolve_source(source_evidence)
        assert coarse_source is not None  # guaranteed by the len(declared) == 1 branch above

        refinement = _resolve_refinement(event, refine_source_by_attribute)
        group_key: _SourceGroupKey = (
            (coarse_source, True, refinement)
            if refinement is not None
            else (coarse_source, False, "")
        )

        tolerance = timedelta(seconds=assertion.tolerance_seconds())
        widened = (assertion.value - tolerance, assertion.value + tolerance, assertion.id)
        intervals.setdefault(group_key, []).append(widened)

    for widened_list in intervals.values():
        widened_list.sort(key=lambda w: (w[0], w[2]))

    group_keys = sorted(intervals.keys())

    # A coarse source's unrefined-fallback bucket (records with no value
    # for the requested attribute) is never compared against a refined
    # sibling group *from that same coarse source* -- doing so would
    # compare a coarse source against a strict subset of itself (the
    # very same underlying records, minus the ones that happened to
    # carry the attribute), producing a nonsensical self-comparison
    # finding (found during adversarial review). It remains fully
    # eligible to be compared against any genuinely different coarse
    # source, including that source's own unrefined-fallback or refined
    # buckets -- only the same-coarse-source, fallback-vs-refined pairing
    # is excluded.
    coarse_sources_with_refinement = {key[0] for key in group_keys if key[1]}
    excluded_unrefined_fallback_with_refined_sibling = sum(
        len(intervals[key])
        for key in group_keys
        if not key[1] and key[0] in coarse_sources_with_refinement
    )

    findings: list[GapFinding] = []

    for absent_key in group_keys:
        absent_events = intervals[absent_key]
        if len(absent_events) < 2:
            continue  # nothing to bracket a gap between -- see §10
        absent_span_start = min(w[0] for w in absent_events)
        absent_span_end = max(w[1] for w in absent_events)

        for present_key in group_keys:
            if present_key == absent_key:
                continue
            if present_key[0] == absent_key[0] and (not present_key[1] or not absent_key[1]):
                # Same coarse source, and at least one side is its
                # unrefined-fallback bucket -- a self-comparison, skip.
                # (Two different refined siblings of the same coarse
                # source are a real, intended comparison and fall
                # through normally; a coarse source's fallback bucket is
                # unique, so this is the only same-coarse-source case
                # reachable now that present_key == absent_key is
                # already excluded above.)
                continue
            present_events = intervals[present_key]
            present_span_start = min(w[0] for w in present_events)
            present_span_end = max(w[1] for w in present_events)

            # Pair-level early exit only -- these two groups' overall
            # observed spans don't overlap at all, so no candidate window
            # from absent_key could ever be corroborated by present_key.
            # This does NOT clip individual gap windows below (see the
            # note on that below) -- it is purely "is it even possible
            # for this pair to produce a finding."
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
                        absent_source=absent_key[0],
                        present_source=present_key[0],
                        interval_start=gap_start,
                        interval_end=gap_end,
                        corroborating_time_assertion_ids=corroborating,
                        bounding_absent_assertion_ids=(bracket_start_id, absent_events[k][2]),
                        absent_source_refinement=absent_key[2] if absent_key[1] else None,
                        present_source_refinement=present_key[2] if present_key[1] else None,
                    )
                )

    findings.sort(
        key=lambda f: (
            f.interval_start,
            f.interval_end,
            f.absent_source,
            f.present_source,
            f.absent_source_refinement or "",
            f.present_source_refinement or "",
        )
    )
    return GapAnalysisResult(
        findings=tuple(findings),
        excluded_no_time_assertion=excluded_no_time_assertion,
        excluded_no_declared_source=excluded_no_declared_source,
        excluded_ambiguous_source=excluded_ambiguous_source,
        excluded_unrefined_fallback_with_refined_sibling=(
            excluded_unrefined_fallback_with_refined_sibling
        ),
        refine_source_by_attribute=refine_source_by_attribute,
    )
