"""V3 BYTE_IDENTICAL_DIFFERENT_SOURCE (adversarial): the mirror image of
SAME_SOURCE_DISJOINT_ROOT / V1's BYTE_DISTINCT_SAME_SOURCE.

There, byte-DISTINCT evidence was declared (as benchmark metadata) to
represent the SAME real-world source, showing root-disjointness does not
imply epistemic independence. Here, byte-IDENTICAL evidence (the two
chains cite the literal same EvidenceItem id, since content-addressing
deduplicates identical bytes -- Witnessgraph cannot represent
"byte-identical, different EvidenceItem" any more than SHA-256 can be
made to collide on demand) is declared, as benchmark metadata only, to
represent two DIFFERENT real-world sources (e.g. two witnesses who
independently filled out the same boilerplate incident-report form with
identical answers by coincidence). This tests the opposite direction of
the same boundary: root-SHARED does not imply epistemic non-independence
either.

Attacks assumption 7 ("content-addressed identity captures source
independence") from the opposite side.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-byte-identical-different-source-01"
FIXTURE_CLASS = "BYTE_IDENTICAL_DIFFERENT_SOURCE"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Two parallel 1-hop A-D relationships both citing the SAME literal "
        "EvidenceItem E1 (identical boilerplate incident-report bytes). The "
        "fixture's independently-authored ground truth declares these two "
        "citations represent two DIFFERENT real-world submissions (two "
        "witnesses, coincidentally identical answers), not one duplicated "
        "record."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="witness-1",
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="witness-2",
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
    ),
    direct_sets_disjoint=False,
    root_sets_disjoint=False,
    root_sets_partial_overlap=False,
    is_adversarial=True,
    conceptual_source_groups=None,
    known_limitation=(
        "fully_evidence_independent=False is the CORRECT provenance-level "
        "answer (both chains genuinely cite the one stored EvidenceItem) -- "
        "neither Baseline 2 nor Witnessgraph is wrong. The limitation runs the "
        "opposite direction from BYTE_DISTINCT_SAME_SOURCE: two witnesses who "
        "coincidentally produce byte-identical accounts are collapsed, by "
        "content-addressing itself, into one EvidenceItem before this analysis "
        "ever runs, so 'shared root' cannot, by construction, distinguish "
        "'the same record cited twice' from 'two independent records that "
        "happen to be byte-identical.' No production code change is implied -- "
        "content-addressed deduplication is deliberate (DESIGN.md principle 1) "
        "and happens at ingest time, upstream of this benchmark entirely."
    ),
    notes=(
        "Neither Baseline 2 nor Witnessgraph can be 'more correct' here: this "
        "fixture demonstrates a limitation that exists before either method's "
        "analysis begins, at evidence ingestion. Included specifically to "
        "satisfy V3's mandate to attack assumption 7 from the direction V1/V2 "
        "never tested (false shared-root, not only false disjoint-root)."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence(
        "E1",
        b'{"form":"incident-report-v1","q1":"yes","q2":"no","q3":"unsure"}',
    )
    # Distinct relationship_type differentiates the two relationship ids
    # (both otherwise identical: same source/target/derived_from) --
    # standing in for two independently-submitted witness reports that
    # both happen to cite the one deduplicated EvidenceItem.
    g.edge("A", "D", ("E1",), relationship_type="witness_1_report")
    g.edge("A", "D", ("E1",), relationship_type="witness_2_report")
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
