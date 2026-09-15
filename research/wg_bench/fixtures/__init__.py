"""The eight WG-Bench fixture classes (one fixture per class in this
initial benchmark) -- see ``docs/research/wg-bench.md``'s fixture
taxonomy for what each class is designed to demonstrate.
"""

from __future__ import annotations

from research.wg_bench.fixtures import (
    byte_distinct_same_source,
    disjoint_multi_evidence,
    disjoint_roots,
    identical_root_sets,
    partial_overlap,
    path_count_deception,
    shared_root,
    single_path,
)
from research.wg_bench.model import Fixture

_MODULES = (
    single_path,
    shared_root,
    disjoint_roots,
    identical_root_sets,
    partial_overlap,
    byte_distinct_same_source,
    path_count_deception,
    disjoint_multi_evidence,
)


def all_fixtures() -> tuple[Fixture, ...]:
    """Every registered WG-Bench fixture, in a fixed, deterministic order."""
    return tuple(
        Fixture(ground_truth=module.GROUND_TRUTH, build=module.build) for module in _MODULES
    )
