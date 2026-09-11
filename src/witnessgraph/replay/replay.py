"""replay_and_verify: the v0.1 form of investigation replay.

Witnessgraph v0.1 does not maintain a step-by-step operation log to
replay; that is deferred to a later version once ingestion pipelines are
complex enough to need it (see DESIGN.md, Phase 0 scope notes). What v0.1
*does* guarantee: anyone holding a case directory can, without trusting
any stored value, independently recompute its provenance manifest from
the evidence graph itself and confirm it matches what was last recorded
-- see DESIGN.md principles 4 and 5. That recomputation is "replay" here.
"""

from __future__ import annotations

from dataclasses import dataclass

from witnessgraph.core.provenance import ProvenanceManifest
from witnessgraph.store.case import Case


@dataclass(frozen=True)
class ReplayResult:
    recomputed_manifest: ProvenanceManifest
    recorded_manifest: ProvenanceManifest | None
    matches_recorded: bool


def replay_and_verify(case: Case) -> ReplayResult:
    """Recompute ``case``'s manifest and check it against the last recorded one."""
    recomputed = case.compute_manifest()
    recorded = case.load_recorded_manifest()
    matches = recorded is None or recomputed.manifest_hash == recorded.manifest_hash
    return ReplayResult(
        recomputed_manifest=recomputed, recorded_manifest=recorded, matches_recorded=matches
    )
