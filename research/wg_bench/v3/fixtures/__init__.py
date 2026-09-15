"""WG-Bench V3 fixture registry: 12 independently-designed adversarial
fixtures, structurally distinct from every V1/V2 fixture, deliberately
including cases NOT expected to favor Witnessgraph (see
``docs/research/wg-bench.md`` V3 §4/§9 for why).

V3 fixtures use ``research.wg_bench.v2.model.GroundTruthV2``/``FixtureV2``
(V2's own model, unmodified) so V3 results are directly comparable to V2's
via the same evaluation/metrics machinery.
"""

from __future__ import annotations

from research.wg_bench.v2.model import FixtureV2
from research.wg_bench.v3.fixtures import (
    byte_identical_different_source,
    cross_branch_disjoint_root,
    cross_branch_shared_root,
    direct_reference_convergence,
    direct_reference_decoy,
    high_multiplicity_collapse,
    high_multiplicity_disjoint,
    mixed_root_depth,
    multi_level_lineage_v3,
    partial_overlap_complex,
    redundant_representations,
    same_source_disjoint_root,
)

_MODULES = (
    multi_level_lineage_v3,
    cross_branch_shared_root,
    cross_branch_disjoint_root,
    mixed_root_depth,
    high_multiplicity_collapse,
    high_multiplicity_disjoint,
    partial_overlap_complex,
    redundant_representations,
    direct_reference_decoy,
    direct_reference_convergence,
    same_source_disjoint_root,
    byte_identical_different_source,
)


def all_fixtures() -> tuple[FixtureV2, ...]:
    """All 12 V3 fixtures, in a fixed, deterministic registration order."""
    return tuple(FixtureV2(ground_truth=m.GROUND_TRUTH, build=m.build) for m in _MODULES)
