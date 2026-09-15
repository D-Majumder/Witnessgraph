"""DISJOINT_MULTI_EVIDENCE: two structurally distinct shortest chains,
each grounded in *multiple* root evidence items, with no root overlap
between the two chains.

Diamond A -> {B, C} -> D. Chain "via B" derives_from E1 on its first hop
and E2 on its second, so its root evidence set is {E1, E2}. Chain
"via C" derives_from E3 then E4, so its root evidence set is {E3, E4}.
{E1, E2} and {E3, E4} share nothing. This tests correct multi-root
resolution per chain (root evidence is the *union* across a chain's
steps) combined with disjointness across chains -- distinct from
DISJOINT_ROOTS, where each chain has only a single root evidence id.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "disjoint-multi-evidence-01"
FIXTURE_CLASS = "DISJOINT_MULTI_EVIDENCE"

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Chain 'via B' roots to {E1,E2}; chain 'via C' roots to "
        "{E3,E4}. The two 2-evidence-item root sets are disjoint."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChain(label="via B", root_evidence_labels=frozenset({"E1", "E2"})),
        ExpectedChain(label="via C", root_evidence_labels=frozenset({"E3", "E4"})),
    ),
    root_sets_identical=False,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    baseline_expected_classification="multiple_paths",
    provenance_expected_classification="independent",
    known_limitation=None,
    notes=(
        "Tests correct multi-root resolution (root evidence is the union across a "
        "chain's own steps) combined with disjointness across chains -- distinct "
        "from DISJOINT_ROOTS, where each chain has only one root evidence id."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    for label in ("E1", "E2", "E3", "E4"):
        g.evidence(label, f"wg-bench/disjoint-multi-evidence-01/{label}".encode())
    g.edge("A", "B", ("E1",))
    g.edge("B", "D", ("E2",))
    g.edge("A", "C", ("E3",))
    g.edge("C", "D", ("E4",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
    )
