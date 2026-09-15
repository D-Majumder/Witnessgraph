"""WG-Bench V3 runner: evaluates the 12 independently-designed V3
adversarial fixtures (research.wg_bench.v3.fixtures) through the exact
same four methods and evaluation harness V2 used
(research.wg_bench.v2.evaluation.evaluate_fixture), then computes both
V2-style grouped metrics and V3's new discriminator-analysis metrics.

Deliberately does NOT combine V1/V2/V3 fixtures into one run -- V3 is
reported as its own, separate benchmark, exactly as the V3 spec requires
(``docs/research/wg-bench.md``'s V3 section reports V1/V2/V3 side by
side, never pooled into one aggregate).
"""

from __future__ import annotations

from research.wg_bench.metrics import ConfusionMatrix
from research.wg_bench.v2.evaluation import FixtureEvaluationV2, evaluate_fixture
from research.wg_bench.v2.metrics import (
    METHODS,
    GroupMetricsV2,
    PartialOverlapFindingV2,
)
from research.wg_bench.v3.fixtures import all_fixtures
from research.wg_bench.v3.metrics import (
    BenchmarkMetricsV3,
    DiscriminatorAnalysis,
    DiscriminatorFinding,
    compute_metrics_v3,
)

WG_BENCH_V3_VERSION = "3.0.0"


def run_benchmark() -> tuple[list[FixtureEvaluationV2], BenchmarkMetricsV3]:
    evaluations = [evaluate_fixture(fixture) for fixture in all_fixtures()]
    metrics = compute_metrics_v3(evaluations)
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


def _discriminator_finding_to_json(f: DiscriminatorFinding) -> dict[str, object]:
    return {
        "fixture_id": f.fixture_id,
        "fixture_class": f.fixture_class,
        "baseline2_predicted_independent": f.baseline2_predicted_independent,
        "witnessgraph_predicted_independent": f.witnessgraph_predicted_independent,
        "ground_truth_root_sets_disjoint": f.ground_truth_root_sets_disjoint,
        "outcome": f.outcome,
    }


def _discriminator_to_json(d: DiscriminatorAnalysis) -> dict[str, object]:
    return {
        "findings": [_discriminator_finding_to_json(f) for f in d.findings],
        "discriminator_count": d.discriminator_count,
        "correct_discriminator_count": d.correct_discriminator_count,
        "baseline_equivalence_count": d.baseline_equivalence_count,
        "adversarial_defeat_count": d.adversarial_defeat_count,
        "witnessgraph_error_count": d.witnessgraph_error_count,
    }


def _metrics_to_json(m: BenchmarkMetricsV3) -> dict[str, object]:
    v2 = m.v2_style
    return {
        "total_fixtures": v2.total_fixtures,
        "all_ground_truth_matches": v2.all_ground_truth_matches,
        "all_deterministic_replay_ok": v2.all_deterministic_replay_ok,
        "binary": _group_to_json(v2.binary),
        "single_path": _group_to_json(v2.single_path),
        "partial_overlap": _group_to_json(v2.partial_overlap),
        "adversarial": _group_to_json(v2.adversarial),
        "partial_overlap_findings": [
            _partial_overlap_finding_to_json(f) for f in v2.partial_overlap_findings
        ],
        "discriminator_analysis": _discriminator_to_json(m.discriminator),
    }


def to_json_document(
    evaluations: list[FixtureEvaluationV2], metrics: BenchmarkMetricsV3
) -> dict[str, object]:
    return {
        "wg_bench_version": WG_BENCH_V3_VERSION,
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


def render_text_report(evaluations: list[FixtureEvaluationV2], metrics: BenchmarkMetricsV3) -> str:
    v2 = metrics.v2_style
    d = metrics.discriminator
    lines: list[str] = [
        "WG-Bench V3 results",
        "====================",
        f"Fixtures evaluated: {v2.total_fixtures}",
        f"All ground-truth checks passed: {v2.all_ground_truth_matches}",
        f"All deterministic-replay checks passed: {v2.all_deterministic_replay_ok}",
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

    lines += _group_lines("Binary-classification group", v2.binary)
    lines += _group_lines("Single-path sanity group", v2.single_path)
    lines += _group_lines("Partial-overlap group", v2.partial_overlap)
    lines += _group_lines("Adversarial group", v2.adversarial)

    if v2.partial_overlap_findings:
        lines.append("Partial-overlap information-loss findings:")
        for f in v2.partial_overlap_findings:
            lines.append(
                f"  {f.fixture_id}: {f.root_disjoint_pairs}/{f.total_chain_pairs} chain pairs "
                f"are root-evidence-disjoint, but the top-level boolean verdict is "
                f"{f.root_boolean_verdict} -- {f.root_pairs_masked_by_boolean} genuinely "
                f"disjoint pair(s) not surfaced (information_loss_rate="
                f"{f.information_loss_rate})."
            )
        lines.append("")

    lines.append("Discriminator analysis (Baseline 2 vs Witnessgraph):")
    lines.append(
        f"  discriminator_count={d.discriminator_count} "
        f"correct_discriminator_count={d.correct_discriminator_count} "
        f"baseline_equivalence_count={d.baseline_equivalence_count} "
        f"adversarial_defeat_count={d.adversarial_defeat_count} "
        f"witnessgraph_error_count={d.witnessgraph_error_count}"
    )
    for finding in d.findings:
        lines.append(
            f"  [{finding.fixture_class}] {finding.fixture_id}: outcome={finding.outcome} "
            f"baseline2={finding.baseline2_predicted_independent} "
            f"witnessgraph={finding.witnessgraph_predicted_independent} "
            f"ground_truth_disjoint={finding.ground_truth_root_sets_disjoint}"
        )

    return "\n".join(lines)
