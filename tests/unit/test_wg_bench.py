"""Tests for the WG-Bench research benchmark infrastructure itself (not
Witnessgraph production code) -- see docs/research/wg-bench.md.

These tests hold two kinds of invariant:
  1. every fixture's own hand-authored ground truth is internally
     consistent, and its ``build()`` function actually produces that
     graph;
  2. the evaluation/metrics machinery computes exactly the documented
     formulas.

They deliberately assert discrete integer/boolean facts (path counts,
set memberships, confusion-matrix counts), never a blended float score,
so that a future accidental change to ``correlate.graph`` shows up here
as an unambiguous failure rather than as a shift in some aggregate
percentage that would need human interpretation.
"""

from __future__ import annotations

import pytest

from research.wg_bench import baseline
from research.wg_bench.evaluation import evaluate_fixture
from research.wg_bench.fixtures import all_fixtures
from research.wg_bench.metrics import ConfusionMatrix, compute_metrics
from research.wg_bench.model import Fixture
from research.wg_bench.runner import run_benchmark, to_json_document
from witnessgraph.core.ids import canonical_json_bytes

_ALL_FIXTURES = all_fixtures()
_EXPECTED_CLASSES = {
    "SINGLE_PATH",
    "SHARED_ROOT",
    "DISJOINT_ROOTS",
    "IDENTICAL_ROOT_SETS",
    "PARTIAL_OVERLAP",
    "BYTE_DISTINCT_SAME_SOURCE",
    "PATH_COUNT_DECEPTION",
    "DISJOINT_MULTI_EVIDENCE",
}


def _fixture(fixture_id: str) -> Fixture:
    return next(fx for fx in _ALL_FIXTURES if fx.ground_truth.fixture_id == fixture_id)


# -- baseline -----------------------------------------------------------------


def test_baseline_classifies_zero_and_one_path_as_no_or_single_path() -> None:
    assert baseline.classify_by_path_count(0) == baseline.NO_OR_SINGLE_PATH
    assert baseline.classify_by_path_count(1) == baseline.NO_OR_SINGLE_PATH


def test_baseline_classifies_two_or_more_paths_as_multiple_paths() -> None:
    assert baseline.classify_by_path_count(2) == baseline.MULTIPLE_PATHS
    assert baseline.classify_by_path_count(8) == baseline.MULTIPLE_PATHS


def test_baseline_rejects_negative_path_count() -> None:
    with pytest.raises(ValueError, match="path_count"):
        baseline.classify_by_path_count(-1)


def test_baseline_implies_independent_corroboration_only_for_multiple_paths() -> None:
    assert baseline.implies_independent_corroboration(baseline.MULTIPLE_PATHS) is True
    assert baseline.implies_independent_corroboration(baseline.NO_OR_SINGLE_PATH) is False


# -- fixture registry -----------------------------------------------------------------


def test_registry_has_exactly_the_eight_taxonomy_classes() -> None:
    assert len(_ALL_FIXTURES) == 8
    classes = {fx.ground_truth.fixture_class for fx in _ALL_FIXTURES}
    assert classes == _EXPECTED_CLASSES
    ids = [fx.ground_truth.fixture_id for fx in _ALL_FIXTURES]
    assert len(ids) == len(set(ids))  # every fixture id is unique


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=lambda fx: fx.ground_truth.fixture_id)
def test_fixture_build_matches_its_own_ground_truth(fixture: Fixture) -> None:
    """Each fixture's ``build()`` graph must actually match the path
    count and root-evidence sets its own hand-authored ground truth
    declares -- "does the fixture builder do what its author said it
    does," independent of whether Witnessgraph's analysis agrees."""
    evaluation = evaluate_fixture(fixture)
    assert evaluation.path_count_matches_expected, evaluation
    assert evaluation.root_sets_match_expected, evaluation


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=lambda fx: fx.ground_truth.fixture_id)
def test_witnessgraph_matches_its_documented_expected_classification(fixture: Fixture) -> None:
    """Pins down exactly what ``analyze_paths_evidence_overlap`` is
    documented (in each fixture's ground truth) to return today. A
    regression here means either the fixture's documentation is stale or
    ``correlate.graph`` changed -- either way it must be investigated,
    never silently absorbed into a shifted aggregate metric."""
    evaluation = evaluate_fixture(fixture)
    assert evaluation.provenance_matches_expected, evaluation


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=lambda fx: fx.ground_truth.fixture_id)
def test_fixture_is_deterministic_across_independent_builds(fixture: Fixture) -> None:
    """H2: two independent builds of the same fixture must produce
    byte-identical manifests and analysis JSON."""
    evaluation = evaluate_fixture(fixture)
    assert evaluation.deterministic_replay_ok, evaluation
    assert evaluation.manifest_hash_run_1 == evaluation.manifest_hash_run_2


# -- known, expected behavior of specific fixtures ---------------------------


def test_shared_root_fixture_is_a_baseline_false_corroboration_case() -> None:
    evaluation = evaluate_fixture(_fixture("shared-root-01"))
    assert evaluation.baseline_false_corroboration is True
    assert evaluation.witnessgraph_false_corroboration is False


def test_disjoint_roots_fixture_is_not_a_false_corroboration_case_for_either_method() -> None:
    evaluation = evaluate_fixture(_fixture("disjoint-roots-01"))
    assert evaluation.baseline_false_corroboration is False
    assert evaluation.witnessgraph_false_corroboration is False


