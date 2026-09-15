"""Condition assignment, case ordering, and response recording.

This module MAY import ``answer_key`` (``record_response`` needs a
case's correct answer to stamp into the stored ``ParticipantResponse`` --
see ``model.ParticipantResponse``'s docstring for why that is not the
same thing as showing the answer key to a participant). The actual
on-screen rendering of a case always goes through
``presentation.present_case``, which never imports ``answer_key`` at
all; this module never passes answer-key data into anything
``presentation`` returns.

Reproducibility (``docs/research/wg-study.md`` section 13): condition
assignment and within-subject case ordering are both deterministic
functions of a fixed, recorded seed (``STUDY_SEED``) and the
participant's own id -- so a given participant_id always gets the same
condition and the same case order across a resumed session, and the
whole assignment is exactly reproducible from the recorded seed without
needing a stored, order-dependent registration roster.
"""

from __future__ import annotations

import hashlib
import random
from datetime import UTC, datetime

from research.wg_study import answer_key as answer_key_module
from research.wg_study import storage
from research.wg_study.model import ALL_CONDITIONS, Answer, Condition, ParticipantResponse

#: Fixed, recorded random seed for WG-Study condition assignment and
#: case-order counterbalancing. Changing this value changes every
#: future participant's assignment and must be treated as a new answer-
#: key/study version (see docs/research/wg-study.md section 13).
STUDY_SEED = "wg-study-v1-seed"


def assign_condition(participant_id: str) -> Condition:
    """Deterministic between-subject condition assignment:
    sha256(seed:participant_id) mod 3. Between-subject (each participant
    sees exactly one condition, never all three) avoids the learning/
    contamination effect a within-subject design would create if the
    same participant saw the same case's answer revealed by a later
    condition -- see docs/research/wg-study.md section 6 for the design
    rationale and its own stated limitation (larger between-subject
    sample size requirement)."""
    digest = hashlib.sha256(f"{STUDY_SEED}:{participant_id}".encode()).hexdigest()
    index = int(digest, 16) % len(ALL_CONDITIONS)
    return ALL_CONDITIONS[index]


def case_order(participant_id: str, case_ids: tuple[str, ...]) -> tuple[str, ...]:
    """Deterministic per-participant case-order randomization, to permit
    measuring order effects across the participant pool without any two
    participants necessarily seeing the same order."""
    rng = random.Random(f"{STUDY_SEED}:{participant_id}:order")
    ids = list(case_ids)
    rng.shuffle(ids)
    return tuple(ids)


def lookup_correct_answer(
    key: answer_key_module.CaseAnswerKey, chain_pair: tuple[int, int] | None
) -> Answer:
    if chain_pair is None:
        if key.whole_case_answer is None:
            raise ValueError(f"case {key.case_id} has no whole-case question but chain_pair=None")
        return key.whole_case_answer
    for pairwise in key.pairwise_answers:
        if pairwise.chain_pair == chain_pair:
            return pairwise.correct_answer
    raise KeyError(f"no answer for chain_pair={chain_pair} in case {key.case_id}")


def record_response(
    *,
    participant_id: str,
    condition: Condition,
    case_id: str,
    question_id: str,
    chain_pair: tuple[int, int] | None,
    answer: Answer,
    response_time_ms: int,
    notes: str | None,
    answer_keys_by_case: dict[str, answer_key_module.CaseAnswerKey],
    is_developer_validation: bool = False,
) -> ParticipantResponse:
    correct = lookup_correct_answer(answer_keys_by_case[case_id], chain_pair)
    response = ParticipantResponse(
        participant_id=participant_id,
        condition=condition,
        case_id=case_id,
        question_id=question_id,
        answer=answer,
        correct_answer=correct,
        response_time_ms=response_time_ms,
        timestamp=datetime.now(UTC).isoformat(),
        optional_notes=notes,
        is_developer_validation=is_developer_validation,
    )
    storage.append_response(response)
    return response
