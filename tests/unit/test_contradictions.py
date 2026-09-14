"""Structural TimeAssertion contradiction detection (no ML/LLM -- DESIGN.md principle 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.correlate.contradictions import contradictions_to_json, detect_time_contradictions
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


# -- contradictions_to_json ----------------------------------------------------


def test_contradictions_to_json_empty_list_is_empty_array() -> None:
    assert contradictions_to_json([]) == []


def test_contradictions_to_json_shape(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.store.put_time_assertion(_assertion("evt-1", NOW))
    case.store.put_time_assertion(_assertion("evt-1", NOW + timedelta(hours=2)))
    found = detect_time_contradictions(case.store)
    doc = contradictions_to_json(found)
    assert len(doc) == 1
    entry = doc[0]
    assert entry["subject_event_id"] == "evt-1"
    assert len(entry["assertions"]) == 2
    assert entry["assertions"][0]["id"] < entry["assertions"][1]["id"]  # canonical order
    for assertion_json in entry["assertions"]:
        assert set(assertion_json) == {"id", "value", "precision", "source_evidence_id"}
    case.close()


def test_contradictions_to_json_deterministic_regardless_of_input_order(tmp_path: Path) -> None:
    """detect_time_contradictions's own return order is not independently
    guaranteed (see its docstring) -- contradictions_to_json must produce
    the same output regardless of the order it is handed."""
    case = Case.create(tmp_path / "case")
    case.store.put_time_assertion(_assertion("evt-1", NOW))
    case.store.put_time_assertion(_assertion("evt-1", NOW + timedelta(hours=3)))
    case.store.put_time_assertion(_assertion("evt-2", NOW))
    case.store.put_time_assertion(_assertion("evt-2", NOW + timedelta(hours=5)))
    found = detect_time_contradictions(case.store)
    assert len(found) == 2
    forward = contradictions_to_json(found)
    backward = contradictions_to_json(list(reversed(found)))
    assert forward == backward
    case.close()
