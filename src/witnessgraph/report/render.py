"""render_report / render_report_bytes: a case's deterministic Markdown projection.

See docs/phase2-v0.2-spec.md (the v0.2 specification) for the full contract
this module implements. Summary of the load-bearing constraints:

- Pure: this module has no filesystem access and never accepts a ``Path``.
  ``case_name`` is an explicit, plain ``str`` input (the caller derives it
  from ``case_dir.name``); everything else comes from a ``Store`` and
  already-computed ``ProvenanceManifest`` instances.
- Deterministic: every collection is sorted by an explicit key before
  rendering; no wall-clock timestamps, environment info, or non-canonical
  datetime formatting ever appears in the output.
- ``render_report(...) -> str`` builds the document; ``render_report_bytes``
  is the *only* place UTF-8 encoding happens (exactly once), and the
  document uses LF-only (``\\n``) line endings throughout.
- Untrusted, ingested/analyst-supplied strings (evidence metadata, entity
  fields, event attributes, hypothesis text, provenance/source strings)
  are passed through a fixed Unicode neutralization pass and rendered
  inside Markdown inline code spans, so neither Markdown-structure
  injection nor Unicode bidi/zero-width visual spoofing can corrupt the
  report's own structure or mislead a human reader.
- A ``Hypothesis``'s ``EvidenceRef``s are rendered exactly as stored
  (``kind``/``id``) without resolving them against the store -- a
  dangling reference (DESIGN.md principle 3's intentional storage/CLI
  validation boundary) renders without crashing, by construction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.time_model import TimeAssertion
from witnessgraph.core.tracked_finding import TrackedGapFinding
from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction
from witnessgraph.correlate.contradictions import TimeContradiction, detect_time_contradictions
from witnessgraph.correlate.gaps import GapAnalysisResult
from witnessgraph.correlate.tracking import is_still_reproduced

if TYPE_CHECKING:
    from witnessgraph.core.provenance import ProvenanceManifest
    from witnessgraph.store.base import Store

# -- Unicode neutralization -------------------------------------------------
#
# A fixed, hardcoded set of code points -- not a broad Unicode-category scan
# -- per the resolved design decision: bidirectional-control characters and
# zero-width/invisible formatting characters (which can make displayed text
# visually differ from its literal content), plus C0 control characters
# (excluding TAB and LF, which are left untouched) so that an embedded raw
# CR byte in ingested content can never violate the report's LF-only
# byte-level contract.

_BIDI_CONTROLS: frozenset[int] = frozenset(
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
    }
)
_ZERO_WIDTH: frozenset[int] = frozenset({0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF})
_C0_CONTROLS: frozenset[int] = (
    frozenset(range(0x00, 0x09)) | frozenset(range(0x0B, 0x20)) | frozenset({0x7F})
)
_NEUTRALIZE: frozenset[int] = _BIDI_CONTROLS | _ZERO_WIDTH | _C0_CONTROLS


def _neutralize(text: str) -> str:
    """Replace every targeted code point with a fixed, visible ``\\uXXXX`` placeholder."""
    return "".join(f"\\u{ord(ch):04X}" if ord(ch) in _NEUTRALIZE else ch for ch in text)


def _code_span(text: str) -> str:
    """Wrap ``text`` (already neutralized) in a Markdown inline code span that
    cannot be broken out of by backticks the text itself contains.

    CommonMark's rule: a code span's opening/closing fence must be longer
    than the longest run of consecutive backticks inside the content.
    """
    longest_run = 0
    current_run = 0
    for ch in text:
        if ch == "`":
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    fence = "`" * (longest_run + 1)
    needs_padding = text == "" or text.startswith("`") or text.endswith("`")
    if needs_padding:
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def _untrusted(text: str) -> str:
    """Render an untrusted, ingested/analyst-supplied string safely."""
    return _code_span(_neutralize(text))


def _format_datetime(value: datetime) -> str:
    """Canonical UTC ISO-8601, ``Z``-suffixed -- the same convention
    ``witnessgraph.core.ids.canonical_json_bytes`` uses, so the report's
    timestamps match what the manifest hash is actually computed over."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _optional_datetime(value: datetime | None) -> str:
    return _format_datetime(value) if value is not None else "(not set)"


