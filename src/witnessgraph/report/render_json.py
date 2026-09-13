"""render_report_json_bytes: a case's deterministic, machine-readable JSON
projection (v0.9).

See the approved v0.9 design (structured/machine-readable output) for the
full contract this module implements. Summary of the load-bearing
constraints -- deliberately mirroring ``report.render``'s own docstring
contract, applied to a second, independent output format:

- Pure: this module has no filesystem access and never accepts a
  ``Path``. Same inputs as ``report.render.render_report`` exactly.
- Deterministic: every array is sorted by the same explicit key its
  Markdown counterpart already uses (never SQLite/filesystem/hash-
  iteration/Python-construction order).
- No duplicate domain models: every function here reads existing public
  attributes of ``EvidenceItem``/``NormalizedEvent``/``Entity``/
  ``Relationship``/``Hypothesis``/``TimeAssertion``/``GapFinding``/``GapAnalysisResult``/
  ``TimeContradiction``/``TrackedGapFinding``/``TrackedTimeContradiction``
  directly and builds plain ``dict``/``list``/primitive trees -- this is
  a second *representation*, not a second model layer, exactly
  paralleling how ``report.render``'s section functions already produce
  a different (Markdown-line) representation of the same instances.
- Field selection deliberately matches what ``report.render`` already
  considers "the reportable shape" of each type (e.g. a ``TimeAssertion``
  inside a contradiction omits ``asserted_by``/``created_at``, exactly as
  ``_render_contradictions`` already does) -- this is parity with an
  existing decision, not a new one.
- SECURITY / display-safety contract (read this before touching any
  string field below): unlike Markdown, this module NEVER applies
  ``report.render._untrusted()`` (neutralize + code-span-wrap) to any
  string. JSON output preserves the EXACT, raw, unmodified underlying
  content -- including any bidi, zero-width, or control characters
  present in ingested or analyst-supplied data -- because a machine
  consumer (e.g. one verifying content against a hash) needs the true
  bytes, not a lossy placeholder substitution. Witnessgraph's JSON
  output therefore makes NO display-safety claim: a consumer that
  renders any string field here for human viewing (a terminal, a web
  page, a ticket) is responsible for its own Unicode/display-safety
  handling. See :func:`render_report_json_bytes` for the second half of
  this contract (the ``ensure_ascii`` clarification).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.ids import canonical_json_bytes
from witnessgraph.core.time_model import TimeAssertion
from witnessgraph.correlate.contradictions import TimeContradiction, detect_time_contradictions
from witnessgraph.correlate.gaps import GapAnalysisResult
from witnessgraph.correlate.tracking import is_still_reproduced

if TYPE_CHECKING:
    from witnessgraph.core.provenance import ProvenanceManifest
    from witnessgraph.store.base import Store

#: The JSON output schema version. Bump only on a breaking shape change;
#: additive fields do not require a bump. Direct precedent:
#: ``ProvenanceManifest.manifest_version`` exists for the same reason.
SCHEMA_VERSION = 1


def _timeline_sort_key(
    event: NormalizedEvent, assertions_by_event: dict[str, list[TimeAssertion]]
) -> datetime:
    times = assertions_by_event.get(event.id, [])
    return min((a.value for a in times), default=event.created_at)


# -- Section builders (mirror report.render's section renderers exactly,
#    field-for-field, but produce dict/list trees instead of Markdown
#    lines) --------------------------------------------------------------


def _build_manifest(
    recomputed_manifest: ProvenanceManifest, recorded_manifest: ProvenanceManifest | None
) -> dict[str, Any]:
    def _manifest_dict(m: ProvenanceManifest) -> dict[str, Any]:
        return {
            "collection_hashes": dict(m.collection_hashes),
            "manifest_hash": m.manifest_hash,
            "manifest_version": m.manifest_version,
        }

    if recorded_manifest is None:
        verdict = "NO_RECORDED_MANIFEST"
    elif recorded_manifest.manifest_version != recomputed_manifest.manifest_version:
        verdict = "NOT_COMPARABLE"
    elif recomputed_manifest.manifest_hash == recorded_manifest.manifest_hash:
        verdict = "MATCH"
    else:
        verdict = "MISMATCH"

    return {
        "recomputed": _manifest_dict(recomputed_manifest),
        "recorded": _manifest_dict(recorded_manifest) if recorded_manifest is not None else None,
        "verdict": verdict,
    }


def _build_evidence(store: Store) -> list[dict[str, Any]]:
    items = sorted(store.list_evidence(), key=lambda e: e.id)
    result = []
    for item in items:
        result.append(
            {
                "id": item.id,
                "source_adapter": item.source_adapter,
                "adapter_version": item.adapter_version,
                "source_locator": item.source_locator,
                "raw_size_bytes": item.raw_size_bytes,
                "collected_at": item.collected_at,
                "observed_at": item.observed_at,
                "chain_of_custody": [
                    {
                        "actor": record.actor,
                        "action": record.action,
                        "timestamp": record.timestamp,
                        "source_locator": record.source_locator,
                        "source_id": record.source_id,
                    }
                    for record in item.chain_of_custody
                ],
            }
        )
    return result


def _build_timeline(store: Store) -> list[dict[str, Any]]:
    assertions_by_event: dict[str, list[TimeAssertion]] = {}
    for assertion in store.list_time_assertions():
        assertions_by_event.setdefault(assertion.subject_event_id, []).append(assertion)

    events = sorted(
        store.list_normalized_events(),
        key=lambda e: (_timeline_sort_key(e, assertions_by_event), e.id),
    )
    result = []
    for event in events:
        assertions = sorted(assertions_by_event.get(event.id, []), key=lambda a: a.id)
        result.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "entity_ids": list(event.entity_ids),
                "derived_from": list(event.derived_from),
                "attributes": dict(event.attributes),
                "time_assertions": [
                    {
                        "id": a.id,
                        "value": a.value,
                        "precision": a.precision.value,
                        "asserted_by": a.asserted_by,
                        "source_evidence_id": a.source_evidence_id,
                    }
                    for a in assertions
                ],
            }
        )
    return result


def _build_entities(store: Store) -> list[dict[str, Any]]:
    entities = sorted(store.list_entities(), key=lambda e: e.id)
    return [
        {
            "id": entity.id,
            "entity_type": entity.entity_type,
            "identifiers": dict(entity.identifiers),
            "first_seen": entity.first_seen,
            "last_seen": entity.last_seen,
            "derived_from": list(entity.derived_from),
        }
        for entity in entities
    ]


def _build_relationships(store: Store) -> list[dict[str, Any]]:
    # No `created_at` field -- mirrors NormalizedEvent/TimeAssertion's own
    # JSON shape, both of which also omit it: like those two types,
    # Relationship's id is content-derived and created_at is excluded from
    # identity (ingest-time wall clock, not observational content), so it
    # is treated as not part of the type's reportable shape here either.
    relationships = sorted(store.list_relationships(), key=lambda r: r.id)
    return [
        {
            "id": rel.id,
            "relationship_type": rel.relationship_type,
            "source_entity_id": rel.source_entity_id,
            "target_entity_id": rel.target_entity_id,
            "attributes": dict(rel.attributes),
            "derived_from": list(rel.derived_from),
        }
        for rel in relationships
    ]


def _build_hypotheses(store: Store) -> list[dict[str, Any]]:
    hypotheses = sorted(store.list_hypotheses(), key=lambda h: h.id)
    return [
        {
            "id": hyp.id,
            "statement": hyp.statement,
            "status": hyp.status.value,
            "inferred_by": hyp.inferred_by,
            "created_at": hyp.created_at,
            "supporting_evidence": [
                {"kind": ref.kind, "id": ref.id} for ref in hyp.supporting_evidence
            ],
            "contradicting_evidence": [
                {"kind": ref.kind, "id": ref.id} for ref in hyp.contradicting_evidence
            ],
        }
        for hyp in hypotheses
    ]


def _assertion_summary(assertion: TimeAssertion) -> dict[str, Any]:
    return {
        "id": assertion.id,
        "value": assertion.value,
        "precision": assertion.precision.value,
        "source_evidence_id": assertion.source_evidence_id,
    }


def _build_contradictions(store: Store) -> list[dict[str, Any]]:
    found: list[TimeContradiction] = sorted(
        detect_time_contradictions(store),
        key=lambda c: (c.subject_event_id, c.assertion_a.id, c.assertion_b.id),
    )
    result = []
    for c in found:
        # Always exactly 2, ascending by id -- mirrors TrackedTimeContradiction's
        # own canonicalization (v0.8); defensive sort, not reliant on the
        # detector's incidental pairing order.
        ordered = sorted([c.assertion_a, c.assertion_b], key=lambda a: a.id)
        result.append(
            {
                "subject_event_id": c.subject_event_id,
                "assertions": [_assertion_summary(a) for a in ordered],
            }
        )
    return result


def _build_coverage_gaps(result: GapAnalysisResult) -> dict[str, Any]:
    return {
        "refine_source_by_attribute": result.refine_source_by_attribute,
        "findings": [
            {
                "absent_source": f.absent_source,
                "present_source": f.present_source,
                "absent_source_refinement": f.absent_source_refinement,
                "present_source_refinement": f.present_source_refinement,
                "interval_start": f.interval_start,
                "interval_end": f.interval_end,
                "corroborating_time_assertion_ids": list(f.corroborating_time_assertion_ids),
                # Order-significant [start, end] bracket -- NEVER sorted,
                # unlike the contradiction-assertion pairs above.
                "bounding_absent_assertion_ids": list(f.bounding_absent_assertion_ids),
            }
            for f in result.findings
        ],
        "excluded_no_time_assertion": result.excluded_no_time_assertion,
        "excluded_no_declared_source": result.excluded_no_declared_source,
        "excluded_ambiguous_source": result.excluded_ambiguous_source,
        "excluded_unrefined_fallback_with_refined_sibling": (
            result.excluded_unrefined_fallback_with_refined_sibling
        ),
    }


def _build_tracked_findings(store: Store) -> list[dict[str, Any]]:
    findings = sorted(store.list_tracked_findings(), key=lambda t: t.id)
    result = []
    for finding in findings:
        result.append(
            {
                "id": finding.id,
                "absent_source": finding.absent_source,
                "present_source": finding.present_source,
                "absent_source_refinement": finding.absent_source_refinement,
                "present_source_refinement": finding.present_source_refinement,
                "interval_start": finding.interval_start,
                "interval_end": finding.interval_end,
                "corroborating_time_assertion_ids": list(
                    finding.corroborating_time_assertion_ids
                ),
                "bounding_absent_assertion_ids": list(finding.bounding_absent_assertion_ids),
                "min_gap_seconds": finding.min_gap_seconds,
                "min_corroborating_events": finding.min_corroborating_events,
                "refine_source_by_attribute": finding.refine_source_by_attribute,
                "status": finding.status.value,
                "annotated_by": finding.annotated_by,
                "annotated_at": finding.annotated_at,
                "note": finding.note,
                # Live-recomputed, never persisted -- see TrackedGapFinding/
                # correlate.tracking.is_still_reproduced. Deterministic for
                # fixed case state; can legitimately differ between two
                # calls separated by an intervening ingest.
                "still_reproduced": is_still_reproduced(store, finding),
            }
        )
    return result


def _build_tracked_contradictions(store: Store) -> list[dict[str, Any]]:
    # Deliberately NO "still_reproduced" field -- see this module's
    # docstring and TrackedTimeContradiction's own module docstring: a
    # genuinely detected contradiction is reproducible with certainty by
    # every future run under this codebase's append-only TimeAssertion
    # model, so such a field would always read true and convey no
    # information (the same v0.8 adversarial finding that removed it from
    # Markdown applies identically here -- JSON making it "free" to add
    # is not a reason to reintroduce it).
    contradictions = sorted(store.list_tracked_contradictions(), key=lambda t: t.id)
    return [
        {
            "id": c.id,
            "subject_event_id": c.subject_event_id,
            "assertion_ids": list(c.assertion_ids),
            "status": c.status.value,
            "annotated_by": c.annotated_by,
            "annotated_at": c.annotated_at,
            "note": c.note,
        }
        for c in contradictions
    ]


def build_report_json_tree(
    *,
    case_name: str,
    store: Store,
    recomputed_manifest: ProvenanceManifest,
    recorded_manifest: ProvenanceManifest | None,
    gap_analysis: GapAnalysisResult | None = None,
) -> dict[str, Any]:
    """Build the full JSON tree for a case's report (pure, no I/O, no encoding).

    Same inputs as ``report.render.render_report`` exactly, including the
    ``gap_analysis=None`` default -- existing callers passing no
    ``gap_analysis`` get ``"coverage_gaps": null`` (see the module
    docstring's display-safety contract for the string-field policy, and
    below for the ``coverage_gaps`` null-vs-empty distinction).

    ``coverage_gaps`` is ``null`` ONLY when ``gap_analysis is None`` (gap
    analysis was not run this call) -- this is the one place a ``null``
    in this schema carries a special "not run" meaning distinct from
    ordinary field-level ``None -> null`` mapping used everywhere else in
    this tree. A ``gap_analysis`` that was run and found nothing produces
    ``{"findings": [], ...}``, never ``null`` -- the two are never
    conflated.

    ``tracked_findings``/``tracked_contradictions`` are ALWAYS arrays
    (``[]`` when nothing is tracked, never omitted, never ``null``) --
    unlike ``coverage_gaps``, there is no "not run" state for either: the
    store either has rows or it doesn't.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "case_name": case_name,
        "manifest": _build_manifest(recomputed_manifest, recorded_manifest),
        "evidence": _build_evidence(store),
        "timeline": _build_timeline(store),
        "entities": _build_entities(store),
        "relationships": _build_relationships(store),
        "hypotheses": _build_hypotheses(store),
        "contradictions": _build_contradictions(store),
        "coverage_gaps": _build_coverage_gaps(gap_analysis) if gap_analysis is not None else None,
        "tracked_findings": _build_tracked_findings(store),
        "tracked_contradictions": _build_tracked_contradictions(store),
    }


