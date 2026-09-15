"""WG-Bench V2 fixture registry: the 8 retained V1 fixtures (via
``research.wg_bench.v2.fixtures.v1_adapter``, unchanged, unmodified) plus
7 new V2-only discriminating fixtures targeting the specific gap between
direct evidence-reference comparison (Baseline 2) and Witnessgraph's
actual recursive root-evidence resolution.

See ``docs/research/wg-bench.md``'s V2 fixture taxonomy for what each new
class demonstrates.
"""

from __future__ import annotations

from research.wg_bench.v2.fixtures import (
    direct_different_shared_root,
    direct_same_root_disjoint,
    high_path_disjoint_root,
    high_path_shared_root,
    mixed_direct_derived,
    multi_level_lineage,
    partial_multi_root,
    v1_adapter,
)
from research.wg_bench.v2.model import FixtureV2

_NEW_MODULES = (
    direct_different_shared_root,
    direct_same_root_disjoint,
    multi_level_lineage,
    mixed_direct_derived,
    high_path_shared_root,
    high_path_disjoint_root,
    partial_multi_root,
)


def all_fixtures() -> tuple[FixtureV2, ...]:
    """Every registered WG-Bench V2 fixture (8 retained V1 + 7 new = 15),
    in a fixed, deterministic order: V1 fixtures first (matching V1's own
    registration order exactly), then the new V2-only fixtures."""
    v1_fixtures = v1_adapter.all_v1_fixtures_as_v2()
    new_fixtures = tuple(
        FixtureV2(ground_truth=module.GROUND_TRUTH, build=module.build) for module in _NEW_MODULES
    )
    return v1_fixtures + new_fixtures
