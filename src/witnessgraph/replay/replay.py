"""replay_and_verify: the v0.1 form of investigation replay.

Witnessgraph v0.1 does not maintain a step-by-step operation log to
replay; that is deferred to a later version once ingestion pipelines are
complex enough to need it (see DESIGN.md, Phase 0 scope notes). What v0.1
*does* guarantee: anyone holding a case directory can, without trusting
any stored value, independently recompute its provenance manifest from
the evidence graph itself and confirm it matches what was last recorded
-- see DESIGN.md principles 4 and 5. That recomputation is "replay" here.

See docs/phase3-v0.3-design.md §11: because the manifest algorithm
changed in v0.3 (``manifest_version`` 1 -> 2), a manifest recorded under
one version is not meaningfully comparable to one recomputed under a
different version -- comparing their hashes would produce a false
MISMATCH for an untampered case that simply predates the algorithm
change. ``ReplayResult.version_comparable`` makes that a distinct,
explicit outcome rather than silently folding it into MATCH/MISMATCH.
"""

from __future__ import annotations

from dataclasses import dataclass

from witnessgraph.core.provenance import ProvenanceManifest
from witnessgraph.store.case import Case


@dataclass(frozen=True)
class ReplayResult:
    recomputed_manifest: ProvenanceManifest
    recorded_manifest: ProvenanceManifest | None
    version_comparable: bool
    matches_recorded: bool


def replay_and_verify(case: Case) -> ReplayResult:
    """Recompute ``case``'s manifest and check it against the last recorded one.

    If there is no recorded manifest, or the recorded and recomputed
    manifests share the same ``manifest_version``, this is a normal
    MATCH/MISMATCH comparison (``version_comparable=True``). If the
    versions differ, the comparison is not meaningful:
    ``version_comparable`` is ``False`` and ``matches_recorded`` is
    ``False`` (callers must check ``version_comparable`` before treating
    a ``False`` ``matches_recorded`` as an integrity failure).
    """
    recomputed = case.compute_manifest()
    recorded = case.load_recorded_manifest()
    if recorded is None:
        return ReplayResult(
            recomputed_manifest=recomputed,
            recorded_manifest=None,
            version_comparable=True,
            matches_recorded=True,
        )
    if recorded.manifest_version != recomputed.manifest_version:
        return ReplayResult(
            recomputed_manifest=recomputed,
            recorded_manifest=recorded,
            version_comparable=False,
            matches_recorded=False,
        )
    matches = recomputed.manifest_hash == recorded.manifest_hash
    return ReplayResult(
        recomputed_manifest=recomputed,
        recorded_manifest=recorded,
        version_comparable=True,
        matches_recorded=matches,
    )
