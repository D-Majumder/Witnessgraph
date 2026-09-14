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
    """Find pairs of TimeAssertions about the same event that cannot both be true.

    Return order is NOT independently guaranteed deterministic by this
    function alone (it follows ``store.list_time_assertions()``'s own,
    storage-incidental grouping order) -- a caller needing a stable,
    presentation-ready order must sort explicitly, exactly as
    :func:`contradictions_to_json` already does. This mirrors
    ``correlate.graph``'s own "unordered collection, sort before use"
    posture toward ``Store.list_relationships()``.
    """
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


def _assertion_to_json(assertion: TimeAssertion) -> dict[str, object]:
    # ``value`` is passed through as a raw datetime, not pre-stringified --
    # core.ids.canonical_json_bytes applies its own UTC/"Z" normalization
    # at encoding time (see that module), and every other datetime field
    # in this codebase's JSON output (report.render_json included) relies
    # on the same encoder-side normalization rather than doing it here.
    return {
        "id": assertion.id,
        "value": assertion.value,
        "precision": assertion.precision.value,
        "source_evidence_id": assertion.source_evidence_id,
    }


def contradictions_to_json(contradictions: list[TimeContradiction]) -> list[dict[str, object]]:
    """A plain dict/list tree for ``contradictions``, deterministically
    ordered regardless of the input list's own order -- pass to
    ``core.ids.canonical_json_bytes`` for encoding, exactly like
    ``correlate.graph``'s own ``*_to_json`` builders.

    Field selection matches what ``report.render``/``report.render_json``
    already consider a contradiction's reportable shape: the subject
    event id and the two disagreeing assertions (id, value, precision,
    source_evidence_id) -- never ``asserted_by``/``created_at``, which
    those two renderers also omit. The two assertions are always ordered
    ascending by id (never the incidental ``assertion_a``/``assertion_b``
    pairing order ``detect_time_contradictions`` happened to produce
    them in), exactly mirroring ``TrackedTimeContradiction``'s own
    canonicalization of the same pair.
    """
    ordered = sorted(
        contradictions,
        key=lambda c: (c.subject_event_id, c.assertion_a.id, c.assertion_b.id),
    )
    result: list[dict[str, object]] = []
    for c in ordered:
        assertions = sorted([c.assertion_a, c.assertion_b], key=lambda a: a.id)
        result.append(
            {
                "subject_event_id": c.subject_event_id,
                "assertions": [_assertion_to_json(a) for a in assertions],
            }
        )
    return result
