"""MULTI_LEVEL_LINEAGE: every hop of every chain requires resolving
through its own distinct ``NormalizedEvent`` before reaching root
EvidenceItems -- stressing recursive resolution across a whole chain
(both hops), not just one hop as in DIRECT_DIFFERENT_SHARED_ROOT.

Note on the data model's actual indirection depth: ``core.events``
documents that an ``EvidenceItem`` never itself has a ``derived_from`` --
it is always the root. The maximum indirection Witnessgraph's current
model supports is therefore exactly one level
(``Relationship -> NormalizedEvent -> EvidenceItem``); a NormalizedEvent's
``derived_from`` cannot itself name another NormalizedEvent under any
current ingest adapter. "Multi-level" in this fixture means "every hop
independently requires that one level of resolution," not "N > 1 levels
of NormalizedEvent chaining" (which the model does not support) -- see
``correlate.graph._resolve_root_evidence_ids``'s own docstring, which
this fixture does not attempt to contradict.

Diamond A -> {B, C} -> D, two hops per chain. Chain "via B": hop A-B
cites event EvB1 (derived_from E1), hop B-D cites a DIFFERENT event EvB2
(also derived_from E1) -- two distinct events, same eventual root. Chain
"via C": hop A-C cites event EvC1 (derived_from E1, the SAME root), hop
C-D cites event EvC2 (also derived_from E1). All four events (EvB1, EvB2,
EvC1, EvC2) are pairwise distinct ids; all four resolve to the one root
E1.
"""

from __future__ import annotations

from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from witnessgraph.store.case import Case

FIXTURE_ID = "multi-level-lineage-01"
FIXTURE_CLASS = "MULTI_LEVEL_LINEAGE"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Every one of 4 hops (2 per chain) cites its own "
        "distinct NormalizedEvent (EvB1, EvB2, EvC1, EvC2), all four derived_from "
        "the single root E1. Direct reference sets {EvB1,EvB2} and {EvC1,EvC2} are "
        "fully disjoint (4 distinct event ids); root sets are both {E1}."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="via B",
            direct_reference_labels=frozenset({"EvB1", "EvB2"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="via C",
            direct_reference_labels=frozenset({"EvC1", "EvC2"}),
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
        "Stresses recursive resolution across an entire multi-hop chain, not one "
        "hop: 4 pairwise-distinct direct references across the two chains all "
        "collapse to one root. Baseline 2 sees full disjointness (4/4 distinct "
        "ids) and wrongly implies independence; Witnessgraph correctly aggregates "
        "each chain's per-hop resolved roots (a union across steps, per "
        "analyze_paths_evidence_overlap's existing documented behavior) and reports "
        "not independent."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV2(case)
    g.evidence("E1", b"wg-bench-v2/multi-level-lineage-01/E1")
    for label, host in (("EvB1", "b1"), ("EvB2", "b2"), ("EvC1", "c1"), ("EvC2", "c2")):
        g.event(
            label,
            event_type="session",
            derived_from_evidence_labels=("E1",),
            attributes={"host": host},
        )
    g.edge("A", "B", ("EvB1",))
    g.edge("B", "D", ("EvB2",))
    g.edge("A", "C", ("EvC1",))
    g.edge("C", "D", ("EvC2",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
