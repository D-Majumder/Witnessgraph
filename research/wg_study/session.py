"""Interactive participant and pilot/developer session flows.

Two entry points:

- ``run_participant_session`` -- the real participant path. Builds the
  case manifest, assigns a condition reproducibly from the participant's
  own (caller-supplied, expected-anonymous) id, walks through every case
  in that participant's deterministic order, asks each case's
  question(s) one at a time via ``presentation.present_case`` (which
  never imports ``answer_key``), times each response, and records it
  through ``runner.record_response`` into the real participant dataset
  (``storage.PARTICIPANT_RESPONSES_FILE``). Never reveals a correct
  answer, never reveals ``case_type``, never reveals the condition's
  name to imply it is "the good one."
- ``run_pilot_walkthrough`` -- a developer/pilot path over the exact same
  presentation and question logic, but after each answer it reveals the
  correct answer (for a human reviewer manually checking the interface
  makes sense) and writes exclusively to the developer-validation file,
  clearly labeled, never the real participant dataset.

Both use the same ``io_read``/``io_write`` callables (default
``input``/``print``) so tests can drive a scripted session without a
real terminal.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from research.wg_study import case_builder, instructions, presentation
from research.wg_study import questions as questions_module
from research.wg_study import runner as runner_module
from research.wg_study.model import Answer, Condition, ParticipantResponse

_ANSWER_ALIASES: dict[str, Answer] = {
    "shared": Answer.SHARED_ROOT,
    "s": Answer.SHARED_ROOT,
    "disjoint": Answer.DISJOINT_ROOT,
    "d": Answer.DISJOINT_ROOT,
    "indeterminate": Answer.INDETERMINATE,
    "i": Answer.INDETERMINATE,
    "unsure": Answer.INDETERMINATE,
}

IoRead = Callable[[str], str]
IoWrite = Callable[[str], None]


def parse_answer(raw: str) -> Answer | None:
    return _ANSWER_ALIASES.get(raw.strip().lower())


def _render_case_view_text(view: presentation.CaseView) -> str:
    lines = [
        f"Case {view.case_id}  (connects {view.source_entity_label} -> {view.target_entity_label})",
        f"Relevant chains found: {view.path_count}",
    ]
    for chain in view.chains:
        lines.append(f"  Chain {chain.chain_index + 1}:")
        lines.append(f"    entities: {', '.join(chain.entity_labels)}")
        lines.append(f"    relationships: {', '.join(chain.relationship_labels)}")
        if chain.direct_reference_labels is not None:
            direct_refs = ", ".join(chain.direct_reference_labels) or "(none)"
            lines.append(f"    direct evidence references: {direct_refs}")
        if chain.root_evidence_labels is not None:
            root_evidence = ", ".join(chain.root_evidence_labels) or "(none)"
            lines.append(f"    root evidence (resolved): {root_evidence}")
    return "\n".join(lines)


@dataclass(frozen=True)
class SessionSummary:
    participant_id: str
    condition: Condition
    cases_completed: int
    questions_answered: int
    is_pilot: bool


def _ask_one_question(
    *,
    io_read: IoRead,
    io_write: IoWrite,
    prompt: str,
) -> tuple[Answer, int]:
    io_write(prompt)
    io_write("Answer [shared/disjoint/indeterminate]: ")
    start = time.perf_counter()
    while True:
        raw = io_read("")
        parsed = parse_answer(raw)
        if parsed is not None:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return parsed, elapsed_ms
        io_write("Please answer one of: shared, disjoint, indeterminate.\n")


def run_participant_session(
    *,
    participant_id: str,
    io_read: IoRead = input,
    io_write: IoWrite = print,
    out_dir: Path | None = None,
) -> SessionSummary:
    """Runs one full real participant session and records every answer
    into the real participant dataset. ``participant_id`` must already be
    an anonymous token supplied by the caller -- this function does not
    validate or anonymize it (see ``model.ParticipantResponse``'s
    docstring and ``docs/research/wg-study-participant-protocol.md``)."""
    io_write(instructions.PARTICIPANT_INSTRUCTIONS)

    cases_and_keys = case_builder.build_all_cases()
    answer_keys_by_case = {key.case_id: key for _case, key in cases_and_keys}
    cases_by_id = {c.case_id: c for c, _key in cases_and_keys}

    condition = runner_module.assign_condition(participant_id)
    order = runner_module.case_order(participant_id, tuple(cases_by_id))

    questions_answered = 0
    for case_id in order:
        study_case = cases_by_id[case_id]
        view = presentation.present_case(study_case, condition)
        io_write("\n" + _render_case_view_text(view) + "\n")
        for question in questions_module.generate_questions(study_case):
            answer, elapsed_ms = _ask_one_question(
                io_read=io_read, io_write=io_write, prompt=question.prompt
            )
            runner_module.record_response(
                participant_id=participant_id,
                condition=condition,
                case_id=case_id,
                question_id=question.question_id,
                chain_pair=question.chain_pair,
                answer=answer,
                response_time_ms=elapsed_ms,
                notes=None,
                answer_keys_by_case=answer_keys_by_case,
                is_developer_validation=False,
                out_dir=out_dir,
            )
            questions_answered += 1

    io_write(
        "\nSession complete. Thank you -- your responses have been recorded locally. "
        "This session does not reveal how any question should have been answered.\n"
    )
    return SessionSummary(
        participant_id=participant_id,
        condition=condition,
        cases_completed=len(order),
        questions_answered=questions_answered,
        is_pilot=False,
    )


def run_pilot_walkthrough(
    *,
    participant_id: str = "pilot-walkthrough",
    io_read: IoRead = input,
    io_write: IoWrite = print,
    out_dir: Path | None = None,
) -> SessionSummary:
    """Developer/pilot mode: identical presentation and question flow to
    a real session, but reveals the correct answer after each response
    (for a human reviewer checking the interface) and records exclusively
    into the developer-validation dataset -- never the real participant
    file. See ``storage.DEV_VALIDATION_FILE``."""
    io_write("=== DEVELOPER / PILOT WALKTHROUGH -- NOT PARTICIPANT DATA ===\n")
    io_write(instructions.PARTICIPANT_INSTRUCTIONS)

    cases_and_keys = case_builder.build_all_cases()
    answer_keys_by_case = {key.case_id: key for _case, key in cases_and_keys}
    cases_by_id = {c.case_id: c for c, _key in cases_and_keys}

    condition = runner_module.assign_condition(participant_id)
    order = runner_module.case_order(participant_id, tuple(cases_by_id))

    questions_answered = 0
    for case_id in order:
        study_case = cases_by_id[case_id]
        io_write(f"\n[developer] case_id={case_id} case_type={study_case.case_type}\n")
        view = presentation.present_case(study_case, condition)
        io_write(_render_case_view_text(view) + "\n")
        for question in questions_module.generate_questions(study_case):
            answer, elapsed_ms = _ask_one_question(
                io_read=io_read, io_write=io_write, prompt=question.prompt
            )
            response: ParticipantResponse = runner_module.record_response(
                participant_id=participant_id,
                condition=condition,
                case_id=case_id,
                question_id=question.question_id,
                chain_pair=question.chain_pair,
                answer=answer,
                response_time_ms=elapsed_ms,
                notes=None,
                answer_keys_by_case=answer_keys_by_case,
                is_developer_validation=True,
                out_dir=out_dir,
            )
            io_write(
                f"[developer] correct_answer={response.correct_answer.value} "
                f"your_answer={response.answer.value} "
                f"match={response.answer == response.correct_answer}\n"
            )
            questions_answered += 1

    io_write("\n=== END DEVELOPER / PILOT WALKTHROUGH ===\n")
    return SessionSummary(
        participant_id=participant_id,
        condition=condition,
        cases_completed=len(order),
        questions_answered=questions_answered,
        is_pilot=True,
    )
