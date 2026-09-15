"""PARTIAL_OVERLAP: three tied-shortest chains whose root evidence sets
pairwise overlap only partially.

A -> {X1, X2, X3} -> D, three parallel 2-hop chains:
  chain A (via X1): roots to {E1, E2}
  chain B (via X2): roots to {E2, E3}
  chain C (via X3): roots to {E4}

Pairwise: (A, B) share E2 -- not disjoint. (A, C) and (B, C) share
nothing -- disjoint. Overall, NOT every pair is disjoint, so the correct
top-level ``fully_evidence_independent`` verdict is False. But that
single boolean does not surface that 2 of the 3 pairs (A-C and B-C) are,
in fact, genuinely root-evidence-disjoint -- this is WG-Bench's fixture
for H3 (the boolean/null representation's information loss for partial
overlap).
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "partial-overlap-01"
FIXTURE_CLASS = "PARTIAL_OVERLAP"

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A->{X1,X2,X3}->D. Chain A roots to {E1,E2}; chain B roots to {E2,E3}; chain "
        "C roots to {E4}. (A,B) share E2; (A,C) and (B,C) are disjoint."
    ),
    expected_shortest_path_count=3,
    expected_chains=(
        ExpectedChain(label="chain A (via X1)", root_evidence_labels=frozenset({"E1", "E2"})),
        ExpectedChain(label="chain B (via X2)", root_evidence_labels=frozenset({"E2", "E3"})),
        ExpectedChain(label="chain C (via X3)", root_evidence_labels=frozenset({"E4"})),
    ),
    root_sets_identical=False,
    root_sets_disjoint=False,
    root_sets_partial_overlap=True,
    is_adversarial=False,
    baseline_expected_classification="multiple_paths",
    provenance_expected_classification="not_independent",
    known_limitation=(
        "fully_evidence_independent is correctly False (not every pair is disjoint), "
        "but that single boolean does not surface that 2 of the 3 chain pairs "
        "(chain A/chain C and chain B/chain C) are, in fact, root-evidence-disjoint. "
        "A consumer reading only the top-level boolean cannot distinguish this "
        "fixture from one where every pair shares evidence; the underlying "
        "per-chain root_evidence_ids fields do retain enough information to "
        "reconstruct the pairwise structure, but the analysis itself does not "
        "compute or expose a pairwise/graded verdict."
    ),
    notes=(
        "WG-Bench's H3 fixture: demonstrates that the single top-level "
        "fully_evidence_independent boolean is coarser than the full pairwise "
        "structure already present in the chains' individual root_evidence_ids."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    for label in ("E1", "E2", "E3", "E4"):
        g.evidence(label, f"wg-bench/partial-overlap-01/{label}".encode())
    g.edge("A", "X1", ("E1",))
    g.edge("X1", "D", ("E2",))
    g.edge("A", "X2", ("E2",))
    g.edge("X2", "D", ("E3",))
    g.edge("A", "X3", ("E4",))
    g.edge("X3", "D", ("E4",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
    )
