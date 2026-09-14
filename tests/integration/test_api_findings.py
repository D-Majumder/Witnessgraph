"""witnessgraph.api: timeline, evidence browsing, gaps, contradiction
tracking, and the findings/contradiction-findings acknowledgement
workflow (UI v1, second pass).

Same TestClient-against-a-real-case style as test_api.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from witnessgraph.api.app import create_app
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.case_dir = tmp_path / "case"
        self.case = Case.create(self.case_dir)

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

    def client(self) -> TestClient:
        self.case.record_manifest()
        self.case.close()
        return TestClient(create_app(self.case_dir))


def _contradiction_case(tmp_path: Path) -> tuple[_Fixture, str]:
    f = _Fixture(tmp_path)
    ev1 = f.evidence("jsonl", "a:1")
    ev2 = f.evidence("syslog", "b:1")
    event = f.event("logon", (ev1.id,))
    f.assertion(event.id, NOW, ev1.id, asserted_by="analyst1")
    f.assertion(event.id, NOW + timedelta(hours=1), ev2.id, asserted_by="analyst2")
    return f, event.id


def _gap_case(tmp_path: Path) -> _Fixture:
    f = _Fixture(tmp_path)
    ev_a = f.evidence("hostA", "a:1", source_id="hostA")
    ev_b = f.evidence("hostB", "b:1", source_id="hostB")
    event_a = f.event("heartbeat", (ev_a.id,))
    f.assertion(event_a.id, NOW, ev_a.id)
    f.assertion(event_a.id, NOW + timedelta(seconds=1000), ev_a.id)
    for i in range(2):
        e = f.event(f"hb-{i}", (ev_b.id,))
        f.assertion(e.id, NOW + timedelta(seconds=500 + i), ev_b.id)
    return f


# -- /timeline --------------------------------------------------------------


def test_timeline_sorted_and_filterable(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    ev = f.evidence("jsonl", "a:1")
    later = f.event("process_start", (ev.id,))
    earlier = f.event("logon", (ev.id,))
    f.assertion(later.id, NOW + timedelta(minutes=5), ev.id)
    f.assertion(earlier.id, NOW, ev.id)
    client = f.client()

    response = client.get("/timeline")
    assert response.status_code == 200
    assert [e["id"] for e in response.json()] == [earlier.id, later.id]

    filtered = client.get("/timeline", params={"event_type": "logon"})
    assert [e["event_type"] for e in filtered.json()] == ["logon"]


def test_timeline_empty_case_returns_empty_list(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    client = f.client()
    response = client.get("/timeline")
    assert response.status_code == 200
    assert response.json() == []


# -- /evidence (list) -------------------------------------------------------


def test_list_evidence(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    f.evidence("jsonl", "a:1")
    f.evidence("syslog", "b:1")
    client = f.client()
    response = client.get("/evidence")
    assert response.status_code == 200
    assert len(response.json()) == 2

    filtered = client.get("/evidence", params={"source_adapter": "syslog"})
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["source_adapter"] == "syslog"


# -- /contradictions, /contradictions/track ---------------------------------


def test_track_contradictions_then_list_findings(tmp_path: Path) -> None:
    f, _event_id = _contradiction_case(tmp_path)
    client = f.client()

    detected = client.get("/contradictions")
    assert len(detected.json()) == 1

    tracked = client.post("/contradictions/track")
    assert tracked.status_code == 200
    assert tracked.json() == {"new": 1, "already_tracked": 0}

    again = client.post("/contradictions/track")
    assert again.json() == {"new": 0, "already_tracked": 1}

    findings = client.get("/contradiction-findings")
    assert len(findings.json()) == 1
    assert findings.json()[0]["status"] == "open"


def test_ack_contradiction_finding(tmp_path: Path) -> None:
    f, _event_id = _contradiction_case(tmp_path)
    client = f.client()
    client.post("/contradictions/track")
    finding_id = client.get("/contradiction-findings").json()[0]["id"]

    response = client.post(
        f"/contradiction-findings/{finding_id}/ack",
        json={"status": "reviewed", "by": "analyst1", "note": "looked into it"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "reviewed"
    assert body["annotated_by"] == "analyst1"
    assert "still_reproduced" not in body


def test_ack_contradiction_finding_blank_by_is_400(tmp_path: Path) -> None:
    f, _event_id = _contradiction_case(tmp_path)
    client = f.client()
    client.post("/contradictions/track")
    finding_id = client.get("/contradiction-findings").json()[0]["id"]

    response = client.post(
        f"/contradiction-findings/{finding_id}/ack", json={"status": "reviewed", "by": "   "}
    )
    assert response.status_code == 400


def test_ack_unknown_contradiction_finding_is_404(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    client = f.client()
    response = client.post(
        "/contradiction-findings/nope/ack", json={"status": "reviewed", "by": "analyst"}
    )
    assert response.status_code == 404


def test_ack_contradiction_finding_rejects_invalid_status(tmp_path: Path) -> None:
    """Only open/reviewed/dismissed are ever accepted -- never a fabricated
    'validated'/'confirmed' status."""
    f, _event_id = _contradiction_case(tmp_path)
    client = f.client()
    client.post("/contradictions/track")
    finding_id = client.get("/contradiction-findings").json()[0]["id"]

    response = client.post(
        f"/contradiction-findings/{finding_id}/ack",
        json={"status": "validated", "by": "analyst1"},
    )
    assert response.status_code == 422


# -- /gaps, /gaps/track -------------------------------------------------


def test_gaps_requires_min_gap_seconds(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    client = f.client()
    response = client.get("/gaps")
    assert response.status_code == 422


def test_analyze_and_track_gaps(tmp_path: Path) -> None:
    f = _gap_case(tmp_path)
    client = f.client()

    analyzed = client.get(
        "/gaps", params={"min_gap_seconds": 60, "min_corroborating_events": 2}
    )
    assert analyzed.status_code == 200
    assert len(analyzed.json()["findings"]) == 1

    tracked = client.post(
        "/gaps/track", params={"min_gap_seconds": 60, "min_corroborating_events": 2}
    )
    assert tracked.status_code == 200
    assert tracked.json() == {"new": 1, "already_tracked": 0}

    findings = client.get("/findings")
    assert len(findings.json()) == 1
    assert findings.json()[0]["still_reproduced"] is True


def test_ack_finding(tmp_path: Path) -> None:
    f = _gap_case(tmp_path)
    client = f.client()
    client.post("/gaps/track", params={"min_gap_seconds": 60, "min_corroborating_events": 2})
    finding_id = client.get("/findings").json()[0]["id"]

    response = client.post(
        f"/findings/{finding_id}/ack", json={"status": "dismissed", "by": "analyst2"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "dismissed"
    assert body["annotated_by"] == "analyst2"


def test_get_unknown_finding_is_404(tmp_path: Path) -> None:
    f = _Fixture(tmp_path)
    client = f.client()
    response = client.get("/findings/nope")
    assert response.status_code == 404
    assert response.json() == {"detail": "no such tracked finding: nope"}
