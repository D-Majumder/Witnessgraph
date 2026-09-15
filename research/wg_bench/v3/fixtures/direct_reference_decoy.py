"""V3 DIRECT_REFERENCE_DECOY: two fully parallel 3-hop paths through
disjoint intermediate entities (A-X1-X2-D and A-Y1-Y2-D, no shared node
at all, unlike V2's converging diamond A-{B,C}-D), each hop citing its
own distinct NormalizedEvent (6 events total), all 6 derived_from the
single root E1.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-direct-reference-decoy-01"
FIXTURE_CLASS = "DIRECT_REFERENCE_DECOY"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Two disjoint 3-hop paths, A-X1-X2-D and A-Y1-Y2-D (no shared "
        "intermediate entity). Each of the 6 hops cites its own distinct "
        "NormalizedEvent, all 6 derived_from root E1."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="via X",
            direct_reference_labels=frozenset({"EvX1", "EvX2", "EvX3"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="via Y",
            direct_reference_labels=frozenset({"EvY1", "EvY2", "EvY3"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=False,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Unlike V2's DIRECT_DIFFERENT_SHARED_ROOT (a 2-hop diamond converging "
        "through a shared final node D but distinct B/C), this fixture's two "
        "chains share only their endpoints -- every intermediate entity and "
        "every relationship is distinct. Confirms the discriminator does not "
        "depend on convergent diamond topology: Baseline 2 sees 6 "
        "pairwise-distinct events (fully disjoint) and wrongly implies "
        "independence regardless of whether the chains converge structurally."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/direct-reference-decoy-01/E1")
    hops = (
        ("EvX1", "A", "X1"),
        ("EvX2", "X1", "X2"),
        ("EvX3", "X2", "D"),
        ("EvY1", "A", "Y1"),
        ("EvY2", "Y1", "Y2"),
        ("EvY3", "Y2", "D"),
    )
    for label, src, dst in hops:
        g.chained_event(
            label, event_type="hop", derived_from_labels=("E1",), attributes={"hop": label}
        )
        g.edge(src, dst, (label,))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
