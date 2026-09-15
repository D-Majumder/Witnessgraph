"""WG-Study ground truth.

Physically separate from ``model.py``'s participant-facing types and
from ``presentation.py``'s rendering code, on purpose: this is the one
place a case's correct answer(s) live. ``presentation.py`` (what a
participant actually sees while answering) must never import this
module -- enforced by
``tests/unit/test_wg_study.py::test_presentation_module_never_imports_answer_key``.

Every ``CaseAnswerKey`` is built by ``case_builder.py`` from a WG-Bench
fixture's own independently-authored ``GroundTruthV2.expected_chains``
labels (never from calling ``analyze_paths_evidence_overlap()`` and
never by copying its output) -- see ``case_builder.py``'s module
docstring for exactly how.
"""

from __future__ import annotations

from dataclasses import dataclass

from research.wg_study.model import Answer


@dataclass(frozen=True)
class PairwiseAnswer:
    chain_pair: tuple[int, int]
    correct_answer: Answer


@dataclass(frozen=True)
class CaseAnswerKey:
    case_id: str
    #: The underlying WG-Bench fixture id this case's topology and
    #: ground truth were drawn from -- audit traceability only, never
    #: shown to a participant.
    fixture_id: str
    answer_key_version: str
    #: The single question's correct answer for a <2-chain
    #: (negative-control) case; ``None`` for every 2+-chain case (those
    #: are answered entirely via ``pairwise_answers``).
    whole_case_answer: Answer | None
    pairwise_answers: tuple[PairwiseAnswer, ...]
    #: WG-Bench's own root_sets_disjoint/root_sets_partial_overlap
    #: fields, retained for audit/report cross-referencing only.
    ground_truth_root_sets_disjoint: bool | None
    ground_truth_root_sets_partial_overlap: bool
    notes: str
