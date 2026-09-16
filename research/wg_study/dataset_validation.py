"""Integrity validation for a collected (or purportedly collected)
WG-Study participant dataset.

This module is deliberately separate from ``storage.py`` (raw JSONL
read/write) and from ``analysis.py`` (descriptive metrics over an
already-trusted list of ``ParticipantResponse`` objects). Its job is the
step in between: look at every raw JSON record in a dataset file and
decide, one record at a time, whether it is well-formed enough to enter
analysis at all -- never silently repairing or guessing a corrected
value for a malformed record.

A record is REJECTED (excluded, with a stated reason) rather than
"fixed" when it:

- is not valid JSON, or is missing a required field;
- names a ``study_version`` other than the dataset's own declared
  version (a "mixed study versions" dataset -- see ``model.STUDY_VERSION``);
- names a ``condition``, ``case_id``, or ``question_id`` that does not
  exist in WG-Study's current frozen case manifest (see ``manifest.py``);
- names an ``answer`` that is not one of the three defined ``Answer``
  values;
- has ``response_time_ms < 0`` (impossible negative timing);
- duplicates an earlier, otherwise-valid record's
  ``(participant_id, case_id, question_id)`` key (a participant is only
  expected to answer a given question once; a second record for the
  same key is flagged, not silently overwritten or averaged).

This module never fabricates a record for a missing response -- a
question a participant never answered simply does not appear in
``valid_responses``; ``analysis.py``'s ``missing_response_rate`` is the
place that turns an expected-but-absent response into a reported number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from research.wg_study.model import (
    ALL_CONDITIONS,
    STUDY_VERSION,
    Answer,
    Condition,
    ParticipantResponse,
)

_VALID_CONDITION_VALUES = {c.value for c in ALL_CONDITIONS}
_VALID_ANSWER_VALUES = {a.value for a in Answer}

_REQUIRED_FIELDS = (
    "participant_id",
    "condition",
    "case_id",
    "question_id",
    "answer",
    "correct_answer",
    "response_time_ms",
    "timestamp",
    "study_version",
    "is_developer_validation",
)


@dataclass(frozen=True)
class RejectedRecord:
    index: int
    reason: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class DatasetValidationReport:
    dataset_study_version: str
    total_records: int
    valid_responses: tuple[ParticipantResponse, ...]
    rejected: tuple[RejectedRecord, ...]

    @property
    def valid_count(self) -> int:
        return len(self.valid_responses)

    @property
    def rejected_count(self) -> int:
        return len(self.rejected)


def _reject(index: int, reason: str, raw: dict[str, Any]) -> RejectedRecord:
    return RejectedRecord(index=index, reason=reason, raw=raw)


def validate_dataset(
    raw_records: list[dict[str, Any]],
    *,
    known_case_question_ids: dict[str, set[str]] | None = None,
    expected_study_version: str = STUDY_VERSION,
) -> DatasetValidationReport:
    """Validates a list of already-JSON-decoded raw records (as produced
    by ``json.loads`` on one JSONL line each).

    ``known_case_question_ids`` maps ``case_id -> {question_id, ...}``
    from the current frozen case manifest; when given, a record naming
    an unknown case or question is rejected. Pass ``None`` to skip that
    check (e.g. when validating in isolation from the manifest).
    """
    valid: list[ParticipantResponse] = []
    rejected: list[RejectedRecord] = []
    seen_keys: set[tuple[str, str, str]] = set()

    for index, raw in enumerate(raw_records):
        missing = [f for f in _REQUIRED_FIELDS if f not in raw]
        if missing:
            rejected.append(_reject(index, f"missing required field(s): {missing}", raw))
            continue

        if raw["study_version"] != expected_study_version:
            rejected.append(
                _reject(
                    index,
                    (
                        f"study_version {raw['study_version']!r} does not match expected "
                        f"dataset version {expected_study_version!r} (mixed study versions)"
                    ),
                    raw,
                )
            )
            continue

        if raw["condition"] not in _VALID_CONDITION_VALUES:
            rejected.append(_reject(index, f"unknown condition {raw['condition']!r}", raw))
            continue

        if raw["answer"] not in _VALID_ANSWER_VALUES:
            rejected.append(_reject(index, f"malformed answer {raw['answer']!r}", raw))
            continue

        if raw["correct_answer"] not in _VALID_ANSWER_VALUES:
            rejected.append(
                _reject(index, f"malformed correct_answer {raw['correct_answer']!r}", raw)
            )
            continue

        try:
            response_time_ms = int(raw["response_time_ms"])
        except (TypeError, ValueError):
            rejected.append(
                _reject(index, f"non-integer response_time_ms {raw['response_time_ms']!r}", raw)
            )
            continue
        if response_time_ms < 0:
            rejected.append(_reject(index, f"impossible negative timing {response_time_ms}", raw))
            continue

        case_id = str(raw["case_id"])
        question_id = str(raw["question_id"])
        if known_case_question_ids is not None:
            if case_id not in known_case_question_ids:
                rejected.append(_reject(index, f"unknown case_id {case_id!r}", raw))
                continue
            if question_id not in known_case_question_ids[case_id]:
                rejected.append(
                    _reject(
                        index, f"unknown question_id {question_id!r} for case {case_id!r}", raw
                    )
                )
                continue

        participant_id = str(raw["participant_id"])
        key = (participant_id, case_id, question_id)
        if key in seen_keys:
            rejected.append(
                _reject(index, f"duplicate response for participant/case/question {key}", raw)
            )
            continue
        seen_keys.add(key)

        valid.append(
            ParticipantResponse(
                participant_id=participant_id,
                condition=Condition(raw["condition"]),
                case_id=case_id,
                question_id=question_id,
                answer=Answer(raw["answer"]),
                correct_answer=Answer(raw["correct_answer"]),
                response_time_ms=response_time_ms,
                timestamp=str(raw["timestamp"]),
                optional_notes=(
                    None if raw.get("optional_notes") is None else str(raw["optional_notes"])
                ),
                study_version=str(raw["study_version"]),
                is_developer_validation=bool(raw["is_developer_validation"]),
            )
        )

    return DatasetValidationReport(
        dataset_study_version=expected_study_version,
        total_records=len(raw_records),
        valid_responses=tuple(valid),
        rejected=tuple(rejected),
    )
