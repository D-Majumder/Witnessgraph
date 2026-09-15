"""Local-only, anonymous response storage.

Security/privacy properties (``docs/research/wg-study.md`` section 14):

- local filesystem only -- no network call, no cloud upload, anywhere in
  this module;
- one append-only JSON-Lines file per record class (real participant
  responses vs. developer-validation responses), kept physically
  separate so the two can never be silently merged;
- the output directory is always either the module's own fixed ``data/``
  directory or an explicit ``Path`` the CALLER constructed in code --
  this module never builds a path by concatenating a participant-
  supplied string, so a malicious ``participant_id`` cannot cause a path
  traversal;
- the only personally-identifying-adjacent field in a stored record is
  the caller-supplied, expected-to-be-anonymous ``participant_id`` (see
  ``model.ParticipantResponse``'s docstring).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from research.wg_study.model import Answer, Condition, ParticipantResponse

DATA_DIR = Path(__file__).resolve().parent / "data"
PARTICIPANT_RESPONSES_FILE = DATA_DIR / "participant_responses.jsonl"
DEV_VALIDATION_FILE = DATA_DIR / "developer_validation_responses.jsonl"


def _target_file(is_developer_validation: bool, directory: Path) -> Path:
    name = DEV_VALIDATION_FILE.name if is_developer_validation else PARTICIPANT_RESPONSES_FILE.name
    return directory / name


def _response_to_record(response: ParticipantResponse) -> dict[str, object]:
    record = asdict(response)
    record["condition"] = response.condition.value
    record["answer"] = response.answer.value
    record["correct_answer"] = response.correct_answer.value
    return record


def append_response(response: ParticipantResponse, *, out_dir: Path | None = None) -> Path:
    """Appends one response as one JSON line to the appropriate file.
    ``out_dir`` defaults to this module's fixed, safe ``data/``
    directory; if a caller passes an explicit directory it must be a
    ``Path`` the caller constructed directly (never built from raw
    participant input)."""
    directory = out_dir if out_dir is not None else DATA_DIR
    directory.mkdir(parents=True, exist_ok=True)
    target = _target_file(response.is_developer_validation, directory)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_response_to_record(response), sort_keys=True))
        f.write("\n")
    return target


def _record_to_response(raw: dict[str, Any]) -> ParticipantResponse:
    return ParticipantResponse(
        participant_id=str(raw["participant_id"]),
        condition=Condition(raw["condition"]),
        case_id=str(raw["case_id"]),
        question_id=str(raw["question_id"]),
        answer=Answer(raw["answer"]),
        correct_answer=Answer(raw["correct_answer"]),
        response_time_ms=int(raw["response_time_ms"]),
        timestamp=str(raw["timestamp"]),
        optional_notes=(None if raw.get("optional_notes") is None else str(raw["optional_notes"])),
        is_developer_validation=bool(raw["is_developer_validation"]),
    )


def load_responses(path: Path) -> list[ParticipantResponse]:
    """Loads every response recorded in ``path``. Returns an empty list,
    never an error, when the file does not exist yet -- an empty study
    dataset is a normal, expected state, not a failure."""
    if not path.exists():
        return []
    responses = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        responses.append(_record_to_response(json.loads(stripped)))
    return responses
