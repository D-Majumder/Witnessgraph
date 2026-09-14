"""Case overview: lightweight counts + manifest verdict for a whole case.

Fills the gap identified in ``docs/phase-ui-v1-architecture-design.md``
§5 gap #1: before this module, the only way to get evidence/entity/
relationship/hypothesis/tracked-finding counts plus the manifest verdict
was either several separate ``store.list_*`` calls or the full
``report --format json`` tree (which also serializes every EvidenceItem
and the whole timeline -- unnecessary cost for a landing page).

Pure aggregation only, in the same style as ``correlate.contradictions``/
``correlate.gaps``: no new domain concept, nothing that is not already a
plain ``len(...)`` of an existing collection or the existing manifest
verdict logic (``core.provenance.manifest_verdict``).
"""

from __future__ import annotations

from dataclasses import dataclass

from witnessgraph.core.provenance import ProvenanceManifest, manifest_verdict
from witnessgraph.store.base import Store


@dataclass(frozen=True)
class CaseOverview:
    case_name: str
    evidence_count: int
    normalized_event_count: int
    entity_count: int
    relationship_count: int
    hypothesis_count: int
    tracked_finding_count: int
    tracked_contradiction_count: int
    manifest_hash: str
    manifest_verdict: str


def compute_case_overview(
    store: Store,
    *,
    case_name: str,
    recomputed_manifest: ProvenanceManifest,
    recorded_manifest: ProvenanceManifest | None,
) -> CaseOverview:
    """Counts + manifest verdict for ``store`` -- one pass over each
    collection's existing ``list_*``, no new traversal or analysis."""
    return CaseOverview(
        case_name=case_name,
        evidence_count=len(store.list_evidence()),
        normalized_event_count=len(store.list_normalized_events()),
        entity_count=len(store.list_entities()),
        relationship_count=len(store.list_relationships()),
        hypothesis_count=len(store.list_hypotheses()),
        tracked_finding_count=len(store.list_tracked_findings()),
        tracked_contradiction_count=len(store.list_tracked_contradictions()),
        manifest_hash=recomputed_manifest.manifest_hash,
        manifest_verdict=manifest_verdict(recomputed_manifest, recorded_manifest),
    )


def case_overview_to_json(overview: CaseOverview) -> dict[str, object]:
    return {
        "case_name": overview.case_name,
        "evidence_count": overview.evidence_count,
        "normalized_event_count": overview.normalized_event_count,
        "entity_count": overview.entity_count,
        "relationship_count": overview.relationship_count,
        "hypothesis_count": overview.hypothesis_count,
        "tracked_finding_count": overview.tracked_finding_count,
        "tracked_contradiction_count": overview.tracked_contradiction_count,
        "manifest_hash": overview.manifest_hash,
        "manifest_verdict": overview.manifest_verdict,
    }
