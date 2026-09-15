"""MIXED_DIRECT_DERIVED: one chain cites its root EvidenceItem DIRECTLY
(no NormalizedEvent indirection); the other cites a NormalizedEvent that
eventually resolves to that SAME root.

Purpose: test normalization of provenance depth. Baseline 2's raw
direct-reference comparison treats an EvidenceItem id and a
NormalizedEvent id as simply two different opaque strings -- it has no
notion that they might, after resolution, name "the same underlying
record at different provenance depths." Witnessgraph's recursive
resolution normalizes both down to the same root id and correctly
reports the chains as sharing evidence.

Diamond A -> {B, C} -> D. Chain "via B" cites E1 directly on both hops.
Chain "via C" cites event Ev1 (derived_from E1) on both hops.
"""

from __future__ import annotations

from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from witnessgraph.store.case import Case

FIXTURE_ID = "mixed-direct-derived-01"
FIXTURE_CLASS = "MIXED_DIRECT_DERIVED"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Chain 'via B' cites root EvidenceItem E1 directly on "
        "both hops. Chain 'via C' cites NormalizedEvent Ev1 (derived_from E1) on "
        "both hops -- same eventual root, different provenance depth. Direct "
        "reference sets {E1} and {Ev1} are disjoint (an EvidenceItem id and a "
        "NormalizedEvent id are never equal); root sets are both {E1}."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="via B",
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="via C",
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
        "Tests that Witnessgraph's resolution normalizes provenance depth (a direct "
        "EvidenceItem citation and a one-hop-derived citation of the same evidence "
        "are treated identically once resolved), while Baseline 2's raw-id "
        "comparison necessarily cannot -- an EvidenceItem id and a NormalizedEvent "
        "id live in the same id space but are never equal to each other even when "
        "they concern the same underlying record."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV2(case)
    g.evidence("E1", b"wg-bench-v2/mixed-direct-derived-01/E1")
    g.event("Ev1", event_type="session", derived_from_evidence_labels=("E1",), attributes={})
    g.edge("A", "B", ("E1",))
    g.edge("B", "D", ("E1",))
    g.edge("A", "C", ("Ev1",))
    g.edge("C", "D", ("Ev1",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
