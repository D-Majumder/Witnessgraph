"""V3 HIGH_MULTIPLICITY_DISJOINT: same 5-branch, 3-hop-per-branch
topology as ``high_multiplicity_collapse.py``, but each branch's events
resolve to its OWN distinct root (E1..E5) instead of a shared root.

Deliberately expected to be a BASELINE-EQUIVALENCE result (both Baseline
2 and Witnessgraph correctly report disjoint/independent): this is the
scaled, genuinely-positive counterpart, included specifically so V3 does
not only report cases where Witnessgraph wins (spec section 4).
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-high-multiplicity-disjoint-01"
FIXTURE_CLASS = "HIGH_MULTIPLICITY_DISJOINT"
_BRANCHES = ("1", "2", "3", "4", "5")

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "5 disjoint 3-hop branches A-Xi-Yi-D (i=1..5). Branch i's 3 hops each "
        "cite their own distinct NormalizedEvent, all derived_from branch i's "
        "OWN root Ei -- 5 disjoint roots, not 1 shared root."
    ),
    expected_shortest_path_count=5,
    expected_chains=tuple(
        ExpectedChainV2(
            label=f"branch {i}",
            direct_reference_labels=frozenset({f"Ev{i}a", f"Ev{i}b", f"Ev{i}c"}),
            root_evidence_labels=frozenset({f"E{i}"}),
        )
        for i in _BRANCHES
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Scaled true-negative control: with 5 genuinely disjoint roots, Baseline "
        "2 and Witnessgraph both correctly report independent -- included so the "
        "benchmark demonstrates Baseline 2 is not simply 'always wrong' at scale, "
        "only wrong specifically when the same root is reached through different "
        "unresolved direct references."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    for i in _BRANCHES:
        g.evidence(f"E{i}", f"wg-bench-v3/high-multiplicity-disjoint-01/E{i}".encode())
    for i in _BRANCHES:
        x, y = f"X{i}", f"Y{i}"
        for suffix, (src, dst) in zip(("a", "b", "c"), (("A", x), (x, y), (y, "D")), strict=True):
            label = f"Ev{i}{suffix}"
            g.chained_event(
                label,
                event_type="hop",
                derived_from_labels=(f"E{i}",),
                attributes={"branch": i, "step": suffix},
            )
            g.edge(src, dst, (label,))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
