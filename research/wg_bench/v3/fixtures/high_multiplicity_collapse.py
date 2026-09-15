"""V3 HIGH_MULTIPLICITY_COLLAPSE: 5 structurally distinct 3-hop chains
(A-Xi-Yi-D, i=1..5), each hop citing its own distinct NormalizedEvent (15
pairwise-distinct events total), every one derived_from the single root
E1. Structurally different from V2's HIGH_PATH_SHARED_ROOT (2-hop, 6-way
fan): this is 3-hop, 5-way, and every branch is a 3-node path with no
entity shared between branches at all.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-high-multiplicity-collapse-01"
FIXTURE_CLASS = "HIGH_MULTIPLICITY_COLLAPSE"
_BRANCHES = ("1", "2", "3", "4", "5")

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "5 disjoint 3-hop branches A-Xi-Yi-D (i=1..5). Each of the 3 hops per "
        "branch cites its own distinct NormalizedEvent (15 events total), all "
        "derived_from root E1."
    ),
    expected_shortest_path_count=5,
    expected_chains=tuple(
        ExpectedChainV2(
            label=f"branch {i}",
            direct_reference_labels=frozenset({f"Ev{i}a", f"Ev{i}b", f"Ev{i}c"}),
            root_evidence_labels=frozenset({"E1"}),
        )
        for i in _BRANCHES
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=False,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Scales V2's 'path multiplicity is not additional root evidence' finding "
        "to a deeper (3-hop), independently-designed topology. Baseline 2 sees 15 "
        "pairwise-disjoint direct ids across 5 chains and wrongly implies strong "
        "independent corroboration; Witnessgraph correctly aggregates all 5 to "
        "the single root E1."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/high-multiplicity-collapse-01/E1")
    for i in _BRANCHES:
        x, y = f"X{i}", f"Y{i}"
        for suffix, (src, dst) in zip(("a", "b", "c"), (("A", x), (x, y), (y, "D")), strict=True):
            label = f"Ev{i}{suffix}"
            g.chained_event(
                label,
                event_type="hop",
                derived_from_labels=("E1",),
                attributes={"branch": i, "step": suffix},
            )
            g.edge(src, dst, (label,))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
