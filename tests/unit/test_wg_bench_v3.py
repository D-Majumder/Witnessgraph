"""Tests for WG-Bench V3 (``research.wg_bench.v3``) -- independent-
adversarial validation research benchmark infrastructure, not
Witnessgraph production code. See ``docs/research/wg-bench.md``'s V3
section.

Mirrors V1/V2's testing discipline: assert discrete integer/boolean
facts, never a blended float score. Assertions below encode the actual,
already-run V3 results (some favorable to Witnessgraph, some not, by
design -- see the module docstrings under ``research/wg_bench/v3/fixtures/``)
so a future accidental change to ``correlate.graph`` shows up here as an
unambiguous failure either direction.
"""

from __future__ import annotations

import pytest

from research.wg_bench.v2.evaluation import evaluate_fixture
from research.wg_bench.v3.fixtures import all_fixtures
from research.wg_bench.v3.metrics import compute_discriminator_analysis
from research.wg_bench.v3.runner import run_benchmark, to_json_document
from witnessgraph.core.ids import canonical_json_bytes

_ALL_FIXTURES = all_fixtures()
_EXPECTED_CLASSES = {
    "MULTI_LEVEL_LINEAGE",
    "CROSS_BRANCH_SHARED_ROOT",
    "CROSS_BRANCH_DISJOINT_ROOT",
    "MIXED_ROOT_DEPTH",
    "HIGH_MULTIPLICITY_COLLAPSE",
    "HIGH_MULTIPLICITY_DISJOINT",
    "PARTIAL_OVERLAP_COMPLEX",
    "REDUNDANT_REPRESENTATIONS",
    "DIRECT_REFERENCE_DECOY",
    "DIRECT_REFERENCE_CONVERGENCE",
    "SAME_SOURCE_DISJOINT_ROOT",
    "BYTE_IDENTICAL_DIFFERENT_SOURCE",
}


def _fixture(fixture_id: str):  # noqa: ANN202
    return next(fx for fx in _ALL_FIXTURES if fx.ground_truth.fixture_id == fixture_id)


# -- registry -----------------------------------------------------------------


def test_registry_has_all_twelve_fixture_classes() -> None:
    assert len(_ALL_FIXTURES) == 12
    classes = {fx.ground_truth.fixture_class for fx in _ALL_FIXTURES}
    assert classes == _EXPECTED_CLASSES
    ids = [fx.ground_truth.fixture_id for fx in _ALL_FIXTURES]
    assert len(ids) == len(set(ids))
    # V3 fixture ids must never collide with V1/V2 ids -- independent namespace.
    assert all(fid.startswith("v3-") for fid in ids)


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=lambda fx: fx.ground_truth.fixture_id)
def test_fixture_build_matches_its_own_ground_truth(fixture) -> None:  # noqa: ANN001
    evaluation = evaluate_fixture(fixture)
    assert evaluation.path_count_matches_expected, evaluation
    assert evaluation.root_sets_match_expected, evaluation
    assert evaluation.direct_sets_match_expected, evaluation


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=lambda fx: fx.ground_truth.fixture_id)
def test_fixture_is_deterministic_across_independent_builds(fixture) -> None:  # noqa: ANN001
    evaluation = evaluate_fixture(fixture)
    assert evaluation.deterministic_replay_ok, evaluation
    assert evaluation.manifest_hash_run_1 == evaluation.manifest_hash_run_2


# -- deliberately Witnessgraph-favorable discriminators ------------------------


@pytest.mark.parametrize(
    "fixture_id",
    [
        "v3-multi-level-lineage-01",
        "v3-mixed-root-depth-01",
        "v3-high-multiplicity-collapse-01",
        "v3-redundant-representations-01",
        "v3-direct-reference-decoy-01",
    ],
)
def test_indirection_fixtures_fool_baseline2_not_witnessgraph(fixture_id: str) -> None:
    evaluation = evaluate_fixture(_fixture(fixture_id))
    assert evaluation.predicted_independent["baseline2"] is True
    assert evaluation.predicted_independent["witnessgraph"] is False
    assert evaluation.false_corroboration["baseline2"] is True
    assert evaluation.false_corroboration["witnessgraph"] is False


def test_direct_reference_convergence_fools_baseline2_the_opposite_direction() -> None:
    """The one V3 discriminator where Baseline 2's error is a FALSE
    NEGATIVE for independence (a shared dangling id), not a false
    positive -- the mirror-image failure mode from every other
    discriminator in this benchmark."""
    evaluation = evaluate_fixture(_fixture("v3-direct-reference-convergence-01"))
    assert evaluation.predicted_independent["baseline2"] is False
    assert evaluation.predicted_independent["witnessgraph"] is True
    # Each chain's resolved root is a single evidence id, and the two are
    # disjoint -- the dangling decoy id contributes to neither root set.
    assert len(evaluation.actual_root_sets) == 2
    (root_a,), (root_b,) = evaluation.actual_root_sets
    assert root_a != root_b
    assert set(evaluation.actual_root_sets[0]) & set(evaluation.actual_root_sets[1]) == set()


