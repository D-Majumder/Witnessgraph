"""Developer validation mode.

Exercises the whole WG-Study pipeline end-to-end -- case building,
condition presentation, question generation, response recording
(including the local storage round-trip), answer-key matching, and
metric computation -- using the answer key itself to answer every
generated question CORRECTLY, with zero human input.

This is a pipeline correctness check, not a research result. Every
record it writes is stamped ``is_developer_validation=True`` and goes to
``storage.DEV_VALIDATION_FILE``, a file physically separate from
``storage.PARTICIPANT_RESPONSES_FILE``; ``analysis.analyze`` excludes
every such record unconditionally. Developer-validation records must
never be reported as, or merged into, a real participant dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from research.wg_study import analysis, case_builder, runner, storage
from research.wg_study import questions as questions_module
from research.wg_study.model import ALL_CONDITIONS, STUDY_VERSION, ParticipantResponse


@dataclass(frozen=True)
class ValidationResult:
    cases_checked: int
    questions_per_condition: int
    total_responses_recorded: int
    all_answers_correct_by_construction: bool
    storage_round_trip_ok: bool
    analysis_correctly_excludes_validation_data: bool
    detail: str


def run_developer_validation() -> ValidationResult:
    cases_and_keys = case_builder.build_all_cases()
    answer_keys_by_case = {key.case_id: key for _case, key in cases_and_keys}

    responses: list[ParticipantResponse] = []
    questions_per_condition = 0
    for study_case, key in cases_and_keys:
        case_questions = questions_module.generate_questions(study_case)
        questions_per_condition += len(case_questions)
        for condition in ALL_CONDITIONS:
            for question in case_questions:
                correct = runner.lookup_correct_answer(key, question.chain_pair)
                response = ParticipantResponse(
                    participant_id="dev-validation",
                    condition=condition,
                    case_id=study_case.case_id,
                    question_id=question.question_id,
                    answer=correct,
                    correct_answer=correct,
                    response_time_ms=1,
                    timestamp=datetime.now(UTC).isoformat(),
                    optional_notes=None,
                    study_version=STUDY_VERSION,
                    is_developer_validation=True,
                )
                storage.append_response(response)
                responses.append(response)

    all_correct = all(r.answer == r.correct_answer for r in responses)

    reloaded = storage.load_responses(storage.DEV_VALIDATION_FILE)
    round_trip_ok = len(reloaded) >= len(responses) and all(
        any(
            (r.case_id, r.question_id, r.condition, r.timestamp)
            == (loaded.case_id, loaded.question_id, loaded.condition, loaded.timestamp)
            for loaded in reloaded
        )
        for r in responses
    )

    excludes_validation = analysis.analyze(responses).has_participant_data is False

    return ValidationResult(
        cases_checked=len(cases_and_keys),
        questions_per_condition=questions_per_condition,
        total_responses_recorded=len(responses),
        all_answers_correct_by_construction=all_correct,
        storage_round_trip_ok=round_trip_ok,
        analysis_correctly_excludes_validation_data=excludes_validation,
        detail=(
            f"{len(cases_and_keys)} cases, {questions_per_condition} questions/condition, "
            f"{len(responses)} total responses across {len(ALL_CONDITIONS)} conditions. "
            f"answer_keys_by_case has {len(answer_keys_by_case)} entries."
        ),
    )
