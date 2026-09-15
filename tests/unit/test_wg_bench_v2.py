"""Tests for WG-Bench V2 (``research.wg_bench.v2``) -- research
benchmark infrastructure, not Witnessgraph production code. See
``docs/research/wg-bench.md``'s V2 section.

Mirrors V1's ``tests/unit/test_wg_bench.py`` testing discipline: assert
discrete integer/boolean facts (path counts, set memberships, confusion-
matrix counts), never a blended float score, so a future accidental
change to ``correlate.graph`` shows up here as an unambiguous failure.
"""

from __future__ import annotations

import pytest

from research.wg_bench.v2 import baseline1, baseline2
from research.wg_bench.v2.evaluation import evaluate_fixture
from research.wg_bench.v2.fixtures import all_fixtures
from research.wg_bench.v2.metrics import compute_metrics
from research.wg_bench.v2.model import FixtureV2
from research.wg_bench.v2.runner import run_benchmark, to_json_document
from witnessgraph.core.ids import canonical_json_bytes

_ALL_FIXTURES = all_fixtures()
_EXPECTED_V1_CLASSES = {
    "SINGLE_PATH",
    "SHARED_ROOT",
    "DISJOINT_ROOTS",
    "IDENTICAL_ROOT_SETS",
    "PARTIAL_OVERLAP",
    "BYTE_DISTINCT_SAME_SOURCE",
    "PATH_COUNT_DECEPTION",
    "DISJOINT_MULTI_EVIDENCE",
}
_EXPECTED_NEW_V2_CLASSES = {
    "DIRECT_DIFFERENT_SHARED_ROOT",
    "DIRECT_SAME_ROOT_DISJOINT",
    "MULTI_LEVEL_LINEAGE",
    "MIXED_DIRECT_DERIVED",
    "HIGH_PATH_SHARED_ROOT",
    "HIGH_PATH_DISJOINT_ROOT",
    "PARTIAL_MULTI_ROOT",
}


def _fixture(fixture_id: str) -> FixtureV2:
    return next(fx for fx in _ALL_FIXTURES if fx.ground_truth.fixture_id == fixture_id)


# -- registry -----------------------------------------------------------------


def test_registry_has_all_fifteen_fixture_classes() -> None:
    assert len(_ALL_FIXTURES) == 15
    classes = {fx.ground_truth.fixture_class for fx in _ALL_FIXTURES}
    assert classes == _EXPECTED_V1_CLASSES | _EXPECTED_NEW_V2_CLASSES
    ids = [fx.ground_truth.fixture_id for fx in _ALL_FIXTURES]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=lambda fx: fx.ground_truth.fixture_id)
def test_fixture_build_matches_its_own_ground_truth(fixture: FixtureV2) -> None:
    evaluation = evaluate_fixture(fixture)
    assert evaluation.path_count_matches_expected, evaluation
    assert evaluation.root_sets_match_expected, evaluation
    assert evaluation.direct_sets_match_expected, evaluation


@pytest.mark.parametrize("fixture", _ALL_FIXTURES, ids=lambda fx: fx.ground_truth.fixture_id)
def test_fixture_is_deterministic_across_independent_builds(fixture: FixtureV2) -> None:
    evaluation = evaluate_fixture(fixture)
    assert evaluation.deterministic_replay_ok, evaluation
    assert evaluation.manifest_hash_run_1 == evaluation.manifest_hash_run_2


# -- baseline 1 (structural) ---------------------------------------------------


def test_baseline1_not_applicable_below_two_chains() -> None:
    assert baseline1.classify_by_structure(()) == baseline1.NOT_APPLICABLE
    assert baseline1.implies_independent_corroboration(baseline1.NOT_APPLICABLE) is False


def test_baseline1_never_inspects_derived_from() -> None:
    """Baseline 1 must be blind to evidence references entirely -- its
    classification depends only on entity/relationship ids. Checked
    against the function bodies (not the module's own documentation,
    which legitimately discusses derived_from to explain the design)."""
    import inspect

    for fn in (
        baseline1.chain_entity_ids,
        baseline1.chain_relationship_ids,
        baseline1.pairwise_structural_overlap,
        baseline1.classify_by_structure,
    ):
        assert "derived_from" not in inspect.getsource(fn), fn.__name__


