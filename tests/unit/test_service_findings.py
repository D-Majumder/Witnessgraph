"""witnessgraph.service: timeline, evidence browsing, gaps, contradiction
tracking, and the tracked-finding/tracked-contradiction acknowledgement
workflow (UI v1, second pass).

Mirrors cli.main's own gaps/contradictions/findings/contradiction-findings
commands exactly -- same validation, same read-then-persist ordering for
--track, same "reviewed never means validated" semantics. Builds a small
in-memory case directly against a real Case/SqliteStore, in the same
style as test_service.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.core.tracked_finding import FindingStatus
from witnessgraph.service import (
    contradiction_findings_service,
    contradictions_service,
    evidence_service,
    findings_service,
    gaps_service,
    timeline_service,
)
from witnessgraph.service.errors import (
    TrackedContradictionNotFoundError,
    TrackedFindingNotFoundError,
    ValidationError,
)
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.case = Case.create(tmp_path / "case")

    def evidence(
        self, source_adapter: str, locator: str, *, source_id: str | None = None
    ) -> EvidenceItem:
        item = EvidenceItem.create(
            raw_bytes=locator.encode(),
            source_adapter=source_adapter,
            adapter_version="0",
            source_locator=locator,
            collected_at=NOW,
            source_id=source_id,
        )
        self.case.store.put_evidence(item)
        return item

    def event(self, event_type: str, derived_from: tuple[str, ...]) -> NormalizedEvent:
        event = NormalizedEvent.create(
            event_type=event_type, derived_from=derived_from, created_at=NOW
        )
        self.case.store.put_normalized_event(event)
        return event

    def assertion(
        self, event_id: str, value: datetime, evidence_id: str, asserted_by: str = "analyst"
    ) -> TimeAssertion:
        ta = TimeAssertion.create(
            subject_event_id=event_id,
            value=value,
            precision=TimePrecision.SECOND,
            source_evidence_id=evidence_id,
            asserted_by=asserted_by,
            created_at=NOW,
        )
        self.case.store.put_time_assertion(ta)
        return ta

    def entity(self, entity_id: str, derived_from: tuple[str, ...]) -> Entity:
        ent = Entity(id=entity_id, entity_type="host", identifiers={}, derived_from=derived_from)
        self.case.store.put_entity(ent)
        return ent


# -- timeline_service ---------------------------------------------------


def test_get_timeline_sorted_earliest_first(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    ev = f.evidence("jsonl", "a:1")
    later = f.event("process_start", (ev.id,))
    earlier = f.event("logon", (ev.id,))
    f.assertion(later.id, NOW + timedelta(minutes=5), ev.id)
    f.assertion(earlier.id, NOW, ev.id)
    timeline = timeline_service.get_timeline(f.case)
    assert [entry["id"] for entry in timeline] == [earlier.id, later.id]
    f.case.close()


def test_get_timeline_filters_by_event_type(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    ev = f.evidence("jsonl", "a:1")
    f.event("logon", (ev.id,))
    f.event("process_start", (ev.id,))
    timeline = timeline_service.get_timeline(f.case, event_type="logon")
    assert [entry["event_type"] for entry in timeline] == ["logon"]
    f.case.close()


# -- evidence_service.list_evidence --------------------------------------


def test_list_evidence_sorted_and_filterable(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.evidence("syslog", "b:1")
    f.evidence("jsonl", "a:1")
    everything = evidence_service.list_evidence(f.case)
    assert [e["source_adapter"] for e in everything] == ["jsonl", "syslog"]
    only_jsonl = evidence_service.list_evidence(f.case, source_adapter="jsonl")
    assert len(only_jsonl) == 1
    assert only_jsonl[0]["source_adapter"] == "jsonl"
    f.case.close()


# -- gaps_service ---------------------------------------------------------


def test_analyze_gaps_invalid_min_corroborating_events_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(ValidationError):
        gaps_service.analyze_gaps(f.case, min_gap_seconds=60, min_corroborating_events=0)
    f.case.close()


def test_analyze_gaps_does_not_persist_anything(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    ev = f.evidence("jsonl", "a:1")
    f.event("logon", (ev.id,))
    gaps_service.analyze_gaps(f.case, min_gap_seconds=60)
    assert f.case.store.list_tracked_findings() == []
    f.case.close()


def test_track_gaps_persists_findings_and_is_idempotent(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    ev_a = f.evidence("hostA", "a:1", source_id="hostA")
    ev_b = f.evidence("hostB", "b:1", source_id="hostB")
    event_a = f.event("heartbeat", (ev_a.id,))
    # hostA active at t=0 and t=1000s; hostB active only around t=500s --
    # a gap in hostA's coverage while hostB has corroborating activity.
    f.assertion(event_a.id, NOW, ev_a.id)
    f.assertion(event_a.id, NOW + timedelta(seconds=1000), ev_a.id)
    for i in range(2):
        e = f.event(f"hb-{i}", (ev_b.id,))
        f.assertion(e.id, NOW + timedelta(seconds=500 + i), ev_b.id)

    first = gaps_service.track_gaps(
        f.case, min_gap_seconds=60, min_corroborating_events=2
    )
    assert first["new"] >= 1
    second = gaps_service.track_gaps(
        f.case, min_gap_seconds=60, min_corroborating_events=2
    )
    assert second["new"] == 0
    assert second["already_tracked"] == first["new"]
    f.case.close()


# -- contradictions_service.track_detected_contradictions -----------------


def test_track_detected_contradictions_persists_and_is_idempotent(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    ev1 = f.evidence("jsonl", "a:1")
    ev2 = f.evidence("syslog", "b:1")
    event = f.event("logon", (ev1.id,))
    f.assertion(event.id, NOW, ev1.id, asserted_by="analyst1")
    f.assertion(event.id, NOW + timedelta(hours=1), ev2.id, asserted_by="analyst2")

    first = contradictions_service.track_detected_contradictions(f.case)
    assert first == {"new": 1, "already_tracked": 0}
    second = contradictions_service.track_detected_contradictions(f.case)
    assert second == {"new": 0, "already_tracked": 1}
    f.case.close()


# -- findings_service -------------------------------------------------------


def _tracked_gap_finding_id(f: _Fixture) -> str:
    ev_a = f.evidence("hostA", "a:1", source_id="hostA")
    ev_b = f.evidence("hostB", "b:1", source_id="hostB")
    event_a = f.event("heartbeat", (ev_a.id,))
    f.assertion(event_a.id, NOW, ev_a.id)
    f.assertion(event_a.id, NOW + timedelta(seconds=1000), ev_a.id)
    for i in range(2):
        e = f.event(f"hb-{i}", (ev_b.id,))
        f.assertion(e.id, NOW + timedelta(seconds=500 + i), ev_b.id)
    outcome = gaps_service.track_gaps(f.case, min_gap_seconds=60, min_corroborating_events=2)
    assert outcome["new"] == 1
    return findings_service.list_findings(f.case)[0]["id"]


def test_get_finding_unknown_id_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(TrackedFindingNotFoundError):
        findings_service.get_finding(f.case, "nope")
    f.case.close()


def test_ack_finding_requires_non_blank_by(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    finding_id = _tracked_gap_finding_id(f)
    with pytest.raises(ValidationError):
        findings_service.ack_finding(
            f.case, finding_id, status=FindingStatus.REVIEWED, by="   ", note=None
        )
    f.case.close()


def test_ack_finding_sets_status_never_calls_it_validated(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    finding_id = _tracked_gap_finding_id(f)
    updated = findings_service.ack_finding(
        f.case, finding_id, status=FindingStatus.REVIEWED, by="analyst1", note="looked at it"
    )
    assert updated["status"] == "reviewed"
    assert updated["annotated_by"] == "analyst1"
    assert "still_reproduced" in updated
    # The three FindingStatus values are open/reviewed/dismissed -- nothing
    # in this codebase should ever accept or emit "validated"/"confirmed".
    assert updated["status"] not in ("validated", "confirmed", "true")
    f.case.close()


def test_ack_finding_unknown_id_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(TrackedFindingNotFoundError):
        findings_service.ack_finding(
            f.case, "nope", status=FindingStatus.REVIEWED, by="analyst", note=None
        )
    f.case.close()


# -- contradiction_findings_service ----------------------------------------


def _tracked_contradiction_id(f: _Fixture) -> str:
    ev1 = f.evidence("jsonl", "a:1")
    ev2 = f.evidence("syslog", "b:1")
    event = f.event("logon", (ev1.id,))
    f.assertion(event.id, NOW, ev1.id, asserted_by="analyst1")
    f.assertion(event.id, NOW + timedelta(hours=1), ev2.id, asserted_by="analyst2")
    contradictions_service.track_detected_contradictions(f.case)
    return contradiction_findings_service.list_contradiction_findings(f.case)[0]["id"]


def test_get_contradiction_finding_unknown_id_raises(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    with pytest.raises(TrackedContradictionNotFoundError):
        contradiction_findings_service.get_contradiction_finding(f.case, "nope")
    f.case.close()


def test_ack_contradiction_finding_never_resolves_which_assertion_is_true(
    tmp_path: Path,
) -> None:
    f = _Fixture(tmp_path)
    contradiction_id = _tracked_contradiction_id(f)
    updated = contradiction_findings_service.ack_contradiction_finding(
        f.case, contradiction_id, status=FindingStatus.DISMISSED, by="analyst1", note=None
    )
    assert updated["status"] == "dismissed"
    # A TrackedTimeContradiction never carries a "still_reproduced" field
    # (an always-true value would convey no information -- see its
    # to-json function's own docstring).
    assert "still_reproduced" not in updated
    f.case.close()


def test_ack_contradiction_finding_requires_non_blank_by(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    contradiction_id = _tracked_contradiction_id(f)
    with pytest.raises(ValidationError):
        contradiction_findings_service.ack_contradiction_finding(
            f.case, contradiction_id, status=FindingStatus.REVIEWED, by="", note=None
        )
    f.case.close()
