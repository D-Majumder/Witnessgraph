"""Structural detection of conflicting TimeAssertions.

Pure and deterministic -- no ML/LLM involved (DESIGN.md principle 7 and
the explicit v0.1 scope decision to exclude ML-based correlation). Two
assertions about the same NormalizedEvent "disagree" when their claimed
values differ by more than the sum of their stated precisions; see
TimeAssertion.disagrees_with.
"""

from __future__ import annotations

from dataclasses import dataclass

from witnessgraph.core.time_model import TimeAssertion
from witnessgraph.store.base import Store


@dataclass(frozen=True)
class TimeContradiction:
    subject_event_id: str
    assertion_a: TimeAssertion
    assertion_b: TimeAssertion


def detect_time_contradictions(store: Store) -> list[TimeContradiction]:
    """Find pairs of TimeAssertions about the same event that cannot both be true."""
    by_subject: dict[str, list[TimeAssertion]] = {}
    for assertion in store.list_time_assertions():
        by_subject.setdefault(assertion.subject_event_id, []).append(assertion)

    contradictions: list[TimeContradiction] = []
    for assertions in by_subject.values():
        ordered = sorted(assertions, key=lambda a: a.id)
        for i in range(len(ordered)):
            for j in range(i + 1, len(ordered)):
                if ordered[i].disagrees_with(ordered[j]):
                    contradictions.append(
                        TimeContradiction(
                            subject_event_id=ordered[i].subject_event_id,
                            assertion_a=ordered[i],
                            assertion_b=ordered[j],
                        )
                    )
    return contradictions
