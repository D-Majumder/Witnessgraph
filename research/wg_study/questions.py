"""Question generation for a ``StudyCase``.

WG-Study asks pairwise questions ("for chain i and chain j, are their
root evidence sets SHARED, DISJOINT, or INDETERMINATE from the
information shown") for EVERY case with 2 or more chains -- not only
cases whose ground truth happens to be a partial-overlap case. This is a
deliberate design choice: generating a different question *format*
(single question vs. several pairwise questions) depending on ground
truth would itself leak a structural signal about which fixture class a
case belongs to. Asking uniformly-pairwise questions avoids that, and a
case with fully shared or fully disjoint roots is simply the case where
every pairwise answer happens to agree -- a valid degenerate case, not a
special format.

A case with fewer than 2 chains (WG-Study's negative control) instead
asks one single question, since no pair exists to ask about.

This module imports only ``model`` -- like ``presentation.py``, it never
imports ``answer_key``.
"""

from __future__ import annotations

from research.wg_study.model import Question, StudyCase


def generate_questions(case: StudyCase) -> tuple[Question, ...]:
    n = len(case.chains)
    if n < 2:
        return (
            Question(
                case_id=case.case_id,
                question_id=f"{case.case_id}-q-single",
                chain_pair=None,
                prompt=(
                    f"Only one relevant chain connects {case.source_entity_label} to "
                    f"{case.target_entity_label} in this case. Is there a second, "
                    "distinct chain here whose root evidence could be compared as "
                    "shared or disjoint?"
                ),
            ),
        )

    questions = []
    for i in range(n):
        for j in range(i + 1, n):
            questions.append(
                Question(
                    case_id=case.case_id,
                    question_id=f"{case.case_id}-q-{i + 1}-{j + 1}",
                    chain_pair=(i, j),
                    prompt=(
                        f"For chain {i + 1} and chain {j + 1} connecting "
                        f"{case.source_entity_label} to {case.target_entity_label}: "
                        "based only on the information shown for this case, are "
                        "their root evidence sets SHARED, DISJOINT, or is this "
                        "INDETERMINATE from what is shown?"
                    ),
                )
            )
    return tuple(questions)
