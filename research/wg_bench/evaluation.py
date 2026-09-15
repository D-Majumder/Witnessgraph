"""Runs one WG-Bench fixture through both the path-count-only baseline
and Witnessgraph's actual, unmodified
``find_all_shortest_paths``/``analyze_paths_evidence_overlap``, and
compares both against the fixture's independently-authored ground
truth.

This module never modifies, tunes, or works around
``correlate.graph.analyze_paths_evidence_overlap`` -- it only calls it,
through its ordinary public API, exactly as any other caller (the CLI,
the API/service layer) would, and records what it returns.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from research.wg_bench import baseline
from research.wg_bench.model import BuiltFixture, Fixture
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

#: Maps `analyze_paths_evidence_overlap`'s `fully_evidence_independent`
#: (True / False / None) onto the same three-valued vocabulary
#: `GroundTruth.provenance_expected_classification` uses.
_PROVENANCE_LABELS: dict[bool | None, str] = {
    True: "independent",
    False: "not_independent",
    None: "not_applicable",
}


@dataclass(frozen=True)
class _RunOutcome:
    """One independent build-and-analyze run of a fixture."""

    built: BuiltFixture
    path_count: int
    #: One sorted tuple of sorted root-evidence ids per returned chain,
    #: the whole collection itself sorted -- an order-independent
    #: multiset representation, since chains are not otherwise labeled.
    root_sets: tuple[tuple[str, ...], ...]
    fully_evidence_independent: bool | None
    shared_evidence_ids: tuple[str, ...]
    manifest_hash: str
    canonical_bytes: bytes


def _run_once(fixture: Fixture, case_dir: Path) -> _RunOutcome:
    """Build ``fixture`` into a fresh ``Case`` at ``case_dir`` and run
    Witnessgraph's own, unmodified path/evidence-overlap analysis over
    it."""
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
        root_sets = tuple(sorted(tuple(sorted(c.root_evidence_ids)) for c in overlap.chains))
        return _RunOutcome(
            built=built,
            path_count=len(result.paths),
            root_sets=root_sets,
            fully_evidence_independent=overlap.fully_evidence_independent,
            shared_evidence_ids=overlap.shared_evidence_ids,
            manifest_hash=manifest.manifest_hash,
            canonical_bytes=canonical_json_bytes(doc),
        )
    finally:
        case.close()


@dataclass(frozen=True)
class FixtureEvaluation:
    """Everything WG-Bench records for one fixture: what was expected,
    what the baseline said, what Witnessgraph said, and whether each
    agreed with the independently-authored ground truth."""

    fixture_id: str
    fixture_class: str
    is_adversarial: bool
    known_limitation: str | None

    expected_shortest_path_count: int
    actual_shortest_path_count: int
    path_count_matches_expected: bool

    expected_root_sets: tuple[tuple[str, ...], ...]
    actual_root_sets: tuple[tuple[str, ...], ...]
    root_sets_match_expected: bool

    ground_truth_root_sets_identical: bool | None
    ground_truth_root_sets_disjoint: bool | None
    ground_truth_root_sets_partial_overlap: bool
    #: True iff `ground_truth_root_sets_disjoint` is not None -- i.e. a
    #: well-defined binary "root-evidence independent yes/no" question
    #: applies to this fixture at all.
    ground_truth_binary_applicable: bool

    baseline_classification: str
    baseline_expected_classification: str
    baseline_matches_expected: bool
    baseline_implies_independent_corroboration: bool
    #: True iff the baseline's implied-corroboration reading is wrong
    #: relative to ground truth, restricted to binary-applicable
    #: fixtures -- the precise operational definition of "false
    #: corroboration" this benchmark measures for the baseline.
    baseline_false_corroboration: bool

    witnessgraph_fully_evidence_independent: bool | None
    witnessgraph_shared_evidence_ids: tuple[str, ...]
    provenance_expected_classification: str
    provenance_matches_expected: bool
    #: Only meaningful when `ground_truth_binary_applicable` is True;
    #: None otherwise.
    witnessgraph_classification_correct: bool | None
    #: The same false-corroboration definition as
    #: `baseline_false_corroboration`, applied to Witnessgraph's own
    #: `fully_evidence_independent` verdict instead of the baseline.
    witnessgraph_false_corroboration: bool

    deterministic_replay_ok: bool
    manifest_hash_run_1: str
    manifest_hash_run_2: str


def evaluate_fixture(fixture: Fixture) -> FixtureEvaluation:
    """Build ``fixture`` twice, independently, run Witnessgraph's own
    analysis on each build, and compare both runs' results against each
    other (H2, determinism) and against ``fixture.ground_truth`` (H1/H3).
    """
    gt = fixture.ground_truth
    with (
        tempfile.TemporaryDirectory(prefix=f"wgbench-{gt.fixture_id}-1-") as d1,
        tempfile.TemporaryDirectory(prefix=f"wgbench-{gt.fixture_id}-2-") as d2,
    ):
        run1 = _run_once(fixture, Path(d1) / "case")
        run2 = _run_once(fixture, Path(d2) / "case")

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
    )

    baseline_classification = baseline.classify_by_path_count(run1.path_count)
    baseline_implies = baseline.implies_independent_corroboration(baseline_classification)
    binary_applicable = gt.root_sets_disjoint is not None

    baseline_false_corroboration = bool(
        baseline_implies and binary_applicable and gt.root_sets_disjoint is False
    )
    witnessgraph_false_corroboration = bool(
        run1.fully_evidence_independent is True
        and binary_applicable
        and gt.root_sets_disjoint is False
    )
    witnessgraph_classification_correct = (
        (run1.fully_evidence_independent == gt.root_sets_disjoint) if binary_applicable else None
    )

    provenance_actual_label = _PROVENANCE_LABELS[run1.fully_evidence_independent]

    return FixtureEvaluation(
        fixture_id=gt.fixture_id,
        fixture_class=gt.fixture_class,
        is_adversarial=gt.is_adversarial,
        known_limitation=gt.known_limitation,
        expected_shortest_path_count=gt.expected_shortest_path_count,
        actual_shortest_path_count=run1.path_count,
        path_count_matches_expected=(run1.path_count == gt.expected_shortest_path_count),
        expected_root_sets=expected_root_sets,
        actual_root_sets=run1.root_sets,
        root_sets_match_expected=(run1.root_sets == expected_root_sets),
        ground_truth_root_sets_identical=gt.root_sets_identical,
        ground_truth_root_sets_disjoint=gt.root_sets_disjoint,
        ground_truth_root_sets_partial_overlap=gt.root_sets_partial_overlap,
        ground_truth_binary_applicable=binary_applicable,
        baseline_classification=baseline_classification,
        baseline_expected_classification=gt.baseline_expected_classification,
        baseline_matches_expected=(baseline_classification == gt.baseline_expected_classification),
        baseline_implies_independent_corroboration=baseline_implies,
        baseline_false_corroboration=baseline_false_corroboration,
        witnessgraph_fully_evidence_independent=run1.fully_evidence_independent,
        witnessgraph_shared_evidence_ids=run1.shared_evidence_ids,
        provenance_expected_classification=gt.provenance_expected_classification,
        provenance_matches_expected=(
            provenance_actual_label == gt.provenance_expected_classification
        ),
        witnessgraph_classification_correct=witnessgraph_classification_correct,
        witnessgraph_false_corroboration=witnessgraph_false_corroboration,
        deterministic_replay_ok=deterministic_replay_ok,
        manifest_hash_run_1=run1.manifest_hash,
        manifest_hash_run_2=run2.manifest_hash,
    )
