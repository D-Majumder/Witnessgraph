"""WG-Bench V2 runner: discovers all 15 fixtures (8 retained V1 + 7 new),
evaluates each against all four methods, computes aggregate metrics, and
renders both a canonical JSON document and a human-readable text summary.
"""

from __future__ import annotations

from research.wg_bench.metrics import ConfusionMatrix
from research.wg_bench.v2.evaluation import FixtureEvaluationV2, evaluate_fixture
from research.wg_bench.v2.fixtures import all_fixtures
from research.wg_bench.v2.metrics import (
    METHODS,
    BenchmarkMetricsV2,
    GroupMetricsV2,
    PartialOverlapFindingV2,
    compute_metrics,
)

WG_BENCH_V2_VERSION = "2.0.0"


def run_benchmark() -> tuple[list[FixtureEvaluationV2], BenchmarkMetricsV2]:
    evaluations = [evaluate_fixture(fixture) for fixture in all_fixtures()]
    metrics = compute_metrics(evaluations)
    return evaluations, metrics


# -- JSON rendering -----------------------------------------------------------


def _evaluation_to_json(e: FixtureEvaluationV2) -> dict[str, object]:
    return {
        "fixture_id": e.fixture_id,
        "fixture_class": e.fixture_class,
        "is_adversarial": e.is_adversarial,
        "known_limitation": e.known_limitation,
        "conceptual_source_groups": (
            [sorted(g) for g in e.conceptual_source_groups]
            if e.conceptual_source_groups is not None
            else None
        ),
        "expected_shortest_path_count": e.expected_shortest_path_count,
        "actual_shortest_path_count": e.actual_shortest_path_count,
        "path_count_matches_expected": e.path_count_matches_expected,
        "expected_direct_sets": [list(s) for s in e.expected_direct_sets],
        "actual_direct_sets": [list(s) for s in e.actual_direct_sets],
        "direct_sets_match_expected": e.direct_sets_match_expected,
        "expected_root_sets": [list(s) for s in e.expected_root_sets],
        "actual_root_sets": [list(s) for s in e.actual_root_sets],
        "root_sets_match_expected": e.root_sets_match_expected,
        "ground_truth_direct_sets_disjoint": e.ground_truth_direct_sets_disjoint,
        "ground_truth_root_sets_disjoint": e.ground_truth_root_sets_disjoint,
        "ground_truth_root_sets_partial_overlap": e.ground_truth_root_sets_partial_overlap,
        "ground_truth_binary_applicable": e.ground_truth_binary_applicable,
        "predicted_independent": dict(e.predicted_independent),
        "false_corroboration": dict(e.false_corroboration),
        "classification_correct": dict(e.classification_correct),
        "deterministic_replay_ok": e.deterministic_replay_ok,
        "manifest_hash_run_1": e.manifest_hash_run_1,
        "manifest_hash_run_2": e.manifest_hash_run_2,
    }


def _confusion_to_json(cm: ConfusionMatrix) -> dict[str, object]:
    return {
        "true_positive": cm.true_positive,
        "false_positive": cm.false_positive,
        "false_negative": cm.false_negative,
        "true_negative": cm.true_negative,
        "total": cm.total,
        "accuracy": cm.accuracy,
        "precision": cm.precision,
        "recall": cm.recall,
        "false_positive_rate": cm.false_positive_rate,
    }


def _group_to_json(g: GroupMetricsV2) -> dict[str, object]:
    return {
        "group": g.group,
        "fixture_ids": list(g.fixture_ids),
        "confusion_matrix": {m: _confusion_to_json(g.confusion[m]) for m in METHODS},
        "false_corroboration_count": dict(g.false_corroboration_count),
        "deterministic_replay_success_count": g.deterministic_replay_success_count,
        "deterministic_replay_total": g.deterministic_replay_total,
        "deterministic_replay_success_rate": g.deterministic_replay_success_rate,
    }


