"""IDENTICAL_ROOT_SETS: three structurally distinct shortest chains that
all share the exact same root evidence set.

A -> {M1, M2, M3} -> D, three parallel 2-hop chains, every hop of every
chain derived_from the single EvidenceItem E1. This is the strongest
minimal demonstration that structural multiplicity is not evidence
independence: three "different-looking" chains, one underlying record.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "identical-root-sets-01"
FIXTURE_CLASS = "IDENTICAL_ROOT_SETS"

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A->{M1,M2,M3}->D, three parallel 2-hop chains, every hop of every chain "
        "derived_from the single EvidenceItem E1."
    ),
    expected_shortest_path_count=3,
    expected_chains=(
        ExpectedChain(label="via M1", root_evidence_labels=frozenset({"E1"})),
        ExpectedChain(label="via M2", root_evidence_labels=frozenset({"E1"})),
        ExpectedChain(label="via M3", root_evidence_labels=frozenset({"E1"})),
    ),
    root_sets_identical=True,
    root_sets_disjoint=False,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    baseline_expected_classification="multiple_paths",
    provenance_expected_classification="not_independent",
    known_limitation=None,
    notes=(
        "The strongest minimal demonstration that structural multiplicity is not "
        "evidence independence: three chains that look structurally distinct rest "
        "entirely on one underlying EvidenceItem."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    g.evidence("E1", b"wg-bench/identical-root-sets-01/E1")
    for midpoint in ("M1", "M2", "M3"):
        g.edge("A", midpoint, ("E1",))
        g.edge(midpoint, "D", ("E1",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
    )