# -- baseline 2 (direct evidence-reference) ------------------------------------


def test_baseline2_not_applicable_below_two_chains() -> None:
    assert baseline2.classify_by_direct_references(()) == baseline2.NOT_APPLICABLE
    assert baseline2.implies_independent_corroboration(baseline2.NOT_APPLICABLE) is False


def test_baseline2_never_calls_analyze_paths_evidence_overlap() -> None:
    """``baseline2`` must never import Witnessgraph's actual evidence-
    overlap resolver -- checked against the module's imports, not its
    documentation (which legitimately names the function to explain why
    Baseline 2 deliberately does not call it)."""
    assert not hasattr(baseline2, "analyze_paths_evidence_overlap")


# -- the key result: Baseline 2 vs. Witnessgraph -------------------------------


def test_direct_different_shared_root_fools_baseline2_not_witnessgraph() -> None:
    """The central V2 discriminating fixture: different direct references
    that resolve to the same root. Baseline 2 (direct-only) is fooled;
    Witnessgraph (recursive) is not."""
    evaluation = evaluate_fixture(_fixture("direct-different-shared-root-01"))
    assert evaluation.predicted_independent["baseline2"] is True
    assert evaluation.false_corroboration["baseline2"] is True
    assert evaluation.predicted_independent["witnessgraph"] is False
    assert evaluation.false_corroboration["witnessgraph"] is False


def test_mixed_direct_derived_fools_baseline2_not_witnessgraph() -> None:
    evaluation = evaluate_fixture(_fixture("mixed-direct-derived-01"))
    assert evaluation.predicted_independent["baseline2"] is True
    assert evaluation.predicted_independent["witnessgraph"] is False


def test_multi_level_lineage_fools_baseline2_not_witnessgraph() -> None:
    evaluation = evaluate_fixture(_fixture("multi-level-lineage-01"))
    assert evaluation.predicted_independent["baseline2"] is True
    assert evaluation.predicted_independent["witnessgraph"] is False


def test_direct_same_root_disjoint_agrees_across_methods() -> None:
    """Negative-control fixture: id-based comparison is not fooled by
    matching event_type/attributes -- baseline2 and witnessgraph agree."""
    evaluation = evaluate_fixture(_fixture("direct-same-root-disjoint-01"))
    assert evaluation.predicted_independent["baseline2"] is True
    assert evaluation.predicted_independent["witnessgraph"] is True
    assert evaluation.false_corroboration["baseline2"] is False
    assert evaluation.false_corroboration["witnessgraph"] is False


def test_high_path_shared_root_fools_baseline2_at_scale() -> None:
    evaluation = evaluate_fixture(_fixture("high-path-shared-root-01"))
    assert evaluation.actual_shortest_path_count == 6
    assert evaluation.predicted_independent["baseline2"] is True
    assert evaluation.predicted_independent["witnessgraph"] is False


def test_high_path_disjoint_root_all_methods_agree() -> None:
    """The scalable true-positive case: every method correctly identifies
    genuine independence at 6 chains."""
    evaluation = evaluate_fixture(_fixture("high-path-disjoint-root-01"))
    assert evaluation.actual_shortest_path_count == 6
    for method in ("baseline0", "baseline1", "baseline2", "witnessgraph"):
        assert evaluation.predicted_independent[method] is True
        assert evaluation.false_corroboration[method] is False


def test_baseline1_never_outperforms_baseline0() -> None:
    """Baseline 1's structural-only reasoning is designed to carry zero
    extra evidence-discriminating signal beyond path count -- it must
    match Baseline 0's classification on every fixture in this benchmark
    (every fixture's chains are constructed with distinct intermediate
    entities/relationships)."""
    for fixture in _ALL_FIXTURES:
        evaluation = evaluate_fixture(fixture)
        assert (
            evaluation.predicted_independent["baseline0"]
            == evaluation.predicted_independent["baseline1"]
        ), evaluation.fixture_id


# -- V1 fixtures retained unchanged under V2 -----------------------------------


