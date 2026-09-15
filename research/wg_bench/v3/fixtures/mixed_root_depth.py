"""V3 MIXED_ROOT_DEPTH: one chain cites root evidence directly, the
parallel chain reaches the identical root through one NormalizedEvent
hop -- the minimal case that isolates depth *mismatch* (0 vs 1 levels)
specifically, distinct from every V2 fixture (which always compares two
chains at the SAME depth, both via events or both direct).
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-mixed-root-depth-01"
FIXTURE_CLASS = "MIXED_ROOT_DEPTH"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Two parallel 1-hop A-D relationships. 'shallow' cites root E1 directly. "
        "'deep' cites NormalizedEvent Ev1 (derived_from=(E1,)) -- one level of "
        "indirection. Same eventual root, mismatched depth."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="shallow",
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="deep",
            direct_reference_labels=frozenset({"Ev1"}),
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
        "Baseline 2 sees {E1} vs {Ev1} -- disjoint, wrongly implies independence. "
        "Witnessgraph resolves 'deep' to {E1} via one BFS hop and correctly "
        "reports shared root. Isolates depth MISMATCH (not depth alone) as the "
        "discriminating variable: neither chain here is individually 'deep' in "
        "the way V2's fixtures test -- it is the asymmetry between 0 and 1 "
        "levels that a naive direct-reference reader has no way to normalize."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/mixed-root-depth-01/E1")
    g.chained_event("Ev1", event_type="capture", derived_from_labels=("E1",))
    g.edge("A", "D", ("E1",))
    g.edge("A", "D", ("Ev1",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