def _sorted_dict_lines(label: str, values: dict[str, str]) -> list[str]:
    if not values:
        return [f"  - {label}: (none)"]
    lines = [f"  - {label}:"]
    for key in sorted(values):
        lines.append(f"    - {_untrusted(key)}: {_untrusted(values[key])}")
    return lines


def _timeline_sort_key(
    event: NormalizedEvent, assertions_by_event: dict[str, list[TimeAssertion]]
) -> datetime:
    times = assertions_by_event.get(event.id, [])
    return min((a.value for a in times), default=event.created_at)


# -- Section renderers --------------------------------------------------


def _render_header(
    case_name: str,
    recorded_manifest: ProvenanceManifest | None,
) -> str:
    lines = ["# Witnessgraph Investigation Report", "", f"Case: `{case_name}`", ""]
    if recorded_manifest is not None:
        lines.append(f"Recorded manifest hash: `{recorded_manifest.manifest_hash}`")
    else:
        lines.append("Recorded manifest hash: (no recorded manifest)")
    lines.append("")
    lines.append(
        "This report's own content is not covered by the manifest hash above "
        "-- see the Integrity Summary section for the exact coverage boundary."
    )
    return "\n".join(lines)


def _render_evidence_inventory(store: Store) -> str:
    lines = ["## Evidence Inventory", ""]
    items = sorted(store.list_evidence(), key=lambda e: e.id)
    if not items:
        lines.append("(none)")
        return "\n".join(lines)
    for item in items:
        lines.append(f"- Evidence `{item.id}`")
        lines.append(f"  - source_adapter: {_untrusted(item.source_adapter)}")
        lines.append(f"  - adapter_version: {_untrusted(item.adapter_version)}")
        lines.append(f"  - source_locator: {_untrusted(item.source_locator)}")
        lines.append(f"  - raw_size_bytes: {item.raw_size_bytes}")
        lines.append(f"  - collected_at: {_format_datetime(item.collected_at)}")
        lines.append(f"  - observed_at: {_optional_datetime(item.observed_at)}")
        if not item.chain_of_custody:
            lines.append("  - chain_of_custody: (none)")
        else:
            lines.append("  - chain_of_custody:")
            for record in item.chain_of_custody:
                locator = (
                    _untrusted(record.source_locator)
                    if record.source_locator is not None
                    else "(not set)"
                )
                source_id_text = (
                    _untrusted(record.source_id)
                    if record.source_id is not None
                    else "(no declared source)"
                )
                lines.append(
                    f"    - actor: {_untrusted(record.actor)}, "
                    f"action: {_untrusted(record.action)}, "
                    f"timestamp: {_format_datetime(record.timestamp)}, "
                    f"source_locator: {locator}, "
                    f"source_id: {source_id_text}"
                )
    return "\n".join(lines)


def _render_timeline(store: Store) -> str:
    lines = ["## Timeline", ""]
    assertions_by_event: dict[str, list[TimeAssertion]] = {}
    for assertion in store.list_time_assertions():
        assertions_by_event.setdefault(assertion.subject_event_id, []).append(assertion)

    events = sorted(
        store.list_normalized_events(),
        key=lambda e: (_timeline_sort_key(e, assertions_by_event), e.id),
    )
    if not events:
        lines.append("(none)")
        return "\n".join(lines)
    for event in events:
        lines.append(f"- Event `{event.id}` ({_untrusted(event.event_type)})")
        entity_ids = ", ".join(f"`{eid}`" for eid in event.entity_ids) or "(none)"
        lines.append(f"  - entity_ids: {entity_ids}")
        lines.append(f"  - derived_from: {', '.join(f'`{did}`' for did in event.derived_from)}")
        lines.extend(_sorted_dict_lines("attributes", event.attributes))
        assertions = sorted(assertions_by_event.get(event.id, []), key=lambda a: a.id)
        if not assertions:
            lines.append("  - time_assertions: (none)")
        else:
            lines.append("  - time_assertions:")
            for assertion in assertions:
                lines.append(
                    f"    - `{assertion.id}`: value={_format_datetime(assertion.value)}, "
                    f"precision={assertion.precision.value}, "
                    f"asserted_by={_untrusted(assertion.asserted_by)}, "
                    f"source_evidence_id=`{assertion.source_evidence_id}`"
                )
    return "\n".join(lines)