def test_v1_fixtures_have_identical_direct_and_root_sets() -> None:
    """Every retained V1 fixture uses no NormalizedEvent indirection, so
    direct references and root evidence must be identical -- Baseline 2
    cannot be distinguished from Witnessgraph on any V1 fixture."""
    for fixture_id in (
        "shared-root-01",
        "disjoint-roots-01",
        "identical-root-sets-01",
        "path-count-deception-01",
        "disjoint-multi-evidence-01",
        "byte-distinct-same-source-01",
    ):
        evaluation = evaluate_fixture(_fixture(fixture_id))
        assert evaluation.actual_direct_sets == evaluation.actual_root_sets, fixture_id
        assert (
            evaluation.predicted_independent["baseline2"]
            == evaluation.predicted_independent["witnessgraph"]
        ), fixture_id


def test_byte_distinct_same_source_records_conceptual_source_group() -> None:
    evaluation = evaluate_fixture(_fixture("byte-distinct-same-source-01"))
    assert evaluation.is_adversarial is True
    assert evaluation.conceptual_source_groups is not None
    (group,) = evaluation.conceptual_source_groups
    assert group == frozenset({"via B", "via C"})


# -- partial overlap / H3 ------------------------------------------------------


def test_partial_multi_root_masks_four_of_six_disjoint_pairs() -> None:
    evaluation = evaluate_fixture(_fixture("partial-multi-root-01"))
    assert evaluation.predicted_independent["witnessgraph"] is False
    metrics = compute_metrics([evaluation])
    (finding,) = metrics.partial_overlap_findings
    assert finding.total_chain_pairs == 6
    assert finding.root_disjoint_pairs == 4
    assert finding.root_pairs_masked_by_boolean == 4
    assert finding.information_loss_rate == pytest.approx(4 / 6)


# -- full benchmark run ---------------------------------------------------------


def test_full_benchmark_run_produces_expected_groups() -> None:
    evaluations, metrics = run_benchmark()
    assert len(evaluations) == 15
    assert metrics.total_fixtures == 15
    assert metrics.all_ground_truth_matches is True
    assert metrics.all_deterministic_replay_ok is True
    assert len(metrics.binary.fixture_ids) == 11
    assert len(metrics.single_path.fixture_ids) == 1
    assert len(metrics.partial_overlap.fixture_ids) == 2
    assert len(metrics.adversarial.fixture_ids) == 1


def test_binary_group_witnessgraph_confusion_matrix_is_perfect() -> None:
    _, metrics = run_benchmark()
    cm = metrics.binary.confusion["witnessgraph"]
    assert (cm.true_positive, cm.false_positive, cm.false_negative, cm.true_negative) == (
        4,
        0,
        0,
        7,
    )
    assert cm.accuracy == 1.0
    assert cm.false_positive_rate == 0.0


def test_binary_group_baseline2_is_fooled_on_exactly_the_new_discriminating_fixtures() -> None:
    """Baseline 2 improves on Baseline 0/1 (path-count/structure carry no
    signal at all) but is still fooled on exactly the fixtures requiring
    recursive resolution -- the key V2 result: the research gap survives
    the strongest non-recursive baseline."""
    _, metrics = run_benchmark()
    cm = metrics.binary.confusion["baseline2"]
    assert (cm.true_positive, cm.false_positive, cm.false_negative, cm.true_negative) == (
        4,
        4,
        0,
        3,
    )
    assert metrics.binary.false_corroboration_count["baseline2"] == 4
    assert metrics.binary.false_corroboration_count["witnessgraph"] == 0


def test_binary_group_baseline0_and_baseline1_are_identical() -> None:
    _, metrics = run_benchmark()
    assert metrics.binary.confusion["baseline0"] == metrics.binary.confusion["baseline1"]
    assert (
        metrics.binary.false_corroboration_count["baseline0"]
        == metrics.binary.false_corroboration_count["baseline1"]
        == 7
    )


def test_json_document_is_canonical_and_deterministic() -> None:
    doc1 = to_json_document(*run_benchmark())
    doc2 = to_json_document(*run_benchmark())
    assert canonical_json_bytes(doc1) == canonical_json_bytes(doc2)