# -- deliberately NOT biased toward Witnessgraph --------------------------------


@pytest.mark.parametrize(
    "fixture_id",
    [
        "v3-cross-branch-shared-root-01",
        "v3-cross-branch-disjoint-root-01",
        "v3-high-multiplicity-disjoint-01",
        "v3-same-source-disjoint-root-01",
        "v3-byte-identical-different-source-01",
    ],
)
def test_no_indirection_fixtures_baseline2_ties_witnessgraph(fixture_id: str) -> None:
    """Fixtures with no NormalizedEvent indirection at all: Baseline 2 and
    Witnessgraph must agree exactly, since they read the identical
    information. Included so V3 does not only report Witnessgraph wins."""
    evaluation = evaluate_fixture(_fixture(fixture_id))
    assert (
        evaluation.predicted_independent["baseline2"]
        == evaluation.predicted_independent["witnessgraph"]
    )


def test_no_witnessgraph_errors_found_across_v3() -> None:
    """The adversarial search found no in-scope case where Witnessgraph's
    own verdict disagrees with independently-authored ground truth."""
    evaluations = [evaluate_fixture(fx) for fx in _ALL_FIXTURES]
    analysis = compute_discriminator_analysis(evaluations)
    assert analysis.witnessgraph_error_count == 0


# -- H3: partial-overlap information loss at a larger, independent scale -------


def test_partial_overlap_complex_masks_four_of_six_disjoint_pairs() -> None:
    from research.wg_bench.v2.metrics import compute_metrics

    evaluation = evaluate_fixture(_fixture("v3-partial-overlap-complex-01"))
    assert evaluation.predicted_independent["witnessgraph"] is False
    metrics = compute_metrics([evaluation])
    (finding,) = metrics.partial_overlap_findings
    assert finding.total_chain_pairs == 6
    assert finding.root_disjoint_pairs == 4
    assert finding.root_pairs_masked_by_boolean == 4
    assert finding.information_loss_rate == pytest.approx(4 / 6)
    # Because this fixture uses only direct references (no indirection),
    # Baseline 2's own boolean loses the identical pairwise information.
    assert finding.direct_pairs_masked_by_boolean == 4


# -- adversarial group: byte-distinct/byte-identical source limitations -------


def test_same_source_disjoint_root_records_conceptual_source_group() -> None:
    evaluation = evaluate_fixture(_fixture("v3-same-source-disjoint-root-01"))
    assert evaluation.is_adversarial is True
    assert evaluation.conceptual_source_groups is not None
    (group,) = evaluation.conceptual_source_groups
    assert group == frozenset({"export-a", "export-b"})
    # Provenance-level ground truth is disjoint -- neither method is "wrong."
    assert evaluation.ground_truth_root_sets_disjoint is True


def test_byte_identical_different_source_is_adversarial_and_not_a_method_error() -> None:
    evaluation = evaluate_fixture(_fixture("v3-byte-identical-different-source-01"))
    assert evaluation.is_adversarial is True
    assert evaluation.ground_truth_root_sets_disjoint is False
    assert evaluation.predicted_independent["witnessgraph"] is False
    assert evaluation.classification_correct["witnessgraph"] is True


# -- full benchmark run ---------------------------------------------------------


def test_full_benchmark_run_produces_expected_discriminator_counts() -> None:
    evaluations, metrics = run_benchmark()
    assert len(evaluations) == 12
    assert metrics.v2_style.total_fixtures == 12
    assert metrics.v2_style.all_ground_truth_matches is True
    assert metrics.v2_style.all_deterministic_replay_ok is True

    d = metrics.discriminator
    assert d.discriminator_count == 6
    assert d.correct_discriminator_count == 6
    assert d.baseline_equivalence_count == 6
    assert d.adversarial_defeat_count == 6
    assert d.witnessgraph_error_count == 0


def test_binary_group_witnessgraph_confusion_matrix_is_perfect() -> None:
    _, metrics = run_benchmark()
    cm = metrics.v2_style.binary.confusion["witnessgraph"]
    assert (cm.true_positive, cm.false_positive, cm.false_negative, cm.true_negative) == (
        3,
        0,
        0,
        6,
    )
    assert cm.false_positive_rate == 0.0


def test_binary_group_baseline2_still_beaten_on_v3_discriminators() -> None:
    _, metrics = run_benchmark()
    cm = metrics.v2_style.binary.confusion["baseline2"]
    assert (cm.true_positive, cm.false_positive, cm.false_negative, cm.true_negative) == (
        2,
        5,
        1,
        1,
    )


def test_json_document_is_canonical_and_deterministic() -> None:
    doc1 = to_json_document(*run_benchmark())
    doc2 = to_json_document(*run_benchmark())
    assert canonical_json_bytes(doc1) == canonical_json_bytes(doc2)
