"""V3 CROSS_BRANCH_SHARED_ROOT: two 2-hop branches through disjoint
intermediate entities (A-M-D and A-N-D, M != N), both hops on both
branches citing the SAME root evidence directly (no NormalizedEvent
indirection at all).

Deliberately NOT expected to separate Baseline 2 from Witnessgraph (see
docs/research/wg-bench.md V3 section, "fixtures not biased toward a
Witnessgraph win"): with no indirection anywhere in this fixture, direct
reference sets and root evidence sets are identical by construction, so
both methods see the same information and must agree.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-cross-branch-shared-root-01"
FIXTURE_CLASS = "CROSS_BRANCH_SHARED_ROOT"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A-M-D and A-N-D, two structurally disjoint 2-hop branches (M != N, no "
        "shared intermediate entity). Every one of the 4 relationships cites root "
        "E1 directly -- no NormalizedEvent anywhere in this fixture."
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
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
    ),
    direct_sets_disjoint=False,
    root_sets_disjoint=False,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Deliberate BASELINE-EQUIVALENCE case: direct reference sets and root "
        "evidence sets are literally the same set ({E1}) for every chain here, "
        "so Baseline 2 and Witnessgraph must produce the identical, both-correct "
        "verdict (not_independent/overlapping). Included specifically so V3's "
        "result set is not biased toward always finding a Witnessgraph advantage "
        "(spec section 4)."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/cross-branch-shared-root-01/E1")
    g.edge("A", "M", ("E1",))
    g.edge("M", "D", ("E1",))
    g.edge("A", "N", ("E1",))
    g.edge("N", "D", ("E1",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