def _partial_overlap_finding_to_json(f: PartialOverlapFindingV2) -> dict[str, object]:
    return {
        "fixture_id": f.fixture_id,
        "total_chain_pairs": f.total_chain_pairs,
        "root_disjoint_pairs": f.root_disjoint_pairs,
        "root_boolean_verdict": f.root_boolean_verdict,
        "root_pairs_masked_by_boolean": f.root_pairs_masked_by_boolean,
        "direct_disjoint_pairs": f.direct_disjoint_pairs,
        "direct_boolean_verdict": f.direct_boolean_verdict,
        "direct_pairs_masked_by_boolean": f.direct_pairs_masked_by_boolean,
        "information_loss_rate": f.information_loss_rate,
    }


def _metrics_to_json(m: BenchmarkMetricsV2) -> dict[str, object]:
    return {
        "total_fixtures": m.total_fixtures,
        "all_ground_truth_matches": m.all_ground_truth_matches,
        "all_deterministic_replay_ok": m.all_deterministic_replay_ok,
        "binary": _group_to_json(m.binary),
        "single_path": _group_to_json(m.single_path),
        "partial_overlap": _group_to_json(m.partial_overlap),
        "adversarial": _group_to_json(m.adversarial),
        "partial_overlap_findings": [
            _partial_overlap_finding_to_json(f) for f in m.partial_overlap_findings
        ],
    }


def to_json_document(
    evaluations: list[FixtureEvaluationV2], metrics: BenchmarkMetricsV2
) -> dict[str, object]:
    return {
        "wg_bench_version": WG_BENCH_V2_VERSION,
        "methods": list(METHODS),
        "fixtures": [_evaluation_to_json(e) for e in evaluations],
        "metrics": _metrics_to_json(metrics),
    }


# -- text rendering -------------------------------------------------------


def _group_lines(title: str, g: GroupMetricsV2) -> list[str]:
    lines = [f"{title} (n={len(g.fixture_ids)}): {list(g.fixture_ids)}"]
    for method in METHODS:
        cm = g.confusion[method]
        lines.append(
            f"  {method}: TP={cm.true_positive} FP={cm.false_positive} FN={cm.false_negative} "
            f"TN={cm.true_negative} accuracy={cm.accuracy} precision={cm.precision} "
            f"recall={cm.recall} false_positive_rate={cm.false_positive_rate} "
            f"false_corroboration_count={g.false_corroboration_count[method]}"
        )
    lines.append(
        f"  deterministic replay success: {g.deterministic_replay_success_count}/"
        f"{g.deterministic_replay_total} ({g.deterministic_replay_success_rate})"
    )
    lines.append("")
    return lines


def render_text_report(evaluations: list[FixtureEvaluationV2], metrics: BenchmarkMetricsV2) -> str:
    lines: list[str] = [
        "WG-Bench V2 results",
        "====================",
        f"Fixtures evaluated: {metrics.total_fixtures}",
        f"All ground-truth checks passed: {metrics.all_ground_truth_matches}",
        f"All deterministic-replay checks passed: {metrics.all_deterministic_replay_ok}",
        "",
        "Per-fixture:",
    ]
    for e in evaluations:
        lines.append(
            f"  [{e.fixture_class}] {e.fixture_id}: paths={e.actual_shortest_path_count} "
            f"predicted_independent={e.predicted_independent} "
            f"ground_truth_disjoint={e.ground_truth_root_sets_disjoint} "
            f"false_corroboration={e.false_corroboration} "
            f"deterministic_replay_ok={e.deterministic_replay_ok}"
        )
        if e.known_limitation:
            lines.append(f"      known limitation: {e.known_limitation}")
    lines.append("")

    lines += _group_lines("Binary-classification group", metrics.binary)
    lines += _group_lines("Single-path sanity group", metrics.single_path)
    lines += _group_lines("Partial-overlap group", metrics.partial_overlap)
    lines += _group_lines("Adversarial group", metrics.adversarial)

    if metrics.partial_overlap_findings:
        lines.append("Partial-overlap information-loss findings:")
        for f in metrics.partial_overlap_findings:
            lines.append(
                f"  {f.fixture_id}: {f.root_disjoint_pairs}/{f.total_chain_pairs} chain pairs "
                f"are root-evidence-disjoint, but the top-level boolean verdict is "
                f"{f.root_boolean_verdict} -- {f.root_pairs_masked_by_boolean} genuinely "
                f"disjoint pair(s) not surfaced (information_loss_rate="
                f"{f.information_loss_rate})."
            )

    return "\n".join(lines)
