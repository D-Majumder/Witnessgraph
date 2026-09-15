"""V3 PARTIAL_OVERLAP_COMPLEX: 4 tied-shortest 2-hop chains with a
non-trivial pairwise overlap graph -- P1={R1,R2}, P2={R2,R3}, P3={R3,R4},
P4={R5,R5}={R5} -- independently authored, at double V2's
PARTIAL_OVERLAP fixture's chain count (3 -> 4, so 3 -> 6 pairs), to
retest H3's information-loss finding at a larger scale.

All citations are direct evidence references (no NormalizedEvent), so
Baseline 2's direct sets equal Witnessgraph's root sets exactly here --
this fixture isolates H3 (Boolean/null information loss) as a
representation question independent of the V2 Baseline-2-vs-Witnessgraph
question; both methods' top-level booleans lose the identical pairwise
information.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-partial-overlap-complex-01"
FIXTURE_CLASS = "PARTIAL_OVERLAP_COMPLEX"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "4 disjoint 2-hop branches A-Mi-D (i=1..4), direct evidence only. "
        "P1 cites {R1,R2}, P2 cites {R2,R3}, P3 cites {R3,R4}, P4 cites {R5} "
        "(both hops cite R5). Pairwise: (P1,P2) share R2, (P2,P3) share R3, "
        "every other pair (P1,P3),(P1,P4),(P2,P4),(P3,P4) is disjoint -- 2 "
        "shared / 4 disjoint of 6 total pairs."
    ),
    expected_shortest_path_count=4,
    expected_chains=(
        ExpectedChainV2(
            label="P1",
            direct_reference_labels=frozenset({"R1", "R2"}),
            root_evidence_labels=frozenset({"R1", "R2"}),
        ),
        ExpectedChainV2(
            label="P2",
            direct_reference_labels=frozenset({"R2", "R3"}),
            root_evidence_labels=frozenset({"R2", "R3"}),
        ),
        ExpectedChainV2(
            label="P3",
            direct_reference_labels=frozenset({"R3", "R4"}),
            root_evidence_labels=frozenset({"R3", "R4"}),
        ),
        ExpectedChainV2(
            label="P4",
            direct_reference_labels=frozenset({"R5"}),
            root_evidence_labels=frozenset({"R5"}),
        ),
    ),
    direct_sets_disjoint=False,
    root_sets_disjoint=False,
    root_sets_partial_overlap=True,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=(
        "The single top-level fully_evidence_independent boolean is False "
        "(some pair overlaps), masking that 4 of 6 (66.7%) chain pairs are in "
        "fact root-evidence-disjoint -- the same rate V2's 3-chain "
        "PARTIAL_OVERLAP fixture found, now confirmed at a larger, "
        "independently-designed scale."
    ),
    notes=(
        "H3 retest at n=4 chains / 6 pairs (vs V2's n=3/3 pairs). Because every "
        "reference here is direct (no indirection), this specifically isolates "
        "the Boolean-representation question from the recursive-resolution "
        "question: both Baseline 2 and Witnessgraph compute the identical set "
        "structure and lose the identical pairwise information."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    for label in ("R1", "R2", "R3", "R4", "R5"):
        g.evidence(label, f"wg-bench-v3/partial-overlap-complex-01/{label}".encode())
    g.edge("A", "M1", ("R1",))
    g.edge("M1", "D", ("R2",))
    g.edge("A", "M2", ("R2",))
    g.edge("M2", "D", ("R3",))
    g.edge("A", "M3", ("R3",))
    g.edge("M3", "D", ("R4",))
    g.edge("A", "M4", ("R5",))
    g.edge("M4", "D", ("R5",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
