"""DIRECT_DIFFERENT_SHARED_ROOT: two chains cite entirely different,
distinctly-identified direct references (different ``NormalizedEvent``
ids), but both those events resolve to the SAME root ``EvidenceItem``.

Diamond A -> {B, C} -> D. Chain "via B"'s two hops both cite event Ev1
(``event_type="login"``, ``host=gw-1``), which derives_from E1. Chain
"via C"'s two hops both cite event Ev2 (``event_type="login"``,
``host=gw-2`` -- a *different* event, different id), which ALSO
derives_from E1.

Purpose: show whether direct evidence comparison (Baseline 2) can be
fooled by derived evidence. Baseline 2 sees two disjoint direct-reference
sets ({Ev1} vs {Ev2}) and wrongly concludes the chains are independent.
Witnessgraph resolves both events down to the same root E1 and correctly
reports them as NOT independent.
"""

from __future__ import annotations

from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from witnessgraph.store.case import Case

FIXTURE_ID = "direct-different-shared-root-01"
FIXTURE_CLASS = "DIRECT_DIFFERENT_SHARED_ROOT"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Chain 'via B' cites event Ev1 (derived_from E1); chain "
        "'via C' cites a DIFFERENT event Ev2 (derived_from E1, the SAME root). Direct "
        "reference sets {Ev1} and {Ev2} are disjoint; root sets {E1} and {E1} are not."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="via B",
            direct_reference_labels=frozenset({"Ev1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="via C",
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
        "The central Baseline-2-vs-Witnessgraph discriminating case: different direct "
        "(NormalizedEvent) references that resolve to the same root EvidenceItem. "
        "Baseline 2's raw-id comparison cannot detect the shared root without "
        "following derived_from through the event -- exactly the step it is defined "
        "not to take."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV2(case)
    g.evidence("E1", b"wg-bench-v2/direct-different-shared-root-01/E1")
    g.event(
        "Ev1", event_type="login", derived_from_evidence_labels=("E1",), attributes={"host": "gw-1"}
    )
    g.event(
        "Ev2", event_type="login", derived_from_evidence_labels=("E1",), attributes={"host": "gw-2"}
    )
    g.edge("A", "B", ("Ev1",))
    g.edge("B", "D", ("Ev1",))
    g.edge("A", "C", ("Ev2",))
    g.edge("C", "D", ("Ev2",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