def _render_entities(store: Store) -> str:
    lines = ["## Entities", ""]
    entities = sorted(store.list_entities(), key=lambda e: e.id)
    if not entities:
        lines.append("(none)")
        return "\n".join(lines)
    for entity in entities:
        lines.append(f"- Entity `{entity.id}` ({_untrusted(entity.entity_type)})")
        lines.append(f"  - first_seen: {_optional_datetime(entity.first_seen)}")
        lines.append(f"  - last_seen: {_optional_datetime(entity.last_seen)}")
        lines.append(f"  - derived_from: {', '.join(f'`{did}`' for did in entity.derived_from)}")
        lines.extend(_sorted_dict_lines("identifiers", entity.identifiers))
    return "\n".join(lines)


def _render_relationships(store: Store) -> str:
    lines = ["## Relationships", ""]
    relationships = sorted(store.list_relationships(), key=lambda r: r.id)
    if not relationships:
        lines.append("(none)")
        return "\n".join(lines)
    for rel in relationships:
        lines.append(f"- Relationship `{rel.id}` ({_untrusted(rel.relationship_type)})")
        lines.append(f"  - source_entity_id: `{rel.source_entity_id}`")
        lines.append(f"  - target_entity_id: `{rel.target_entity_id}`")
        lines.append(f"  - derived_from: {', '.join(f'`{did}`' for did in rel.derived_from)}")
        lines.extend(_sorted_dict_lines("attributes", rel.attributes))
    return "\n".join(lines)


def _render_hypotheses(store: Store) -> str:
    lines = ["## Hypotheses", ""]
    hypotheses = sorted(store.list_hypotheses(), key=lambda h: h.id)
    if not hypotheses:
        lines.append("(none)")
        return "\n".join(lines)
    for hyp in hypotheses:
        lines.append(f"- Hypothesis `{hyp.id}`")
        lines.append(f"  - statement: {_untrusted(hyp.statement)}")
        lines.append(f"  - status: {hyp.status.value}")
        lines.append(f"  - inferred_by: {_untrusted(hyp.inferred_by)}")
        lines.append(f"  - created_at: {_format_datetime(hyp.created_at)}")
        if not hyp.supporting_evidence:
            lines.append("  - Supporting evidence: (none)")
        else:
            lines.append("  - Supporting evidence:")
            for ref in hyp.supporting_evidence:
                lines.append(f"    - kind={ref.kind}, id=`{ref.id}`")
        if not hyp.contradicting_evidence:
            lines.append("  - Contradicting evidence: (none)")
        else:
            lines.append("  - Contradicting evidence:")
            for ref in hyp.contradicting_evidence:
                lines.append(f"    - kind={ref.kind}, id=`{ref.id}`")
    return "\n".join(lines)


def _render_contradictions(store: Store) -> str:
    lines = ["## Contradictions", ""]
    found: list[TimeContradiction] = sorted(
        detect_time_contradictions(store),
        key=lambda c: (c.subject_event_id, c.assertion_a.id, c.assertion_b.id),
    )
    if not found:
        lines.append("(none)")
        return "\n".join(lines)
    for c in found:
        lines.append(f"- Event `{c.subject_event_id}`:")
        lines.append(
            f"  - `{c.assertion_a.id}`: {_format_datetime(c.assertion_a.value)} "
            f"(precision={c.assertion_a.precision.value}, "
            f"source_evidence_id=`{c.assertion_a.source_evidence_id}`)"
        )
        lines.append(
            f"  - `{c.assertion_b.id}`: {_format_datetime(c.assertion_b.value)} "
            f"(precision={c.assertion_b.precision.value}, "
            f"source_evidence_id=`{c.assertion_b.source_evidence_id}`)"
        )
    return "\n".join(lines)


