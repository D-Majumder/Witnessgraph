"""Adapts all 8 V1 WG-Bench fixtures (``research.wg_bench.fixtures``,
unchanged, unmodified, still the historical V1 benchmark) into V2's
``FixtureV2``/``GroundTruthV2`` shape, so V2's runner can evaluate them
side by side with the 7 new V2-only fixtures under all four methods.

Every V1 fixture's graph is built exclusively with
``research.wg_bench.graph_builder.FixtureGraphBuilder`` -- there is no
``NormalizedEvent`` indirection anywhere in a V1 fixture, every
``Relationship.derived_from`` id names an ``EvidenceItem`` directly. That
means, for every V1 fixture, the *direct* reference set and the *root*
evidence set are identical by construction: this adapter sets
``direct_reference_labels == root_evidence_labels`` for every expected
chain, never invents a distinction V1's fixtures do not actually contain.
This is itself an important, honest part of V2's results (see
docs/research/wg-bench.md's V2 section): Baseline 2 cannot be
distinguished from Witnessgraph on any V1 fixture, precisely because none
of them exercise multi-level lineage -- only the 7 new fixtures do.
"""

from __future__ import annotations

from collections.abc import Callable

from research.wg_bench.fixtures import (
    byte_distinct_same_source,
    disjoint_multi_evidence,
    disjoint_roots,
    identical_root_sets,
    partial_overlap,
    path_count_deception,
    shared_root,
    single_path,
)
from research.wg_bench.model import BuiltFixture, Fixture, GroundTruth
from research.wg_bench.v2.model import BuiltFixtureV2, ExpectedChainV2, FixtureV2, GroundTruthV2
from witnessgraph.store.case import Case

_V1_MODULES = (
    single_path,
    shared_root,
    disjoint_roots,
    identical_root_sets,
    partial_overlap,
    byte_distinct_same_source,
    path_count_deception,
    disjoint_multi_evidence,
)


def _v1_ground_truth_to_v2(gt: GroundTruth) -> GroundTruthV2:
    expected_chains = tuple(
        ExpectedChainV2(
            label=chain.label,
            direct_reference_labels=chain.root_evidence_labels,
            root_evidence_labels=chain.root_evidence_labels,
        )
        for chain in gt.expected_chains
    )
    conceptual_source_groups: tuple[frozenset[str], ...] | None = None
    if gt.fixture_class == "BYTE_DISTINCT_SAME_SOURCE":
        # Independently declared benchmark metadata (never a production
        # inference, see GroundTruthV2's docstring): both chains are
        # judged, by the same fixture author, to represent one real-world
        # source record despite disjoint root evidence ids.
        conceptual_source_groups = (frozenset(c.label for c in gt.expected_chains),)
    return GroundTruthV2(
        fixture_id=gt.fixture_id,
        fixture_class=gt.fixture_class,
        description=gt.description,
        expected_shortest_path_count=gt.expected_shortest_path_count,
        expected_chains=expected_chains,
        direct_sets_disjoint=gt.root_sets_disjoint,
        root_sets_disjoint=gt.root_sets_disjoint,
        root_sets_partial_overlap=gt.root_sets_partial_overlap,
        is_adversarial=gt.is_adversarial,
        conceptual_source_groups=conceptual_source_groups,
        known_limitation=gt.known_limitation,
        notes=gt.notes + " [V1 fixture, retained unchanged under V2 evaluation.]",
    )


def _v1_build_to_v2(v1_build: Fixture) -> Callable[[Case], BuiltFixtureV2]:
    def build(case: Case) -> BuiltFixtureV2:
        built: BuiltFixture = v1_build.build(case)
        return BuiltFixtureV2(
            source_entity_id=built.source_entity_id,
            target_entity_id=built.target_entity_id,
            evidence_by_label=built.evidence_by_label,
            event_by_label={},
        )

    return build


def all_v1_fixtures_as_v2() -> tuple[FixtureV2, ...]:
    fixtures = []
    for module in _V1_MODULES:
        v1_fixture = Fixture(ground_truth=module.GROUND_TRUTH, build=module.build)
        fixtures.append(
            FixtureV2(
                ground_truth=_v1_ground_truth_to_v2(v1_fixture.ground_truth),
                build=_v1_build_to_v2(v1_fixture),
            )
        )
    return tuple(fixtures)
