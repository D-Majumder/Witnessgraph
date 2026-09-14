"""Tracked gap findings: list/get/acknowledge -- thin wrappers over
``store``/``correlate.tracking``.

Three genuinely distinct tiers exist here, and this module never blurs
them (see ``docs/phase-ui-v1-architecture-design.md`` §10): the
structural analysis itself (``gaps_service.analyze_gaps``, mechanically
re-derived, no persisted identity), a *tracked* finding (a stable
identity for that same structural fact, from ``gaps_service.track_gaps``),
and this module's own ``ack_finding`` -- an analyst's review annotation
attached to a tracked finding. ``status=reviewed`` means only "an
analyst looked at this," never "this was validated" -- see
``TrackedGapFinding``'s own docstring. This module never invents a
"resolved"/"confirmed" status; only the three that already exist on
``FindingStatus`` (open, reviewed, dismissed) are ever accepted.
"""

from __future__ import annotations

from datetime import UTC, datetime

from witnessgraph.core.tracked_finding import FindingStatus
from witnessgraph.correlate.tracking import is_still_reproduced, tracked_finding_to_json
from witnessgraph.service.errors import TrackedFindingNotFoundError, ValidationError
from witnessgraph.store.case import Case


def list_findings(case: Case) -> list[dict[str, object]]:
    findings = sorted(case.store.list_tracked_findings(), key=lambda f: f.id)
    return [
        tracked_finding_to_json(f, still_reproduced=is_still_reproduced(case.store, f))
        for f in findings
    ]


def get_finding(case: Case, finding_id: str) -> dict[str, object]:
    finding = case.store.get_tracked_finding(finding_id)
    if finding is None:
        raise TrackedFindingNotFoundError(finding_id)
    return tracked_finding_to_json(
        finding, still_reproduced=is_still_reproduced(case.store, finding)
    )


def ack_finding(
    case: Case, finding_id: str, *, status: FindingStatus, by: str, note: str | None
) -> dict[str, object]:
    """Replace a tracked finding's review annotation.

    ``by`` is required and must not be blank/whitespace-only -- an
    analyst identity is never invented or inferred (mirrors
    ``cli.main.findings_ack``'s own validation exactly). This REPLACES
    the existing status/attribution/note; there is no history table.
    """
    if not by.strip():
        raise ValidationError(
            "by must not be blank or whitespace-only -- an analyst identity is never "
            "invented or inferred by this tool"
        )
    try:
        updated = case.store.annotate_tracked_finding(
            finding_id,
            status=status,
            annotated_by=by,
            annotated_at=datetime.now(UTC),
            note=note,
        )
    except ValueError as exc:
        raise TrackedFindingNotFoundError(finding_id) from exc
    return tracked_finding_to_json(
        updated, still_reproduced=is_still_reproduced(case.store, updated)
    )
