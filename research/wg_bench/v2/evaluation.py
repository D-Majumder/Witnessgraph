"""Runs one WG-Bench V2 fixture through all four methods -- Baseline 0
(path-count-only, V1, unchanged), Baseline 1 (path-structure), Baseline 2
(direct evidence-reference), and Witnessgraph's actual, unmodified
``find_all_shortest_paths``/``analyze_paths_evidence_overlap`` -- and
compares all four against the fixture's independently-authored ground
truth.

Every method's binary "does this imply the connection is corroborated by
independent evidence" reading is scored against the SAME target
question: the fixture's ground-truth ``root_sets_disjoint`` (whether
every pair of the fixture's *intended* chains' root evidence sets is
disjoint) -- this is what makes the four methods' results directly,
fairly comparable to each other, and is the operational form of V2's
central research question (see docs/research/wg-bench.md's V2 section).

This module never modifies, tunes, or works around
``correlate.graph.analyze_paths_evidence_overlap`` or
``find_all_shortest_paths`` -- it only calls them, through their ordinary
public API, exactly as any other caller would.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from research.wg_bench import baseline as baseline0
from research.wg_bench.v2 import baseline1, baseline2
from research.wg_bench.v2.model import BuiltFixtureV2, FixtureV2
from witnessgraph.core.ids import canonical_json_bytes
from witnessgraph.correlate.graph import (
    DEFAULT_PATH_MAX_DEPTH,
    DEFAULT_PATHS_LIMIT,
    all_shortest_paths_result_to_json,
    analyze_paths_evidence_overlap,
    find_all_shortest_paths,
    paths_evidence_overlap_to_json,
)
from witnessgraph.store.case import Case

_PROVENANCE_LABELS: dict[bool | None, str] = {
    True: "independent",
    False: "not_independent",
    None: "not_applicable",
}


@dataclass(frozen=True)
class _RunOutcome:
    built: BuiltFixtureV2
    path_count: int
    #: Order-independent multiset of each chain's own direct-reference id set.
    direct_sets: tuple[tuple[str, ...], ...]
    #: Order-independent multiset of each chain's own root-evidence id set.
    root_sets: tuple[tuple[str, ...], ...]
    baseline0_classification: str
    baseline1_classification: str
    baseline2_classification: str
    fully_evidence_independent: bool | None
    shared_evidence_ids: tuple[str, ...]
    manifest_hash: str
    canonical_bytes: bytes


def _run_once(fixture: FixtureV2, case_dir: Path) -> _RunOutcome:
    case = Case.create(case_dir)
    try:
        built = fixture.build(case)
        result = find_all_shortest_paths(
            case.store,
            built.source_entity_id,
            built.target_entity_id,
            max_depth=DEFAULT_PATH_MAX_DEPTH,
            limit=DEFAULT_PATHS_LIMIT,
        )
        overlap = analyze_paths_evidence_overlap(case.store, result)
        manifest = case.compute_manifest()
        doc = {
            "paths": all_shortest_paths_result_to_json(result),
            "evidence_independence": paths_evidence_overlap_to_json(overlap),
        }
        direct_sets = tuple(
            sorted(
                tuple(sorted(baseline2.chain_direct_reference_ids(chain))) for chain in result.paths
            )
        )
        root_sets = tuple(sorted(tuple(sorted(c.root_evidence_ids)) for c in overlap.chains))
        return _RunOutcome(
            built=built,
            path_count=len(result.paths),
            direct_sets=direct_sets,
            root_sets=root_sets,
            baseline0_classification=baseline0.classify_by_path_count(len(result.paths)),
            baseline1_classification=baseline1.classify_by_structure(result.paths),
            baseline2_classification=baseline2.classify_by_direct_references(result.paths),
            fully_evidence_independent=overlap.fully_evidence_independent,
            shared_evidence_ids=overlap.shared_evidence_ids,
            manifest_hash=manifest.manifest_hash,
            canonical_bytes=canonical_json_bytes(doc),
        )
    finally:
        case.close()


@dataclass(frozen=True)
class FixtureEvaluationV2:
    fixture_id: str
    fixture_class: str
    is_adversarial: bool
    known_limitation: str | None
    conceptual_source_groups: tuple[frozenset[str], ...] | None

    expected_shortest_path_count: int
    actual_shortest_path_count: int
    path_count_matches_expected: bool

    expected_direct_sets: tuple[tuple[str, ...], ...]
    actual_direct_sets: tuple[tuple[str, ...], ...]
    direct_sets_match_expected: bool

    expected_root_sets: tuple[tuple[str, ...], ...]
    actual_root_sets: tuple[tuple[str, ...], ...]
    root_sets_match_expected: bool

    ground_truth_direct_sets_disjoint: bool | None
    ground_truth_root_sets_disjoint: bool | None
    ground_truth_root_sets_partial_overlap: bool
    ground_truth_binary_applicable: bool

    #: {"baseline0": ..., "baseline1": ..., "baseline2": ..., "witnessgraph": ...}
    predicted_independent: dict[str, bool | None]
    #: Same keys: True iff that method's implied-independence reading is
    #: wrong relative to ground truth root_sets_disjoint, restricted to
    #: binary-applicable fixtures -- the precise, uniform definition of
    #: "false corroboration" V2 measures for every method identically.
    false_corroboration: dict[str, bool]
    #: Same keys: None when not binary-applicable, else whether the
    #: method's predicted_independent matches ground truth exactly.
    classification_correct: dict[str, bool | None]

    deterministic_replay_ok: bool
    manifest_hash_run_1: str
    manifest_hash_run_2: str


def evaluate_fixture(fixture: FixtureV2) -> FixtureEvaluationV2:
    gt = fixture.ground_truth
    with (
        tempfile.TemporaryDirectory(prefix=f"wgbenchv2-{gt.fixture_id}-1-") as d1,
        tempfile.TemporaryDirectory(prefix=f"wgbenchv2-{gt.fixture_id}-2-") as d2,
    ):
        run1 = _run_once(fixture, Path(d1) / "case")
        run2 = _run_once(fixture, Path(d2) / "case")

    expected_direct_sets = tuple(
        sorted(
            tuple(
                sorted(
                    run1.built.resolve_ref_label(label) for label in chain.direct_reference_labels
                )
            )
            for chain in gt.expected_chains
        )
    )
    expected_root_sets = tuple(
        sorted(
            tuple(
                sorted(run1.built.evidence_by_label[label] for label in chain.root_evidence_labels)
            )
            for chain in gt.expected_chains
        )
    )

    deterministic_replay_ok = (
        run1.manifest_hash == run2.manifest_hash
        and run1.canonical_bytes == run2.canonical_bytes
        and run1.path_count == run2.path_count
        and run1.root_sets == run2.root_sets
        and run1.direct_sets == run2.direct_sets
    )

    binary_applicable = gt.root_sets_disjoint is not None

    predicted_independent: dict[str, bool | None] = {
        "baseline0": baseline0.implies_independent_corroboration(run1.baseline0_classification),
        "baseline1": baseline1.implies_independent_corroboration(run1.baseline1_classification),
        "baseline2": baseline2.implies_independent_corroboration(run1.baseline2_classification),
        "witnessgraph": run1.fully_evidence_independent,
    }

    false_corroboration: dict[str, bool] = {}
    classification_correct: dict[str, bool | None] = {}
    for method, predicted in predicted_independent.items():
        false_corroboration[method] = bool(
            bool(predicted) and binary_applicable and gt.root_sets_disjoint is False
        )
        classification_correct[method] = (
            (predicted == gt.root_sets_disjoint) if binary_applicable else None
        )

    return FixtureEvaluationV2(
        fixture_id=gt.fixture_id,
        fixture_class=gt.fixture_class,
        is_adversarial=gt.is_adversarial,
        known_limitation=gt.known_limitation,
        conceptual_source_groups=gt.conceptual_source_groups,
        expected_shortest_path_count=gt.expected_shortest_path_count,
        actual_shortest_path_count=run1.path_count,
        path_count_matches_expected=(run1.path_count == gt.expected_shortest_path_count),
        expected_direct_sets=expected_direct_sets,
        actual_direct_sets=run1.direct_sets,
        direct_sets_match_expected=(run1.direct_sets == expected_direct_sets),
        expected_root_sets=expected_root_sets,
        actual_root_sets=run1.root_sets,
        root_sets_match_expected=(run1.root_sets == expected_root_sets),
        ground_truth_direct_sets_disjoint=gt.direct_sets_disjoint,
        ground_truth_root_sets_disjoint=gt.root_sets_disjoint,
        ground_truth_root_sets_partial_overlap=gt.root_sets_partial_overlap,
        ground_truth_binary_applicable=binary_applicable,
        predicted_independent=predicted_independent,
        false_corroboration=false_corroboration,
        classification_correct=classification_correct,
        deterministic_replay_ok=deterministic_replay_ok,
        manifest_hash_run_1=run1.manifest_hash,
        manifest_hash_run_2=run2.manifest_hash,
    )
