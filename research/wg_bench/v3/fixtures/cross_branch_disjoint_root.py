"""V3 CROSS_BRANCH_DISJOINT_ROOT: structurally identical to
``cross_branch_shared_root.py`` (two disjoint 2-hop branches, A-M-D and
A-N-D), but branch "via N" cites a genuinely different root, E2, instead
of E1. A true-negative sanity control at the same topology as the
shared-root sibling fixture.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-cross-branch-disjoint-root-01"
FIXTURE_CLASS = "CROSS_BRANCH_DISJOINT_ROOT"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A-M-D cites root E1 directly (both hops); A-N-D cites root E2 directly "
        "(both hops). No NormalizedEvent anywhere. Genuinely disjoint roots."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="via M",
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="via N",
            direct_reference_labels=frozenset({"E2"}),
            root_evidence_labels=frozenset({"E2"}),
        ),
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Deliberate BASELINE-EQUIVALENCE case (true negative for false-"
        "corroboration): with no indirection present, Baseline 2 and "
        "Witnessgraph read identical information and both correctly report "
        "independent/disjoint. Paired with cross_branch_shared_root.py to show "
        "the two methods only diverge when NormalizedEvent indirection is "
        "actually present -- not on cross-branch topology alone."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/cross-branch-disjoint-root-01/E1")
    g.evidence("E2", b"wg-bench-v3/cross-branch-disjoint-root-01/E2")
    g.edge("A", "M", ("E1",))
    g.edge("M", "D", ("E1",))
    g.edge("A", "N", ("E2",))
    g.edge("N", "D", ("E2",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
