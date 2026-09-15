"""WG-Bench runner: discovers fixtures, evaluates each against its
ground truth, computes aggregate metrics, and renders both a canonical
JSON document and a human-readable text summary.

Uses Witnessgraph's own existing Python APIs directly
(``correlate.graph``, ``core.ids.canonical_json_bytes``) -- it never
shells out to, or parses the text output of, the ``witnessgraph`` CLI.
"""

from __future__ import annotations

from research.wg_bench.evaluation import FixtureEvaluation, evaluate_fixture
from research.wg_bench.fixtures import all_fixtures
from research.wg_bench.metrics import (
    BenchmarkMetrics,
    ConfusionMatrix,
    GroupMetrics,
    PartialOverlapFinding,
    compute_metrics,
)

WG_BENCH_VERSION = "1.0.0"


def run_benchmark() -> tuple[list[FixtureEvaluation], BenchmarkMetrics]:
    """Evaluate every registered fixture and compute aggregate metrics."""
    evaluations = [evaluate_fixture(fixture) for fixture in all_fixtures()]
    metrics = compute_metrics(evaluations)
    return evaluations, metrics


# -- JSON rendering -----------------------------------------------------------


def _evaluation_to_json(e: FixtureEvaluation) -> dict[str, object]:
    return {
        "fixture_id": e.fixture_id,
        "fixture_class": e.fixture_class,
        "is_adversarial": e.is_adversarial,
        "known_limitation": e.known_limitation,
        "expected_shortest_path_count": e.expected_shortest_path_count,
        "actual_shortest_path_count": e.actual_shortest_path_count,
        "path_count_matches_expected": e.path_count_matches_expected,
        "expected_root_sets": [list(s) for s in e.expected_root_sets],
        "actual_root_sets": [list(s) for s in e.actual_root_sets],
        "root_sets_match_expected": e.root_sets_match_expected,
        "ground_truth_root_sets_identical": e.ground_truth_root_sets_identical,
        "ground_truth_root_sets_disjoint": e.ground_truth_root_sets_disjoint,
        "ground_truth_root_sets_partial_overlap": e.ground_truth_root_sets_partial_overlap,
        "ground_truth_binary_applicable": e.ground_truth_binary_applicable,
        "baseline_classification": e.baseline_classification,
        "baseline_expected_classification": e.baseline_expected_classification,
        "baseline_matches_expected": e.baseline_matches_expected,
        "baseline_implies_independent_corroboration": e.baseline_implies_independent_corroboration,
        "baseline_false_corroboration": e.baseline_false_corroboration,
        "witnessgraph_fully_evidence_independent": e.witnessgraph_fully_evidence_independent,
        "witnessgraph_shared_evidence_ids": list(e.witnessgraph_shared_evidence_ids),
        "provenance_expected_classification": e.provenance_expected_classification,
        "provenance_matches_expected": e.provenance_matches_expected,
        "witnessgraph_classification_correct": e.witnessgraph_classification_correct,
        "witnessgraph_false_corroboration": e.witnessgraph_false_corroboration,
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


def _group_to_json(g: GroupMetrics) -> dict[str, object]:
    return {
        "group": g.group,
        "fixture_ids": list(g.fixture_ids),
        "baseline_confusion_matrix": _confusion_to_json(g.baseline_confusion),
        "witnessgraph_confusion_matrix": _confusion_to_json(g.witnessgraph_confusion),
        "baseline_false_corroboration_count": g.baseline_false_corroboration_count,
        "witnessgraph_false_corroboration_count": g.witnessgraph_false_corroboration_count,
        "deterministic_replay_success_count": g.deterministic_replay_success_count,
        "deterministic_replay_total": g.deterministic_replay_total,
        "deterministic_replay_success_rate": g.deterministic_replay_success_rate,
    }


def _partial_overlap_finding_to_json(f: PartialOverlapFinding) -> dict[str, object]:
    return {
        "fixture_id": f.fixture_id,
        "total_chain_pairs": f.total_chain_pairs,
        "disjoint_pairs": f.disjoint_pairs,
        "non_disjoint_pairs": f.non_disjoint_pairs,
        "boolean_verdict": f.boolean_verdict,
        "shared_evidence_ids": list(f.shared_evidence_ids),
        "pairs_masked_by_boolean": f.pairs_masked_by_boolean,
    }


def _metrics_to_json(m: BenchmarkMetrics) -> dict[str, object]:
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
    evaluations: list[FixtureEvaluation], metrics: BenchmarkMetrics
) -> dict[str, object]:
    """A plain dict/list tree for one benchmark run -- pass to
    ``witnessgraph.core.ids.canonical_json_bytes`` for deterministic
    encoding, exactly like Witnessgraph's own ``*_to_json`` builders."""
    return {
        "wg_bench_version": WG_BENCH_VERSION,
        "fixtures": [_evaluation_to_json(e) for e in evaluations],
        "metrics": _metrics_to_json(metrics),
    }


# -- text rendering -------------------------------------------------------


def _group_lines(title: str, g: GroupMetrics) -> list[str]:
    cm = g.witnessgraph_confusion
    bcm = g.baseline_confusion
    return [
        f"{title} (n={len(g.fixture_ids)}): {list(g.fixture_ids)}",
        (
            f"  witnessgraph confusion matrix: TP={cm.true_positive} FP={cm.false_positive} "
            f"FN={cm.false_negative} TN={cm.true_negative} accuracy={cm.accuracy} "
            f"precision={cm.precision} recall={cm.recall} "
            f"false_positive_rate={cm.false_positive_rate}"
        ),
        (
            f"  baseline confusion matrix:     TP={bcm.true_positive} FP={bcm.false_positive} "
            f"FN={bcm.false_negative} TN={bcm.true_negative} "
            f"false_positive_rate={bcm.false_positive_rate}"
        ),
        (
            f"  false-corroboration count -- baseline: {g.baseline_false_corroboration_count}, "
            f"witnessgraph: {g.witnessgraph_false_corroboration_count}"
        ),
        (
            f"  deterministic replay success: {g.deterministic_replay_success_count}/"
            f"{g.deterministic_replay_total} ({g.deterministic_replay_success_rate})"
        ),
        "",
    ]


def render_text_report(evaluations: list[FixtureEvaluation], metrics: BenchmarkMetrics) -> str:
    lines: list[str] = [
        "WG-Bench results",
        "=================",
        f"Fixtures evaluated: {metrics.total_fixtures}",
        f"All ground-truth checks passed: {metrics.all_ground_truth_matches}",
        f"All deterministic-replay checks passed: {metrics.all_deterministic_replay_ok}",
        "",
        "Per-fixture:",
    ]
    for e in evaluations:
        lines.append(
            f"  [{e.fixture_class}] {e.fixture_id}: "
            f"paths={e.actual_shortest_path_count} "
            f"baseline={e.baseline_classification} "
            f"witnessgraph_independent={e.witnessgraph_fully_evidence_independent} "
            f"ground_truth_disjoint={e.ground_truth_root_sets_disjoint} "
            f"baseline_false_corroboration={e.baseline_false_corroboration} "
            f"witnessgraph_false_corroboration={e.witnessgraph_false_corroboration} "
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
                f"  {f.fixture_id}: {f.disjoint_pairs}/{f.total_chain_pairs} chain pairs are "
                f"root-evidence-disjoint, but the top-level boolean verdict is "
                f"{f.boolean_verdict} -- {f.pairs_masked_by_boolean} genuinely disjoint "
                f"pair(s) are not surfaced by that single field."
            )

    return "\n".join(lines)
