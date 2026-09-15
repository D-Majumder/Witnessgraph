"""HIGH_PATH_SHARED_ROOT: 6 structurally distinct shortest chains, each
citing its own distinct NormalizedEvent, all 6 resolving to the SAME
single root EvidenceItem.

Purpose: demonstrate that path multiplicity can be arbitrarily inflated
without additional root evidence, AND that Baseline 2 can be fooled at
scale, not just in the minimal 2-chain case (DIRECT_DIFFERENT_SHARED_ROOT):
6 pairwise-distinct direct references look like strong structural
corroboration to both path-count-only (Baseline 0) and direct-reference
(Baseline 2) reasoning, but every one of them ultimately rests on one
underlying record.
"""

from __future__ import annotations

from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from witnessgraph.store.case import Case

FIXTURE_ID = "high-path-shared-root-01"
FIXTURE_CLASS = "HIGH_PATH_SHARED_ROOT"
_MIDPOINTS = ("M1", "M2", "M3", "M4", "M5", "M6")

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A->{M1..M6}->D, 6 parallel 2-hop chains. Each chain's 2 hops cite the "
        "chain's own distinct NormalizedEvent (6 pairwise-distinct events), every "
        "one derived_from the single root E1. 6 pairwise-disjoint direct sets, 6 "
        "identical root sets."
    ),
    expected_shortest_path_count=6,
    expected_chains=tuple(
        ExpectedChainV2(
            label=f"via {m}",
            direct_reference_labels=frozenset({f"Ev{m}"}),
            root_evidence_labels=frozenset({"E1"}),
        )
        for m in _MIDPOINTS
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=False,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Scaled version of DIRECT_DIFFERENT_SHARED_ROOT: 6, not 2, chains, each with "
        "its own distinct direct reference, all resolving to one root. Shows the "
        "false-corroboration failure mode Baseline 2 exhibits on the minimal case "
        "does not vanish, and if anything looks more convincing, as chain count "
        "grows -- the same scaling argument V1's PATH_COUNT_DECEPTION fixture made "
        "against Baseline 0 also applies to Baseline 2."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV2(case)
    g.evidence("E1", b"wg-bench-v2/high-path-shared-root-01/E1")
    for m in _MIDPOINTS:
        g.event(
            f"Ev{m}",
            event_type="session",
            derived_from_evidence_labels=("E1",),
            attributes={"via": m},
        )
        g.edge("A", m, (f"Ev{m}",))
        g.edge(m, "D", (f"Ev{m}",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
