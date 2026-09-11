"""DESIGN.md principle 3: TimeAssertions are preserved, not silently collapsed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from witnessgraph.core.time_model import TimeAssertion, TimePrecision

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _assertion(value: datetime, precision: TimePrecision, subject: str = "evt-1") -> TimeAssertion:
    return TimeAssertion(
        subject_event_id=subject,
        value=value,
        precision=precision,
        source_evidence_id="ev-1",
        asserted_by="adapter:test",
        created_at=NOW,
    )


def test_identical_exact_assertions_do_not_disagree() -> None:
    a = _assertion(NOW, TimePrecision.EXACT)
    b = _assertion(NOW, TimePrecision.EXACT)
    assert not a.disagrees_with(b)


def test_exact_assertions_one_second_apart_disagree() -> None:
    a = _assertion(NOW, TimePrecision.EXACT)
    b = _assertion(NOW + timedelta(seconds=1), TimePrecision.EXACT)
    assert a.disagrees_with(b)
    assert b.disagrees_with(a)


def test_minute_precision_tolerates_small_gap() -> None:
    a = _assertion(NOW, TimePrecision.MINUTE)
    b = _assertion(NOW + timedelta(seconds=30), TimePrecision.MINUTE)
    assert not a.disagrees_with(b)


def test_minute_precision_does_not_tolerate_large_gap() -> None:
    a = _assertion(NOW, TimePrecision.MINUTE)
    b = _assertion(NOW + timedelta(hours=1), TimePrecision.MINUTE)
    assert a.disagrees_with(b)


def test_different_subjects_never_disagree() -> None:
    a = _assertion(NOW, TimePrecision.EXACT, subject="evt-1")
    b = _assertion(NOW + timedelta(days=1), TimePrecision.EXACT, subject="evt-2")
    assert not a.disagrees_with(b)
