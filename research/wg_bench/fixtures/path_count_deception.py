"""PATH_COUNT_DECEPTION: a high number of structurally distinct shortest
chains that all share the same single root evidence item.

A -> {M1..M8} -> D, eight parallel 2-hop chains, every hop of every
chain derived_from the single EvidenceItem E1. Structurally identical in
kind to IDENTICAL_ROOT_SETS, but at a much larger multiplicity -- this
fixture exists specifically to demonstrate that scaling the *number* of
structurally distinct chains does nothing to change the underlying
evidence-independence answer, even though it makes the naive
"many independent-looking chains" misreading far more visually
persuasive.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "path-count-deception-01"
FIXTURE_CLASS = "PATH_COUNT_DECEPTION"

_MIDPOINTS = tuple(f"M{i}" for i in range(1, 9))

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A->{M1..M8}->D, eight parallel 2-hop chains, every hop of every chain "
        "derived_from the single EvidenceItem E1."
    ),
    expected_shortest_path_count=len(_MIDPOINTS),
    expected_chains=tuple(
        ExpectedChain(label=f"via {m}", root_evidence_labels=frozenset({"E1"})) for m in _MIDPOINTS
    ),
    root_sets_identical=True,
    root_sets_disjoint=False,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    baseline_expected_classification="multiple_paths",
    provenance_expected_classification="not_independent",
    known_limitation=None,
    notes=(
        "Demonstrates why path count alone can overstate apparent corroboration: "
        "8 structurally distinct chains look, by count alone, like a strong "
        "multi-source signal, but they rest on exactly one underlying EvidenceItem "
        "-- identical in kind to IDENTICAL_ROOT_SETS, just scaled up to show the "
        "failure mode does not improve with more paths."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    g.evidence("E1", b"wg-bench/path-count-deception-01/E1")
    for midpoint in _MIDPOINTS:
        g.edge("A", midpoint, ("E1",))
        g.edge(midpoint, "D", ("E1",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
    )
