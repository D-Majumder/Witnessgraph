"""DISJOINT_ROOTS: two structurally distinct shortest chains derived
from fully disjoint root evidence sets.

Diamond A -> {B, C} -> D. Chain "via B" roots to {E1}; chain "via C"
roots to {E2}. E1 and E2 are two entirely separate EvidenceItems -- this
is the benchmark's "true positive" case: path multiplicity here really
does correspond to root-evidence-independent support.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "disjoint-roots-01"
FIXTURE_CLASS = "DISJOINT_ROOTS"

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Chain 'via B' roots to {E1}; chain 'via C' roots to "
        "{E2}. E1 and E2 are disjoint EvidenceItems."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChain(label="via B", root_evidence_labels=frozenset({"E1"})),
        ExpectedChain(label="via C", root_evidence_labels=frozenset({"E2"})),
    ),
    root_sets_identical=False,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    baseline_expected_classification="multiple_paths",
    provenance_expected_classification="independent",
    known_limitation=None,
    notes=(
        "The benchmark's 'true positive' case: two structurally distinct chains that "
        "really are grounded in two disjoint EvidenceItems, so the path-count "
        "baseline's implied-corroboration reading happens to be correct here."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    g.evidence("E1", b"wg-bench/disjoint-roots-01/E1")
    g.evidence("E2", b"wg-bench/disjoint-roots-01/E2")
    g.edge("A", "B", ("E1",))
    g.edge("B", "D", ("E1",))
    g.edge("A", "C", ("E2",))
    g.edge("C", "D", ("E2",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
    )
