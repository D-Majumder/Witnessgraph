"""Analysis of collected WG-Study participant responses.

Computes per-condition descriptive metrics from whatever responses
actually exist. If zero real-participant responses exist (which is the
case throughout this repository as of this module's authorship -- no
human study has been run), every entry point here says so explicitly
and computes nothing further; it never estimates, extrapolates, or
substitutes a synthetic value. Developer-validation records
(``is_developer_validation=True``) are always excluded from participant
metrics, unconditionally.

Primary outcome (``docs/research/wg-study.md`` section 9):
false-corroboration rate -- the proportion of pairwise/negative-control
answers whose ground truth is SHARED_ROOT (i.e. genuinely NOT
provenance-disjoint) that a participant answered DISJOINT_ROOT. This
mirrors WG-Bench's own false-corroboration definition exactly, applied
to human responses instead of a computed method's classification. Never
called "evidence independence accuracy" -- see
``docs/research/wg-study.md`` section 9's terminology note.

No inferential statistics (p-values, confidence intervals) are computed
by this module. ``docs/research/wg-study.md`` section 10 documents why,
and what a future analysis extension would need before adding them.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median

from research.wg_study.model import Answer, Condition, ParticipantResponse


@dataclass(frozen=True)
class ConditionMetrics:
    condition: Condition
    response_count: int
    accuracy: float | None
    shared_root_accuracy: float | None
    disjoint_root_accuracy: float | None
    partial_overlap_pair_accuracy: float | None
    mean_response_time_ms: float | None
    median_response_time_ms: float | None
    false_corroboration_rate: float | None
    indeterminate_rate: float | None
    missing_response_rate: float | None


@dataclass(frozen=True)
class StudyAnalysisResult:
    has_participant_data: bool
    total_participant_responses: int
    per_condition: tuple[ConditionMetrics, ...]
    message: str


def _ratio(numerator: int, denominator: int) -> float | None:
    return (numerator / denominator) if denominator > 0 else None


def _is_pairwise_question(question_id: str) -> bool:
    return not question_id.endswith("-q-single")


def _condition_metrics(
    condition: Condition,
    responses: list[ParticipantResponse],
    expected_question_count: int | None,
) -> ConditionMetrics:
    n = len(responses)
    if n == 0:
        return ConditionMetrics(
            condition=condition,
            response_count=0,
            accuracy=None,
            shared_root_accuracy=None,
            disjoint_root_accuracy=None,
            partial_overlap_pair_accuracy=None,
            mean_response_time_ms=None,
            median_response_time_ms=None,
            false_corroboration_rate=None,
            indeterminate_rate=None,
            missing_response_rate=(1.0 if expected_question_count else None),
        )

    correct = sum(1 for r in responses if r.answer == r.correct_answer)
    shared_truth = [r for r in responses if r.correct_answer == Answer.SHARED_ROOT]
    disjoint_truth = [r for r in responses if r.correct_answer == Answer.DISJOINT_ROOT]
    pairwise_responses = [r for r in responses if _is_pairwise_question(r.question_id)]
    false_corroboration = [r for r in shared_truth if r.answer == Answer.DISJOINT_ROOT]
    indeterminate = [r for r in responses if r.answer == Answer.INDETERMINATE]
    times = [r.response_time_ms for r in responses]

    missing_response_rate = None
    if expected_question_count is not None and expected_question_count > 0:
        missing_response_rate = _ratio(max(expected_question_count - n, 0), expected_question_count)

    return ConditionMetrics(
        condition=condition,
        response_count=n,
        accuracy=_ratio(correct, n),
        shared_root_accuracy=_ratio(
            sum(1 for r in shared_truth if r.answer == r.correct_answer), len(shared_truth)
        ),
        disjoint_root_accuracy=_ratio(
            sum(1 for r in disjoint_truth if r.answer == r.correct_answer), len(disjoint_truth)
        ),
        partial_overlap_pair_accuracy=_ratio(
            sum(1 for r in pairwise_responses if r.answer == r.correct_answer),
            len(pairwise_responses),
        ),
        mean_response_time_ms=mean(times),
        median_response_time_ms=median(times),
        false_corroboration_rate=_ratio(len(false_corroboration), len(shared_truth)),
        indeterminate_rate=_ratio(len(indeterminate), n),
        missing_response_rate=missing_response_rate,
    )


def analyze(
    responses: list[ParticipantResponse],
    *,
    expected_question_count_per_condition: int | None = None,
) -> StudyAnalysisResult:
    """Computes descriptive metrics for every non-developer-validation
    response in ``responses``. Returns ``has_participant_data=False``
    and an explicit "no results collected" message, computing nothing
    else, if none exist."""
    real = [r for r in responses if not r.is_developer_validation]
    if not real:
        return StudyAnalysisResult(
            has_participant_data=False,
            total_participant_responses=0,
            per_condition=(),
            message="No human-participant results were collected.",
        )

    per_condition = tuple(
        _condition_metrics(
            condition,
            [r for r in real if r.condition == condition],
            expected_question_count_per_condition,
        )
        for condition in (Condition.PATH_ONLY, Condition.DIRECT_EVIDENCE, Condition.WITNESSGRAPH)
    )
    conditions_with_data = sum(1 for c in per_condition if c.response_count > 0)
    return StudyAnalysisResult(
        has_participant_data=True,
        total_participant_responses=len(real),
        per_condition=per_condition,
        message=(
            f"{len(real)} participant response(s) collected across "
            f"{conditions_with_data} condition(s). Sample size is a descriptive "
            f"report only -- see docs/research/wg-study.md section 10 for when "
            f"inferential comparison would become appropriate."
        ),
    )