def test_byte_distinct_same_source_fixture_is_flagged_adversarial_not_hidden() -> None:
    evaluation = evaluate_fixture(_fixture("byte-distinct-same-source-01"))
    assert evaluation.is_adversarial is True
    assert evaluation.known_limitation is not None
    # Witnessgraph mechanically reports independence at the provenance
    # level -- documented as correct-per-its-own-model, not a bug.
    assert evaluation.witnessgraph_fully_evidence_independent is True


def test_partial_overlap_fixture_masks_two_of_three_disjoint_pairs() -> None:
    """H3: the top-level boolean loses information for partial overlap.
    Path A/{E1,E2}, B/{E2,E3}, C/{E4}: (A,C) and (B,C) are genuinely
    root-evidence-disjoint, but the single ``fully_evidence_independent``
    field is False because (A,B) share E2."""
    evaluation = evaluate_fixture(_fixture("partial-overlap-01"))
    assert evaluation.witnessgraph_fully_evidence_independent is False
    metrics = compute_metrics([evaluation])
    (finding,) = metrics.partial_overlap_findings
    assert finding.total_chain_pairs == 3
    assert finding.disjoint_pairs == 2
    assert finding.pairs_masked_by_boolean == 2


def test_path_count_deception_fixture_has_eight_paths_one_root() -> None:
    evaluation = evaluate_fixture(_fixture("path-count-deception-01"))
    assert evaluation.actual_shortest_path_count == 8
    assert evaluation.witnessgraph_fully_evidence_independent is False
    assert evaluation.baseline_false_corroboration is True


# -- metrics --------------------------------------------------------------


def test_confusion_matrix_ratios_on_synthetic_counts() -> None:
    cm = ConfusionMatrix(true_positive=3, false_positive=1, false_negative=1, true_negative=2)
    assert cm.total == 7
    assert cm.accuracy == pytest.approx(5 / 7)
    assert cm.precision == pytest.approx(3 / 4)
    assert cm.recall == pytest.approx(3 / 4)
    assert cm.false_positive_rate == pytest.approx(1 / 3)


def test_confusion_matrix_ratios_are_none_when_denominator_is_zero() -> None:
    cm = ConfusionMatrix(true_positive=0, false_positive=0, false_negative=0, true_negative=0)
    assert cm.total == 0
    assert cm.accuracy is None
    assert cm.precision is None
    assert cm.recall is None
    assert cm.false_positive_rate is None


def test_full_benchmark_run_produces_expected_groups() -> None:
    evaluations, metrics = run_benchmark()
    assert len(evaluations) == 8
    assert metrics.total_fixtures == 8
    assert metrics.all_ground_truth_matches is True
    assert metrics.all_deterministic_replay_ok is True
    # SHARED_ROOT, DISJOINT_ROOTS, IDENTICAL_ROOT_SETS, PATH_COUNT_DECEPTION,
    # DISJOINT_MULTI_EVIDENCE -- 5 binary-applicable, non-adversarial,
    # non-partial-overlap fixtures.
    assert len(metrics.binary.fixture_ids) == 5
    assert len(metrics.single_path.fixture_ids) == 1
    assert len(metrics.partial_overlap.fixture_ids) == 1
    assert len(metrics.adversarial.fixture_ids) == 1


def test_binary_group_witnessgraph_confusion_matrix_is_perfect() -> None:
    """Over the binary-applicable, non-adversarial, non-partial-overlap
    fixtures, Witnessgraph's own evidence-independence check must match
    ground truth on every one of them: 2 true disjoint-root fixtures, 3
    true shared/identical-root fixtures."""
    _, metrics = run_benchmark()
    cm = metrics.binary.witnessgraph_confusion
    counts = (cm.true_positive, cm.false_positive, cm.false_negative, cm.true_negative)
    assert counts == (2, 0, 0, 3)
    assert cm.accuracy == 1.0
    assert cm.false_positive_rate == 0.0


def test_binary_group_baseline_produces_false_corroboration_on_every_non_independent_fixture() -> (
    None
):
    """The path-count-only baseline treats every one of these 5 fixtures
    as "multiple_paths" (each has >= 2 expected chains by construction),
    which naively reads as implied independent corroboration for all 5
    -- 3 of which are ground-truth NOT independent. That mismatch is
    exactly the false-corroboration failure mode this benchmark
    measures; see docs/research/wg-bench.md's threats-to-validity
    section for why 100% here is partly a function of every binary
    fixture being deliberately constructed to have path multiplicity."""
    _, metrics = run_benchmark()
    cm = metrics.binary.baseline_confusion
    counts = (cm.true_positive, cm.false_positive, cm.false_negative, cm.true_negative)
    assert counts == (2, 3, 0, 0)
    assert cm.false_positive_rate == 1.0
    assert metrics.binary.baseline_false_corroboration_count == 3
    assert metrics.binary.witnessgraph_false_corroboration_count == 0


def test_json_document_is_canonical_and_deterministic() -> None:
    doc1 = to_json_document(*run_benchmark())
    doc2 = to_json_document(*run_benchmark())
    assert canonical_json_bytes(doc1) == canonical_json_bytes(doc2)
