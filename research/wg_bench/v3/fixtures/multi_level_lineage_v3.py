"""V3 MULTI_LEVEL_LINEAGE: genuine N>1-level ``derived_from`` chaining
(``Relationship -> NormalizedEvent -> NormalizedEvent -> EvidenceItem``),
contradicting V2's ``multi_level_lineage.py`` note that only one
indirection level is constructible -- see ``research.wg_bench.v3.graph_builder``
for the investigation. Two parallel 1-hop chains between A and D: one
cites the root evidence directly, the other reaches the SAME root through
two chained events.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-multi-level-lineage-01"
FIXTURE_CLASS = "MULTI_LEVEL_LINEAGE"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Two parallel 1-hop A-D relationships. Chain 'direct' cites root E1 "
        "directly. Chain 'chained' cites Ev2, where Ev2 = NormalizedEvent("
        "derived_from=(Ev1,)) and Ev1 = NormalizedEvent(derived_from=(E1,)) -- "
        "a genuine 2-level Event->Event->Evidence chain, not the 1-level "
        "Relationship->Event->Evidence depth every V1/V2 fixture uses."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="direct",
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="chained",
            direct_reference_labels=frozenset({"Ev2"}),
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
        "Baseline 2 sees direct sets {E1} vs {Ev2} -- disjoint, wrongly implies "
        "independence. Witnessgraph's _resolve_root_evidence_ids is an explicit "
        "BFS with a visited set (not depth-limited to one hop), so it correctly "
        "walks Ev2 -> Ev1 -> E1 and reports the true shared root. Confirms the "
        "V2 discriminator mechanism generalizes past exactly one indirection "
        "level, which V2's own fixture comment incorrectly claimed was "
        "unconstructible."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/multi-level-lineage-01/E1")
    g.chained_event("Ev1", event_type="capture", derived_from_labels=("E1",))
    g.chained_event("Ev2", event_type="derived_capture", derived_from_labels=("Ev1",))
    g.edge("A", "D", ("E1",))
    g.edge("A", "D", ("Ev2",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