def _format_resolved_source(source: str, refinement: str | None) -> str:
    """Render a resolved gap-analysis source for the report (v0.6).

    ``refinement`` is already neutralized by ``find_gaps`` (equality-safe)
    before this is ever called; it is additionally passed through
    ``_untrusted`` here for the same display-safety/code-span treatment
    every other untrusted string in this report already gets.
    """
    base = _untrusted(source)
    if refinement is None:
        return base
    return f"{base} (refined: {_untrusted(refinement)})"


def _render_coverage_gaps(result: GapAnalysisResult) -> str:
    lines = ["## Coverage Gaps", ""]
    if result.refine_source_by_attribute is not None:
        lines.append(
            f"Source identity refined by attribute {_untrusted(result.refine_source_by_attribute)} "
            "-- this does not prove physical source identity; the attribute value comes "
            "from ingested, untrusted evidence content."
        )
        lines.append("")
    if not result.findings:
        lines.append("(none)")
    else:
        for f in result.findings:
            absent_label = _format_resolved_source(f.absent_source, f.absent_source_refinement)
            present_label = _format_resolved_source(f.present_source, f.present_source_refinement)
            lines.append(
                f"- Source {absent_label} has no observed evidence in "
                f"[{_format_datetime(f.interval_start)}, {_format_datetime(f.interval_end)}) "
                f"while source {present_label} has corroborating activity"
            )
            lines.append(
                f"  - bounded by time assertions `{f.bounding_absent_assertion_ids[0]}`, "
                f"`{f.bounding_absent_assertion_ids[1]}`"
            )
            corroborating = ", ".join(f"`{cid}`" for cid in f.corroborating_time_assertion_ids)
            lines.append(f"  - corroborating time assertions: {corroborating}")
    excluded_summary = (
        f"Excluded from analysis: {result.excluded_no_time_assertion} normalized event(s) "
        f"with no time assertion, {result.excluded_no_declared_source} time assertion(s) "
        f"with no declared source, {result.excluded_ambiguous_source} time assertion(s) "
        "with an ambiguous declared source"
    )
    if result.refine_source_by_attribute is not None:
        excluded_summary += (
            f", {result.excluded_unrefined_fallback_with_refined_sibling} time assertion(s) "
            "in an unrefined fallback bucket excluded from comparison against a refined "
            "sibling group of the same coarse source (still comparable against genuinely "
            "different coarse sources)"
        )
    excluded_summary += (
        ". A finding above is never a claim that an event should have existed -- only "
        "that a different, independently-declared source has observed activity in the "
        "same interval while this source has none."
    )
    lines.append("")
    lines.append(excluded_summary)
    return "\n".join(lines)


_TRACKED_FINDING_DISCLOSURE = (
    "A tracked finding's status reflects an analyst's review process only. "
    "`reviewed` does not mean the underlying finding has been validated, "
    "and no status here is ever a claim that an absent event should have "
    "existed. Annotation history is not retained -- the current "
    "status/attribution/note is the only state stored; a prior value is "
    "permanently discarded once replaced. A finding whose corroborating "
    "evidence changes receives a new tracked identity even if its sources "
    "and interval are unchanged -- this is intentional and can require "
    "re-review of what looks like \"the same\" gap."
)


def _format_tracked_finding_annotation(finding: TrackedGapFinding) -> str:
    if finding.annotated_by is None:
        return "(not yet reviewed)"
    assert finding.annotated_at is not None  # paired by TrackedGapFinding's own invariant
    note = _untrusted(finding.note) if finding.note is not None else "(none)"
    return (
        f"by {_untrusted(finding.annotated_by)} at "
        f"{_format_datetime(finding.annotated_at)}, note: {note}"
    )


