"""DIRECT_SAME_ROOT_DISJOINT: two direct references that LOOK similar at
the surface (same ``event_type``, same ``attributes``) -- exactly the
kind of superficial resemblance a human analyst skimming event summaries
might read as "the same kind of record" -- but are two genuinely
different, distinctly-identified ``NormalizedEvent``s (different
``derived_from``, hence different content-derived ids) that resolve to
DISJOINT root EvidenceItems.

Purpose: test recursive resolution against a superficial-similarity
distraction. Result (see docs/research/wg-bench.md's V2 section): because
every method here (Baseline 2 included) compares *ids*, never
``event_type``/``attributes`` content, none of them is actually fooled by
the surface resemblance -- this fixture is an honest, reported *negative*
finding: it demonstrates that ID-based comparison is already robust to
this particular distraction, not a case where recursion changes the
verdict. It is retained as a documented robustness check, not silently
dropped for failing to produce a positive gap.
"""

from __future__ import annotations

from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from witnessgraph.store.case import Case

FIXTURE_ID = "direct-same-root-disjoint-01"
FIXTURE_CLASS = "DIRECT_SAME_ROOT_DISJOINT"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Chain 'via B' cites event Ev1 (event_type='login', "
        "host='shared-gateway', derived_from E1); chain 'via C' cites event Ev2 with "
        "the SAME event_type/attributes but derived_from E2 (a different, disjoint "
        "root) -- Ev1 != Ev2 because derived_from differs, even though the surface "
        "fields match."
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
            root_evidence_labels=frozenset({"E2"}),
        ),
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Negative-control fixture: Ev1 and Ev2 share event_type and attributes (a "
        "surface-level distraction) but are distinct, content-addressed ids because "
        "derived_from differs, and correctly resolve to disjoint roots. Every method "
        "in this benchmark compares ids, never event content, so none is fooled here "
        "-- Baseline 2 and Witnessgraph agree. Documents that Baseline 2's advantage "
        "over Witnessgraph is specifically about following derived_from indirection "
        "(see DIRECT_DIFFERENT_SHARED_ROOT), not about resisting attribute-level "
        "surface resemblance, which id-based comparison already handles for free."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV2(case)
    g.evidence("E1", b"wg-bench-v2/direct-same-root-disjoint-01/E1")
    g.evidence("E2", b"wg-bench-v2/direct-same-root-disjoint-01/E2")
    g.event(
        "Ev1",
        event_type="login",
        derived_from_evidence_labels=("E1",),
        attributes={"host": "shared-gateway"},
    )
    g.event(
        "Ev2",
        event_type="login",
        derived_from_evidence_labels=("E2",),
        attributes={"host": "shared-gateway"},
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
