"""V3 SAME_SOURCE_DISJOINT_ROOT (adversarial): an independently-authored
retest of the byte-distinct/same-source limitation V1's
BYTE_DISTINCT_SAME_SOURCE fixture first demonstrated, using a different
concrete narrative (two independently re-encoded photographs of one
physical scene, not V1's "JSON export with/without a trailing newline")
and a different topology (two parallel 1-hop A-D relationships, not
V1's single-hop-pair-of-entities shape) -- see
docs/research/adversarial-contribution-review.md and
docs/research/wg-bench.md V1 section 11 for the original finding this
retests.

The fixture's own ground truth (conceptual_source_groups) declares, as
benchmark metadata only, that the two byte-distinct EvidenceItems here
represent the SAME real-world source (one physical photograph, exported
twice with different embedded metadata) -- a claim never fed back into
Witnessgraph and never derivable from its output.
"""

from __future__ import annotations

from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, GroundTruthV2
from research.wg_bench.v3.graph_builder import FixtureGraphBuilderV3
from witnessgraph.store.case import Case

FIXTURE_ID = "v3-same-source-disjoint-root-01"
FIXTURE_CLASS = "SAME_SOURCE_DISJOINT_ROOT"

GROUND_TRUTH = GroundTruthV2(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Two parallel 1-hop A-D relationships, each citing its own directly-"
        "referenced EvidenceItem. E1 and E2 are two BYTE-DISTINCT JPEG payloads "
        "(different embedded capture-device metadata blocks) that the fixture's "
        "independently-authored ground truth declares represent one physical "
        "photograph, exported twice by two different devices/tools."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChainV2(
            label="export-a",
            direct_reference_labels=frozenset({"E1"}),
            root_evidence_labels=frozenset({"E1"}),
        ),
        ExpectedChainV2(
            label="export-b",
            direct_reference_labels=frozenset({"E2"}),
            root_evidence_labels=frozenset({"E2"}),
        ),
    ),
    direct_sets_disjoint=True,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=True,
    conceptual_source_groups=(frozenset({"export-a", "export-b"}),),
    known_limitation=(
        "root_sets_disjoint=True is the CORRECT provenance-level answer (E1 and "
        "E2 are genuinely different content hashes) -- neither Baseline 2 nor "
        "Witnessgraph is wrong here. The limitation is that 'provenance-disjoint' "
        "is silently read as 'independently corroborating' by any consumer who "
        "does not separately know, from outside Witnessgraph entirely, that "
        "these two records are re-exports of one physical source."
    ),
    notes=(
        "Independently-constructed retest of V1's BYTE_DISTINCT_SAME_SOURCE "
        "finding with a different narrative and topology, per V3's mandate not "
        "to merely permute ids in an existing fixture. Both Baseline 2 and "
        "Witnessgraph correctly agree the roots are provenance-disjoint -- this "
        "is reported in V3's adversarial group, never counted as a "
        "classification error against either method."
    ),
)


def build(case: Case) -> BuiltFixtureV2:
    g = FixtureGraphBuilderV3(case)
    g.evidence(
        "E1",
        b'{"jpeg_stub":"scene-001","device_meta":"CameraModel=DeviceA;ISO=200"}',
    )
    g.evidence(
        "E2",
        b'{"jpeg_stub":"scene-001","device_meta":"CameraModel=DeviceB;ISO=200"}',
    )
    g.edge("A", "D", ("E1",))
    g.edge("A", "D", ("E2",))
    return BuiltFixtureV2(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
        event_by_label=g.event_by_label,
    )
