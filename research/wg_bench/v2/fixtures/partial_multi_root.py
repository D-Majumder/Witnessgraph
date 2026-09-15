"""PARTIAL_MULTI_ROOT: 4 structurally distinct shortest chains with a
richer pairwise overlapping/disjoint root structure than V1's
PARTIAL_OVERLAP (3 chains) -- measures the information loss of the
current Boolean/null ``fully_evidence_independent`` representation at a
larger, more realistic scale.

A -> {X1, X2, X3, X4} -> D:
  chain A (via X1): roots to {E1, E2}
  chain B (via X2): roots to {E2, E3}
  chain C (via X3): roots to {E3, E4}
  chain D (via X4): roots to {E5}

Pairwise (6 pairs total): (A,B) share E2; (B,C) share E3; (A,C), (A,D),
(B,D), (C,D) are disjoint -- 4 of 6 pairs (66.7%) are genuinely
root-evidence-disjoint, but the single top-level boolean is False (not
every pair is disjoint) and surfaces none of that structure.
"""

from __future__ import annotations

from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from witnessgraph.store.case import Case

FIXTURE_ID = "partial-multi-root-01"
FIXTURE_CLASS = "PARTIAL_MULTI_ROOT"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A->{X1,X2,X3,X4}->D. Chain A roots to {E1,E2}; chain B to {E2,E3}; chain C "
        "to {E3,E4}; chain D to {E5}. (A,B) and (B,C) share evidence; the other 4 of "
        "6 pairs are disjoint."
    ),
    expected_shortest_path_count=4,
    expected_chains=(
        ExpectedChainV2(
            label="chain A (via X1)",
            direct_reference_labels=frozenset({"E1", "E2"}),
            root_evidence_labels=frozenset({"E1", "E2"}),
        ),
        ExpectedChainV2(
            label="chain B (via X2)",
            direct_reference_labels=frozenset({"E2", "E3"}),
            root_evidence_labels=frozenset({"E2", "E3"}),
        ),
        ExpectedChainV2(
            label="chain C (via X3)",
            direct_reference_labels=frozenset({"E3", "E4"}),
            root_evidence_labels=frozenset({"E3", "E4"}),
        ),
        ExpectedChainV2(
            label="chain D (via X4)",
            direct_reference_labels=frozenset({"E5"}),
            root_evidence_labels=frozenset({"E5"}),
        ),
    ),
    direct_sets_disjoint=False,
    root_sets_disjoint=False,
    root_sets_partial_overlap=True,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=(
        "fully_evidence_independent is correctly False (not every pair is disjoint), "
        "but that single boolean does not surface that 4 of 6 chain pairs (A/C, A/D, "
        "B/D, C/D) are, in fact, root-evidence-disjoint -- a richer, 4-chain "
        "demonstration of the same information-loss finding V1's PARTIAL_OVERLAP "
        "fixture makes with 3 chains (H3)."
    ),
    notes=(
        "Richer PARTIAL_OVERLAP-style fixture: 4 chains, 6 pairs, a chain-of-overlap "
        "topology (A-B-C share pairwise, D fully separate) closer to what a larger "
        "real case graph might produce than V1's 3-chain minimal example."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV2(case)
    for label in ("E1", "E2", "E3", "E4", "E5"):
        g.evidence(label, f"wg-bench-v2/partial-multi-root-01/{label}".encode())
    g.edge("A", "X1", ("E1",))
    g.edge("X1", "D", ("E2",))
    g.edge("A", "X2", ("E2",))
    g.edge("X2", "D", ("E3",))
    g.edge("A", "X3", ("E3",))
    g.edge("X3", "D", ("E4",))
    g.edge("A", "X4", ("E5",))
    g.edge("X4", "D", ("E5",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
