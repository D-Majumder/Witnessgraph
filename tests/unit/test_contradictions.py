"""Structural TimeAssertion contradiction detection (no ML/LLM -- DESIGN.md principle 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _assertion(
    subject: str, value: datetime, precision: TimePrecision = TimePrecision.EXACT
) -> TimeAssertion:
    return TimeAssertion(
        subject_event_id=subject,
        value=value,
        precision=precision,
        source_evidence_id="ev-1",
        asserted_by="adapter:test",
        created_at=NOW,
    )


def test_no_contradictions_for_empty_case(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    assert detect_time_contradictions(case.store) == []
    case.close()


def test_agreeing_assertions_produce_no_contradiction(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.store.put_time_assertion(_assertion("evt-1", NOW))
    case.store.put_time_assertion(_assertion("evt-1", NOW))
    assert detect_time_contradictions(case.store) == []
    case.close()


def test_disagreeing_assertions_are_detected(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.store.put_time_assertion(_assertion("evt-1", NOW))
    case.store.put_time_assertion(_assertion("evt-1", NOW + timedelta(hours=2)))
    found = detect_time_contradictions(case.store)
    assert len(found) == 1
    assert found[0].subject_event_id == "evt-1"
    case.close()


def test_contradictions_scoped_per_subject_event(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.store.put_time_assertion(_assertion("evt-1", NOW))
    case.store.put_time_assertion(_assertion("evt-2", NOW + timedelta(days=5)))
    assert detect_time_contradictions(case.store) == []
    case.close()


def test_three_way_disagreement_detects_all_pairs(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.store.put_time_assertion(_assertion("evt-1", NOW))
    case.store.put_time_assertion(_assertion("evt-1", NOW + timedelta(hours=3)))
    case.store.put_time_assertion(_assertion("evt-1", NOW + timedelta(hours=6)))
    found = detect_time_contradictions(case.store)
    assert len(found) == 3  # C(3,2)
    case.close()
