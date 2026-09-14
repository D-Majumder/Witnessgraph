"""Structural TimeAssertion conflicts -- a thin wrapper over
``correlate.contradictions``/``correlate.contradiction_tracking``.

Mirrors ``cli.main.contradictions``'s JSON path exactly, including its
read-then-persist ordering for ``--track``: the full, read-only
detection always completes before any persistence is attempted.
"""

from __future__ import annotations

from witnessgraph.correlate.contradiction_tracking import track_contradictions
from witnessgraph.correlate.contradictions import contradictions_to_json, detect_time_contradictions
from witnessgraph.store.case import Case


def list_contradictions(case: Case) -> list[dict[str, object]]:
    return contradictions_to_json(detect_time_contradictions(case.store))


def track_detected_contradictions(case: Case) -> dict[str, object]:
    """Re-run detection and persist each contradiction as a
    TrackedTimeContradiction (insert-if-absent). Returns
    ``{"new": N, "already_tracked": M}``, mirroring the CLI's own
    ``--track`` summary exactly."""
    found = detect_time_contradictions(case.store)
    with case.transaction():
        outcomes = track_contradictions(case.store, found)
    new_count = sum(1 for o in outcomes if o.newly_created)
    return {"new": new_count, "already_tracked": len(outcomes) - new_count}
