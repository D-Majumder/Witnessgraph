"""V3 REDUNDANT_REPRESENTATIONS: two parallel 1-hop A-D relationships,
each citing a DIFFERENT NormalizedEvent (different event_type and
attributes, so different ids by content-addressing), but both events
derived_from the identical root E1 -- two different "representations" of
the same underlying evidence.

Structurally the minimal single-hop case (not a diamond or fan): tests
whether recursive resolution still adds value even when there is no
chain-length or branch-topology signal at all, only the choice of which
event a single hop happens to cite.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-redundant-representations-01"
FIXTURE_CLASS = "REDUNDANT_REPRESENTATIONS"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Two parallel single-hop A-D relationships. 'login' cites NormalizedEvent "
        "EvLogin (event_type='login_record', derived_from=(E1,)). 'session' cites "
        "NormalizedEvent EvSession (event_type='session_record', derived_from=(E1,)). "
        "Different event_type -> different ids -> same root E1."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="login",
            direct_reference_labels=frozenset({"EvLogin"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="session",
            direct_reference_labels=frozenset({"EvSession"}),
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
        "Minimal single-hop analogue of DIRECT_DIFFERENT_SHARED_ROOT: no "
        "diamond, no fan, no multi-hop chain -- the discriminator here is purely "
        "'which of two differently-typed normalization records was chosen to "
        "represent the same source evidence,' a realistic re-normalization "
        "scenario (e.g. one ingest adapter tags a login differently from "
        "another that also derives from the same raw log). Baseline 2 sees 2 "
        "distinct event ids and wrongly implies independence; Witnessgraph "
        "correctly reports the shared root."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/redundant-representations-01/E1")
    g.chained_event("EvLogin", event_type="login_record", derived_from_labels=("E1",))
    g.chained_event("EvSession", event_type="session_record", derived_from_labels=("E1",))
    g.edge("A", "D", ("EvLogin",))
    g.edge("A", "D", ("EvSession",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