def _render_tracked_findings(store: Store) -> str | None:
    """``## Tracked Findings`` (v0.7). Returns ``None`` (omit the section
    entirely, not rendered as empty) when no findings have been tracked --
    "not tracked" and "tracked, currently empty" are not the same state
    the Coverage Gaps section keeps distinct, but there is no case here
    where an empty, rendered section would be meaningful: unlike gap
    analysis (which needs a caller-chosen threshold to even run), tracked
    findings are either present in the store or they are not.

    Pure function of ``store`` alone -- like ``_render_contradictions``,
    not like ``_render_coverage_gaps`` (which requires an externally
    computed, threshold-dependent result): a tracked finding's own
    recorded analysis parameters are enough to recompute its live
    "still reproduced" state with no external parameter needed.
    """
    findings = sorted(store.list_tracked_findings(), key=lambda t: t.id)
    if not findings:
        return None
    lines = ["## Tracked Findings", ""]
    for finding in findings:
        absent_label = _format_resolved_source(
            finding.absent_source, finding.absent_source_refinement
        )
        present_label = _format_resolved_source(
            finding.present_source, finding.present_source_refinement
        )
        still_reproduced = is_still_reproduced(store, finding)
        lines.append(f"- Tracked finding `{finding.id}`")
        lines.append(
            f"  - Source {absent_label} has no observed evidence in "
            f"[{_format_datetime(finding.interval_start)}, "
            f"{_format_datetime(finding.interval_end)}) while source "
            f"{present_label} has corroborating activity"
        )
        lines.append(
            f"  - status: {finding.status.value} "
            f"({_format_tracked_finding_annotation(finding)})"
        )
        lines.append(
            f"  - still reproduced by current evidence: {'yes' if still_reproduced else 'no'}"
        )
    lines.append("")
    lines.append(_TRACKED_FINDING_DISCLOSURE)
    return "\n".join(lines)


_TRACKED_CONTRADICTION_DISCLOSURE = (
    "Review status is workflow metadata only; reviewed or dismissed does "
    "not mean the contradiction is resolved, adjudicated, or that either "
    "assertion is more correct. Witnessgraph does not determine which "
    "disagreeing assertion is true."
)


def _format_tracked_contradiction_annotation(contradiction: TrackedTimeContradiction) -> str:
    if contradiction.annotated_by is None:
        return "(not yet reviewed)"
    assert contradiction.annotated_at is not None  # paired by the model's own invariant
    note = _untrusted(contradiction.note) if contradiction.note is not None else "(none)"
    return (
        f"by {_untrusted(contradiction.annotated_by)} at "
        f"{_format_datetime(contradiction.annotated_at)}, note: {note}"
    )


def _render_tracked_contradictions(store: Store) -> str | None:
    """``## Tracked Contradictions`` (v0.8). Returns ``None`` (section
    omitted entirely, not rendered as empty) when no contradictions have
    been tracked -- mirrors ``_render_tracked_findings``'s pattern, but
    structurally disjoint from it (docs/phase4-v0.4-gap-analysis-design.md
    §9): a separate section, never merged with ``## Contradictions`` or
    ``## Tracked Findings``.

    Deliberately has no "still reproduced" line -- see
    ``TrackedTimeContradiction``'s module docstring for why: a genuinely
    detected contradiction is reproducible with certainty by every future
    analysis run under this codebase's append-only TimeAssertion model,
    so such an indicator would either always read "yes" (no information)
    or risk being misread as a live re-validation signal.
    """
    contradictions = sorted(store.list_tracked_contradictions(), key=lambda t: t.id)
    if not contradictions:
        return None
    lines = ["## Tracked Contradictions", ""]
    for contradiction in contradictions:
        first_id, second_id = contradiction.assertion_ids
        lines.append(f"- Tracked contradiction `{contradiction.id}`")
        lines.append(f"  - subject event: `{contradiction.subject_event_id}`")
        lines.append(f"  - assertions: `{first_id}`, `{second_id}`")
        lines.append(
            f"  - status: {contradiction.status.value} "
            f"({_format_tracked_contradiction_annotation(contradiction)})"
        )
    lines.append("")
    lines.append(_TRACKED_CONTRADICTION_DISCLOSURE)
    return "\n".join(lines)


