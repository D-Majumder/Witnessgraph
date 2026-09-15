"""SINGLE_PATH: exactly one relationship chain between source and target.

There is no structural multiplicity here for either the baseline or
Witnessgraph's evidence-independence check to (mis)read as
corroboration -- both correctly have nothing to report. This is
WG-Bench's sanity-check fixture: it establishes the "zero-multiplicity"
floor the other seven fixtures are built to depart from.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "single-path-01"
FIXTURE_CLASS = "SINGLE_PATH"

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description="One direct relationship A -> B, derived_from one EvidenceItem (E1).",
    expected_shortest_path_count=1,
    expected_chains=(ExpectedChain(label="direct", root_evidence_labels=frozenset({"E1"})),),
    root_sets_identical=None,
    root_sets_disjoint=None,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    baseline_expected_classification="no_or_single_path",
    provenance_expected_classification="not_applicable",
    known_limitation=None,
    notes=(
        "With only one chain, there is no multiplicity for either the baseline or "
        "Witnessgraph's evidence-independence check to (mis)read as corroboration -- "
        "both correctly have nothing to report."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    g.evidence("E1", b"wg-bench/single-path-01/E1")
    g.edge("A", "B", ("E1",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("B"),
        evidence_by_label=g.evidence_by_label,
    )
