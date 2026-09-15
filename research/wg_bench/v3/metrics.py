"""V3-specific aggregate metrics: reuses V2's ``compute_metrics`` (same
four never-pooled evaluation groups: binary/single_path/partial_overlap/
adversarial) unmodified, and adds the five discriminator-analysis counts
spec section 9 requires -- none of which existed in V2, since V2 had no
reason to ask "does Baseline 2 ever do AS WELL AS Witnessgraph" (V3's
whole point is to actively look for that).

Every count here is computed only over fixtures where the binary
independence question applies at all (``ground_truth_binary_applicable``)
-- the same restriction V2's confusion matrices already use, so these
counts are never contaminated by adversarial/single-path/partial-overlap
fixtures where "Baseline 2 vs Witnessgraph" is not a well-formed
question.
"""

from __future__ import annotations

from dataclasses import dataclass

from research.wg_bench.v2.evaluation import FixtureEvaluationV2
from research.wg_bench.v2.metrics import BenchmarkMetricsV2, compute_metrics


@dataclass(frozen=True)
class DiscriminatorFinding:
    fixture_id: str
    fixture_class: str
    baseline2_predicted_independent: bool | None
    witnessgraph_predicted_independent: bool | None
    ground_truth_root_sets_disjoint: bool | None
    #: One of: "baseline2_wins", "witnessgraph_wins", "tie", "both_wrong",
    #: "not_applicable" (fewer than 2 chains -- no binary question).
    outcome: str


def _outcome(e: FixtureEvaluationV2) -> str:
    if not e.ground_truth_binary_applicable:
        return "not_applicable"
    b2_correct = e.classification_correct["baseline2"]
    wg_correct = e.classification_correct["witnessgraph"]
    if b2_correct and wg_correct:
        return "tie"
    if wg_correct and not b2_correct:
        return "witnessgraph_wins"
    if b2_correct and not wg_correct:
        return "baseline2_wins"
    return "both_wrong"


@dataclass(frozen=True)
class DiscriminatorAnalysis:
    findings: tuple[DiscriminatorFinding, ...]

    #: Fixtures where Witnessgraph's predicted_independent differs from
    #: Baseline 2's, regardless of which (if either) is correct.
    discriminator_count: int
    #: Of those, fixtures where Witnessgraph matches ground truth and
    #: Baseline 2 does not -- the precise V2-style "research gap" count.
    correct_discriminator_count: int
    #: Fixtures where Baseline 2 and Witnessgraph produce the SAME
    #: correct (both classification_correct) result.
    baseline_equivalence_count: int
    #: Fixtures where Baseline 2 performs as well as or better than
    #: Witnessgraph (tie OR baseline2_wins OR both wrong) -- the
    #: "adversarial defeat" count spec section 9 asks for.
    adversarial_defeat_count: int
    #: In-scope (binary-applicable) fixtures where Witnessgraph disagrees
    #: with ground truth at all, independent of Baseline 2.
    witnessgraph_error_count: int


def compute_discriminator_analysis(evaluations: list[FixtureEvaluationV2]) -> DiscriminatorAnalysis:
    findings: list[DiscriminatorFinding] = []
    for e in evaluations:
        if not e.ground_truth_binary_applicable:
            continue
        findings.append(
            DiscriminatorFinding(
                fixture_id=e.fixture_id,
                fixture_class=e.fixture_class,
                baseline2_predicted_independent=e.predicted_independent["baseline2"],
                witnessgraph_predicted_independent=e.predicted_independent["witnessgraph"],
                ground_truth_root_sets_disjoint=e.ground_truth_root_sets_disjoint,
                outcome=_outcome(e),
            )
        )

    discriminator = [
        f
        for f in findings
        if f.baseline2_predicted_independent != f.witnessgraph_predicted_independent
    ]
    correct_discriminator = [f for f in discriminator if f.outcome == "witnessgraph_wins"]
    baseline_equivalence = [f for f in findings if f.outcome == "tie"]
    adversarial_defeat = [
        f for f in findings if f.outcome in ("tie", "baseline2_wins", "both_wrong")
    ]
    witnessgraph_error = [
        f
        for f in findings
        if f.witnessgraph_predicted_independent != f.ground_truth_root_sets_disjoint
    ]

    return DiscriminatorAnalysis(
        findings=tuple(findings),
        discriminator_count=len(discriminator),
        correct_discriminator_count=len(correct_discriminator),
        baseline_equivalence_count=len(baseline_equivalence),
        adversarial_defeat_count=len(adversarial_defeat),
        witnessgraph_error_count=len(witnessgraph_error),
    )


@dataclass(frozen=True)
class BenchmarkMetricsV3:
    v2_style: BenchmarkMetricsV2
    discriminator: DiscriminatorAnalysis


def compute_metrics_v3(evaluations: list[FixtureEvaluationV2]) -> BenchmarkMetricsV3:
    return BenchmarkMetricsV3(
        v2_style=compute_metrics(evaluations),
        discriminator=compute_discriminator_analysis(evaluations),
    )
