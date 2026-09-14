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

from typing import TYPE_CHECKING, Any

from witnessgraph.core.entities import entity_to_json
from witnessgraph.core.ids import canonical_json_bytes
from witnessgraph.core.provenance import manifest_verdict
from witnessgraph.correlate.contradiction_tracking import tracked_contradiction_to_json
from witnessgraph.correlate.contradictions import contradictions_to_json, detect_time_contradictions
from witnessgraph.correlate.gaps import GapAnalysisResult, gap_analysis_to_json
from witnessgraph.correlate.timeline import build_timeline_json
from witnessgraph.correlate.tracking import is_still_reproduced, tracked_finding_to_json

if TYPE_CHECKING:
    from witnessgraph.core.provenance import ProvenanceManifest
    from witnessgraph.store.base import Store

#: The JSON output schema version. Bump only on a breaking shape change;
#: additive fields do not require a bump. Direct precedent:
#: ``ProvenanceManifest.manifest_version`` exists for the same reason.
SCHEMA_VERSION = 1


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

    return {
        "recomputed": _manifest_dict(recomputed_manifest),
        "recorded": _manifest_dict(recorded_manifest) if recorded_manifest is not None else None,
        "verdict": manifest_verdict(recomputed_manifest, recorded_manifest),
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


def _build_entities(store: Store) -> list[dict[str, Any]]:
    entities = sorted(store.list_entities(), key=lambda e: e.id)
    return [entity_to_json(entity) for entity in entities]


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


def _build_contradictions(store: Store) -> list[dict[str, Any]]:
    # contradictions_to_json applies its own defensive, independent sort
    # (see its docstring) -- detect_time_contradictions's own return
    # order is not independently guaranteed.
    return contradictions_to_json(detect_time_contradictions(store))


def _build_coverage_gaps(result: GapAnalysisResult) -> dict[str, Any]:
    return gap_analysis_to_json(result)


def _build_tracked_findings(store: Store) -> list[dict[str, Any]]:
    findings = sorted(store.list_tracked_findings(), key=lambda t: t.id)
    # still_reproduced is live-recomputed, never persisted -- see
    # TrackedGapFinding / correlate.tracking.is_still_reproduced.
    # Deterministic for fixed case state; can legitimately differ between
    # two calls separated by an intervening ingest.
    return [
        tracked_finding_to_json(f, still_reproduced=is_still_reproduced(store, f))
        for f in findings
    ]


def _build_tracked_contradictions(store: Store) -> list[dict[str, Any]]:
    contradictions = sorted(store.list_tracked_contradictions(), key=lambda t: t.id)
    return [tracked_contradiction_to_json(c) for c in contradictions]


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
        "timeline": build_timeline_json(store),
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
