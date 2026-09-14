"""Structural TimeAssertion conflicts -- a thin wrapper over ``correlate.contradictions``.

Mirrors ``cli.main.contradictions``'s JSON path exactly. Read-only,
parameter-free (unlike gap analysis), so it is included in the first
vertical slice even though the Contradictions view itself is a
SHOULD-HAVE (see ``docs/phase-ui-v1-architecture-design.md`` §17): the
service/analysis support already exists in full and nothing new needs to
be built to expose it.
"""

from __future__ import annotations

from witnessgraph.correlate.contradictions import contradictions_to_json, detect_time_contradictions
from witnessgraph.store.case import Case


def list_contradictions(case: Case) -> list[dict[str, object]]:
    return contradictions_to_json(detect_time_contradictions(case.store))