def _render_integrity_summary(
    recomputed_manifest: ProvenanceManifest,
    recorded_manifest: ProvenanceManifest | None,
) -> str:
    # Same-version formatting deliberately matches v0.2 byte-for-byte (no
    # manifest_version annotation) -- only a genuine version mismatch gets
    # the extra, explicit version disclosure. See docs/phase3-v0.3-design.md
    # §11 and the review that flagged unconditionally showing the version as
    # a broader-than-required v0.2 report compatibility break.
    lines = ["## Integrity Summary", ""]
    lines.append(f"Recomputed manifest hash: `{recomputed_manifest.manifest_hash}`")
    if recorded_manifest is None:
        lines.append("Recorded manifest hash: (no recorded manifest)")
    elif recorded_manifest.manifest_version != recomputed_manifest.manifest_version:
        lines.append(f"Recorded manifest hash: `{recorded_manifest.manifest_hash}`")
        lines.append(
            "Verdict: NOT COMPARABLE (manifest algorithm version differs: "
            f"recorded=v{recorded_manifest.manifest_version}, "
            f"recomputed=v{recomputed_manifest.manifest_version})"
        )
    else:
        lines.append(f"Recorded manifest hash: `{recorded_manifest.manifest_hash}`")
        matches = recomputed_manifest.manifest_hash == recorded_manifest.manifest_hash
        lines.append(f"Verdict: {'MATCH' if matches else 'MISMATCH'}")
    lines.append("")
    lines.append(
        "This verdict covers only: EvidenceItem.raw_content_hash for every "
        "evidence item, and the full canonical content of every "
        "NormalizedEvent, Entity, Relationship, TimeAssertion, and "
        "Hypothesis. It does NOT cover the following fields displayed "
        "elsewhere in this report, which are excluded from the manifest "
        "hash by design: "
        "EvidenceItem.chain_of_custody, EvidenceItem.collected_at, "
        "EvidenceItem.source_locator, EvidenceItem.source_adapter, "
        "EvidenceItem.adapter_version, EvidenceItem.ingest_parameters, and "
        "EvidenceItem.observed_at. A MATCH verdict does not, by itself, "
        "prove those specific fields are untampered."
    )
    return "\n".join(lines)


def render_report(
    *,
    case_name: str,
    store: Store,
    recomputed_manifest: ProvenanceManifest,
    recorded_manifest: ProvenanceManifest | None,
    gap_analysis: GapAnalysisResult | None = None,
) -> str:
    """Render a case's full, deterministic Markdown report as a ``str``.

    Pure: no filesystem access, no ``Path`` accepted, no wall-clock reads.
    ``case_name`` is a plain string the caller derives from ``case_dir.name``
    -- this module never touches the filesystem to determine it.

    ``gap_analysis``, if given, adds a ``## Coverage Gaps`` section (see
    ``witnessgraph.correlate.gaps`` and
    docs/phase5-v0.5-gap-analysis-design.md §20). Omitted entirely (not
    even rendered as empty) when ``None``, since gap analysis requires an
    explicit, no-default ``min_gap_seconds`` threshold this module has no
    basis to choose -- "not run" and "run, found nothing" are kept
    visibly distinct. Existing callers passing no ``gap_analysis`` see
    byte-identical output to before this parameter existed.
    """
    sections = [
        _render_header(case_name, recorded_manifest),
        _render_evidence_inventory(store),
        _render_timeline(store),
        _render_entities(store),
        _render_relationships(store),
        _render_hypotheses(store),
        _render_contradictions(store),
    ]
    if gap_analysis is not None:
        sections.append(_render_coverage_gaps(gap_analysis))
    tracked_findings_section = _render_tracked_findings(store)
    if tracked_findings_section is not None:
        sections.append(tracked_findings_section)
    tracked_contradictions_section = _render_tracked_contradictions(store)
    if tracked_contradictions_section is not None:
        sections.append(tracked_contradictions_section)
    sections.append(_render_integrity_summary(recomputed_manifest, recorded_manifest))
    return "\n\n".join(sections) + "\n"


def render_report_bytes(
    *,
    case_name: str,
    store: Store,
    recomputed_manifest: ProvenanceManifest,
    recorded_manifest: ProvenanceManifest | None,
    gap_analysis: GapAnalysisResult | None = None,
) -> bytes:
    """The only place UTF-8 encoding happens for report output.

    Callers (the CLI) must use the returned ``bytes`` object as-is for both
    stdout and ``--output`` file writes -- never re-derive or re-encode.
    """
    text = render_report(
        case_name=case_name,
        store=store,
        recomputed_manifest=recomputed_manifest,
        recorded_manifest=recorded_manifest,
        gap_analysis=gap_analysis,
    )
    return text.encode("utf-8")
