"""WG-Study's "study freeze" package descriptor.

A frozen study manifest captures everything a stored dataset's
``study_version`` field implicitly promises: the exact case set,
condition/question definitions, answer-key version, randomization
protocol, and software version that produced it. Given a manifest and a
dataset that declares a matching ``study_version``, an analyst can be
confident the two actually agree on what every ``case_id``/
``question_id``/``condition`` in the dataset means -- see
``dataset_validation.py``, which uses ``case_question_ids()`` from this
module to reject a record naming a case/question outside the frozen
manifest.

This module computes the manifest deterministically from the current
case builder and answer key -- it does not read or write a file itself;
``python -m research.wg_study freeze`` is the command that prints it (see
``docs/research/wg-study.md`` for the procedure this implements).
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass

from research.wg_study import case_builder
from research.wg_study import questions as questions_module
from research.wg_study.model import ALL_CONDITIONS, STUDY_VERSION
from research.wg_study.runner import STUDY_SEED


@dataclass(frozen=True)
class StudyManifest:
    study_version: str
    answer_key_version: str
    case_count: int
    case_ids: tuple[str, ...]
    condition_values: tuple[str, ...]
    randomization_seed: str
    randomization_protocol: str
    case_manifest_hash: str
    python_version: str
    platform_summary: str


def case_question_ids() -> dict[str, set[str]]:
    """``case_id -> {question_id, ...}`` for WG-Study's current fixed
    case manifest -- used by ``dataset_validation.py`` to reject a record
    naming a case/question the frozen manifest does not define."""
    cases_and_keys = case_builder.build_all_cases()
    return {
        study_case.case_id: {q.question_id for q in questions_module.generate_questions(study_case)}
        for study_case, _key in cases_and_keys
    }


def _canonical_case_manifest_bytes() -> bytes:
    cases_and_keys = case_builder.build_all_cases()
    manifest = [
        {
            "case_id": study_case.case_id,
            "case_type": study_case.case_type,
            "path_count": study_case.path_count,
            "chain_count": len(study_case.chains),
            "fixture_id": key.fixture_id,
            "answer_key_version": key.answer_key_version,
            "question_ids": sorted(
                q.question_id for q in questions_module.generate_questions(study_case)
            ),
        }
        for study_case, key in cases_and_keys
    ]
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")


def build_manifest() -> StudyManifest:
    """Deterministically (re)computes the current study manifest. Two
    calls in the same repository state always return byte-identical
    ``case_manifest_hash`` -- see
    ``tests/unit/test_wg_study_pilot_package.py::test_manifest_is_deterministic``."""
    cases_and_keys = case_builder.build_all_cases()
    case_ids = tuple(study_case.case_id for study_case, _key in cases_and_keys)
    answer_key_versions = {key.answer_key_version for _case, key in cases_and_keys}
    if len(answer_key_versions) != 1:
        raise ValueError(
            f"expected exactly one answer_key_version across cases, got {answer_key_versions}"
        )
    (answer_key_version,) = answer_key_versions

    digest = hashlib.sha256(_canonical_case_manifest_bytes()).hexdigest()

    return StudyManifest(
        study_version=STUDY_VERSION,
        answer_key_version=answer_key_version,
        case_count=len(cases_and_keys),
        case_ids=case_ids,
        condition_values=tuple(c.value for c in ALL_CONDITIONS),
        randomization_seed=STUDY_SEED,
        randomization_protocol=(
            "condition = sha256(seed:participant_id) mod 3 (between-subject); "
            "case_order = random.Random(seed:participant_id:order).shuffle (per-participant, "
            "deterministic). See research/wg_study/runner.py."
        ),
        case_manifest_hash=digest,
        python_version=sys.version.split()[0],
        platform_summary=platform.platform(),
    )


def manifest_to_dict(manifest: StudyManifest) -> dict[str, object]:
    return {
        "study_version": manifest.study_version,
        "answer_key_version": manifest.answer_key_version,
        "case_count": manifest.case_count,
        "case_ids": list(manifest.case_ids),
        "condition_values": list(manifest.condition_values),
        "randomization_seed": manifest.randomization_seed,
        "randomization_protocol": manifest.randomization_protocol,
        "case_manifest_hash": manifest.case_manifest_hash,
        "python_version": manifest.python_version,
        "platform_summary": manifest.platform_summary,
    }