def render_report_json_bytes(
    *,
    case_name: str,
    store: Store,
    recomputed_manifest: ProvenanceManifest,
    recorded_manifest: ProvenanceManifest | None,
    gap_analysis: GapAnalysisResult | None = None,
) -> bytes:
    """The only place JSON encoding happens for report output.

    Reuses ``core.ids.canonical_json_bytes`` verbatim -- no second
    canonical-JSON implementation exists anywhere in this module.
    Compact (no whitespace), sorted-key, UTF-8 bytes, with NO trailing
    newline (unlike ``report.render.render_report_bytes``'s Markdown
    output, which appends one) -- ``stdout`` and ``--output`` file writes
    must both use this exact byte string, unmodified, so the two are
    always byte-identical to each other.

    SECURITY NOTE -- read before changing this call: ``canonical_json_bytes``
    sets ``ensure_ascii=True``. This is REVERSIBLE JSON TRANSPORT ENCODING
    ONLY (e.g. a real U+200B becomes the 6-character escape sequence
    ``\\u200b`` in the byte stream, and any standard JSON parser decodes
    it straight back to the identical character) -- it provides NO
    display-safety guarantee and must never be confused with
    ``report.render._neutralize()``, which permanently, lossily replaces
    a dangerous code point with visible placeholder text specifically so
    a human reading raw Markdown sees a marker instead of an invisible/
    spoofing character. This function's string fields are never passed
    through ``_neutralize()``/``_untrusted()`` at all: JSON output
    preserves exact content for machine consumers, and any downstream
    tool that renders these string values for a human is solely
    responsible for its own Unicode/display-safety handling.
    """
    tree = build_report_json_tree(
        case_name=case_name,
        store=store,
        recomputed_manifest=recomputed_manifest,
        recorded_manifest=recorded_manifest,
        gap_analysis=gap_analysis,
    )
    return canonical_json_bytes(tree)
