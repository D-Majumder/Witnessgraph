"""SHARED_ROOT: two structurally distinct shortest chains that share
some, but not all, root evidence.

Diamond A -> {B, C} -> D. Chain "via B" (A-B, B-D) derives entirely from
E1. Chain "via C" (A-C, C-D) derives from E1 on its first hop and E2 on
its second, so its root evidence set is {E1, E2}. The two chains are
structurally distinct but share E1 -- a naive path-count reading sees 2
structurally distinct chains and may read that as 2 independent
supporting sources, when in fact both ultimately rest, at least in part,
on the same underlying record. This is the canonical shared-root
false-corroboration scenario.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "shared-root-01"
FIXTURE_CLASS = "SHARED_ROOT"

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Chain 'via B' roots to {E1}; chain 'via C' roots to "
        "{E1, E2} -- the two chains share E1 but are not identical."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChain(label="via B", root_evidence_labels=frozenset({"E1"})),
        ExpectedChain(label="via C", root_evidence_labels=frozenset({"E1", "E2"})),
    ),
    root_sets_identical=False,
    root_sets_disjoint=False,
    root_sets_partial_overlap=True,
    is_adversarial=False,
    baseline_expected_classification="multiple_paths",
    provenance_expected_classification="not_independent",
    known_limitation=None,
    notes=(
        "A naive path-count reading sees 2 structurally distinct chains and may read "
        "that as 2 independent supporting sources; in fact both ultimately rest, at "
        "least in part, on the same E1."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    g.evidence("E1", b"wg-bench/shared-root-01/E1")
    g.evidence("E2", b"wg-bench/shared-root-01/E2")
    g.edge("A", "B", ("E1",))
    g.edge("B", "D", ("E1",))
    g.edge("A", "C", ("E1",))
    g.edge("C", "D", ("E2",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
    )
