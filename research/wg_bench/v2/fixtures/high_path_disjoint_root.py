"""HIGH_PATH_DISJOINT_ROOT: 6 structurally distinct shortest chains, each
grounded in its own genuinely distinct root EvidenceItem -- no sharing
anywhere. The scalable positive case: every method (Baseline 0, 1, 2, and
Witnessgraph) should agree these 6 chains really are independently
corroborating.

Purpose: a scale sanity check showing Baseline 2 (and Witnessgraph) are
not simply "always pessimistic" -- both correctly recognize genuine,
large-scale independence, not only the false-corroboration failure modes
the other new fixtures probe.
"""

from __future__ import annotations

from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from witnessgraph.store.case import Case

FIXTURE_ID = "high-path-disjoint-root-01"
FIXTURE_CLASS = "HIGH_PATH_DISJOINT_ROOT"
_MIDPOINTS = ("M1", "M2", "M3", "M4", "M5", "M6")

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "A->{M1..M6}->D, 6 parallel 2-hop chains. Each chain cites its own distinct "
        "root EvidenceItem (E1..E6) directly on both hops -- 6 pairwise-disjoint "
        "direct sets AND 6 pairwise-disjoint root sets."
    ),
    expected_shortest_path_count=6,
    expected_chains=tuple(
        ExpectedChainV2(
            label=f"via {m}",
            direct_reference_labels=frozenset({f"E{i}"}),
            root_evidence_labels=frozenset({f"E{i}"}),
        )
        for i, m in enumerate(_MIDPOINTS, start=1)
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Scaled version of DISJOINT_ROOTS: the genuine-independence positive case at "
        "6 chains instead of 2, confirming Baseline 2 and Witnessgraph both scale "
        "correctly on true positives, not only failing identically or differently on "
        "false-corroboration cases."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV2(case)
    for i, m in enumerate(_MIDPOINTS, start=1):
        label = f"E{i}"
        g.evidence(label, f"wg-bench-v2/high-path-disjoint-root-01/{label}".encode())
        g.edge("A", m, (label,))
        g.edge(m, "D", (label,))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
