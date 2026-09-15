"""V3 DIRECT_REFERENCE_CONVERGENCE: two parallel 1-hop A-D relationships,
each citing its own genuinely distinct root evidence (E1 / E2) PLUS a
shared *dangling* id ("decoy") that is never backed by any stored
EvidenceItem or NormalizedEvent.

This is the mirror image of every other V3/V2 discriminator: instead of
different direct ids masking a shared root, here a SHARED direct id
masks a genuinely disjoint (independent) case, because the shared id
resolves to nothing. Tests whether a direct-reference baseline can be
fooled the opposite direction -- false non-independence, not false
independence -- and whether Witnessgraph's resolver correctly treats a
dangling reference as contributing zero root evidence rather than
crashing or fabricating a root (see
``correlate.graph.resolve_evidence_ref``'s ``"not_found"`` handling and
``research.wg_bench.v3.graph_builder.dangling``).
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-direct-reference-convergence-01"
FIXTURE_CLASS = "DIRECT_REFERENCE_CONVERGENCE"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Two parallel 1-hop A-D relationships. Chain 'first' cites (E1, decoy); "
        "chain 'second' cites (E2, decoy), where 'decoy' is a syntactically "
        "valid id with no backing EvidenceItem/NormalizedEvent -- never written "
        "to the store."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="first",
            direct_reference_labels=frozenset({"E1", "decoy"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="second",
            direct_reference_labels=frozenset({"E2", "decoy"}),
            root_evidence_labels=frozenset({"E2"}),
        ),
    ),
    direct_sets_disjoint=False,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=False,
    conceptual_source_groups=None,
    known_limitation=None,
    notes=(
        "Baseline 2 sees direct sets {E1,decoy} and {E2,decoy} -- they share "
        "'decoy', so Baseline 2 classifies this as OVERLAPPING and wrongly "
        "implies NOT independent (a false negative for independence -- the "
        "opposite error direction from every other V3/V2 discriminator, which "
        "are all false positives for independence). Witnessgraph's "
        "_resolve_root_evidence_ids correctly resolves 'decoy' to the empty set "
        "(resolve_evidence_ref's 'not_found' kind, per its own documented "
        "contract) and reports the true, disjoint root sets {E1} and {E2} -- "
        "correctly independent. Also a legitimate section-8 probe: a dangling "
        "derived_from id is representable through the public model with no "
        "referential-integrity enforcement, and correlate.graph already "
        "documents handling it gracefully rather than crashing."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence("E1", b"wg-bench-v3/direct-reference-convergence-01/E1")
    g.evidence("E2", b"wg-bench-v3/direct-reference-convergence-01/E2")
    g.dangling("decoy")
    g.edge("A", "D", ("E1", "decoy"))
    g.edge("A", "D", ("E2", "decoy"))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
