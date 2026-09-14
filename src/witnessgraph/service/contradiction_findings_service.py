"""Tracked contradiction findings: list/get/acknowledge.

Structurally separate from ``findings_service`` (a contradiction id is
never looked up in the gap-finding table, and vice versa -- mirrors
``cli.main``'s own ``contradiction-findings`` vs. ``findings`` command
separation). ``status=reviewed``/``dismissed`` never mean the
contradiction has been resolved, adjudicated, or that either assertion
is more correct -- Witnessgraph does not determine which disagreeing
assertion is true. Deliberately no ``still_reproduced`` field: a
contradiction's own docstring is explicit that an always-true value
would convey no information.
"""

from __future__ import annotations

from datetime import UTC, datetime

from witnessgraph.core.tracked_finding import FindingStatus
from witnessgraph.correlate.contradiction_tracking import tracked_contradiction_to_json
from witnessgraph.service.errors import TrackedContradictionNotFoundError, ValidationError
from witnessgraph.store.case import Case


def list_contradiction_findings(case: Case) -> list[dict[str, object]]:
    tracked = sorted(case.store.list_tracked_contradictions(), key=lambda c: c.id)
    return [tracked_contradiction_to_json(c) for c in tracked]


def get_contradiction_finding(case: Case, contradiction_id: str) -> dict[str, object]:
    contradiction = case.store.get_tracked_contradiction(contradiction_id)
    if contradiction is None:
        raise TrackedContradictionNotFoundError(contradiction_id)
    return tracked_contradiction_to_json(contradiction)


def ack_contradiction_finding(
    case: Case, contradiction_id: str, *, status: FindingStatus, by: str, note: str | None
) -> dict[str, object]:
    """Replace a tracked contradiction's review annotation -- see
    ``findings_service.ack_finding``'s identical validation/replace
    semantics."""
    if not by.strip():
        raise ValidationError(
            "by must not be blank or whitespace-only -- an analyst identity is never "
            "invented or inferred by this tool"
        )
    try:
        updated = case.store.annotate_tracked_contradiction(
            contradiction_id,
            status=status,
            annotated_by=by,
            annotated_at=datetime.now(UTC),
            note=note,
        )
    except ValueError as exc:
        raise TrackedContradictionNotFoundError(contradiction_id) from exc
    return tracked_contradiction_to_json(updated)
