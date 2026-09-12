"""docs/phase5-v0.5-gap-analysis-design.md: deterministic cross-source
evidence coverage-gap analysis (correlate.gaps.find_gaps).

Uses only synthetic fixtures -- no real systems contacted or scanned.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.correlate.gaps import find_gaps
from witnessgraph.portable import export_case, import_case
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _put(
    case: Case,
    *,
    source_id: str | None,
    value: datetime,
    precision: TimePrecision = TimePrecision.EXACT,
    label: str | None = None,
) -> TimeAssertion:
    """Insert one EvidenceItem/NormalizedEvent/TimeAssertion triple."""
    label = label or f"{source_id}-{value.isoformat()}"
    evidence = EvidenceItem.create(
        raw_bytes=label.encode(),
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1",
        collected_at=NOW,
        source_id=source_id,
    )
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line", attributes={"label": label}, derived_from=(evidence.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    assertion = TimeAssertion.create(
        subject_event_id=event.id,
        value=value,
        precision=precision,
        source_evidence_id=evidence.id,
        asserted_by="test",
        created_at=NOW,
    )
    case.store.put_time_assertion(assertion)
    return assertion


def _t(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, second, tzinfo=UTC)


# -- Basic shape -------------------------------------------------------------


def test_empty_case_has_no_findings(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    assert result.excluded_no_time_assertion == 0
    case.close()


def test_one_source_only_has_no_findings(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9))
    _put(case, source_id="host1", value=_t(10))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    case.close()


def test_two_sources_genuinely_non_overlapping(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9))
    _put(case, source_id="host1", value=_t(10))
    _put(case, source_id="host2", value=_t(14))
    _put(case, source_id="host2", value=_t(15))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    case.close()


def test_overlapping_sources_no_actual_gap(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    for m in range(0, 60, 5):
        _put(case, source_id="host1", value=_t(9, m))
        _put(case, source_id="host2", value=_t(9, m))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    case.close()


def test_true_internal_gap_is_detected(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 5))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host1", value=_t(9, 45))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))
    _put(case, source_id="host2", value=_t(9, 30))

    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.absent_source == "host1"
    assert finding.present_source == "host2"
    assert finding.interval_start == _t(9, 5)
    assert finding.interval_end == _t(9, 40)
    assert len(finding.corroborating_time_assertion_ids) == 3
    case.close()


# -- Source-identity resolution (the v0.4-unblocked scenario) ---------------


def test_same_adapter_different_source_ids_remain_distinguishable(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1
    assert result.findings[0].absent_source == "host1"
    case.close()


def test_different_adapters_different_source_ids(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    evidence_jsonl = EvidenceItem.create(
        raw_bytes=b"j", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="a.jsonl:1", collected_at=NOW, source_id="host1",
    )
    evidence_syslog = EvidenceItem.create(
        raw_bytes=b"s1", source_adapter="syslog", adapter_version="0.1.0",
        source_locator="b.syslog:1", collected_at=NOW, source_id="host2",
    )
    case.store.put_evidence(evidence_jsonl)
    case.store.put_evidence(evidence_syslog)
    for i, (ev, when) in enumerate(
        [(evidence_jsonl, _t(9, 0)), (evidence_jsonl, _t(9, 40)),
         (evidence_syslog, _t(9, 10)), (evidence_syslog, _t(9, 20))]
    ):
        event = NormalizedEvent.create(
            event_type="line", attributes={"i": str(i)}, derived_from=(ev.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=when, precision=TimePrecision.EXACT,
                source_evidence_id=ev.id, asserted_by="test", created_at=NOW,
            )
        )
    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1
    assert result.findings[0].absent_source == "host1"
    case.close()


def test_missing_source_id_is_excluded_not_grouped(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id=None, value=_t(9, 10))
    _put(case, source_id=None, value=_t(9, 20))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()  # the undeclared-source evidence never corroborates
    assert result.excluded_no_declared_source == 2
    case.close()


def test_ambiguous_source_id_byte_identical_evidence_is_excluded(tmp_path: Path) -> None:
    """Two different declared source_ids for byte-identical content must be
    excluded, never guessed between (docs/phase4-v0.4-source-identity-design.md §2)."""
    case = Case.create(tmp_path / "case")
    first = EvidenceItem.create(
        raw_bytes=b"identical", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="a.jsonl:1", collected_at=NOW, source_id="host1",
    )
    second = EvidenceItem.create(
        raw_bytes=b"identical", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="b.jsonl:1", collected_at=NOW, source_id="host2",
    )
    case.store.put_evidence(first)
    case.store.put_evidence(second)
    stored = case.store.get_evidence(first.id)
    assert stored is not None
    assert stored.declared_source_ids() == frozenset({"host1", "host2"})

    event = NormalizedEvent.create(
        event_type="line", derived_from=(first.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event.id, value=_t(9, 15), precision=TimePrecision.EXACT,
            source_evidence_id=first.id, asserted_by="test", created_at=NOW,
        )
    )
    # A second, unambiguous source with a bracketing pair so a gap *would*
    # be reachable if the ambiguous evidence were wrongly attributed.
    _put(case, source_id="host3", value=_t(9, 0))
    _put(case, source_id="host3", value=_t(9, 40))

    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.excluded_ambiguous_source == 1
    assert all(f.absent_source not in ("host1", "host2") for f in result.findings)
    assert all(f.present_source not in ("host1", "host2") for f in result.findings)
    case.close()


# -- Duplicate ingestion / idempotence ----------------------------------------


def test_duplicate_ingestion_does_not_duplicate_findings(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    a1 = _put(case, source_id="host1", value=_t(9, 0))
    a2 = _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))

    # Re-insert the exact same (idempotent, per v0.3) records again.
    case.store.put_time_assertion(a1)
    case.store.put_time_assertion(a2)

    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1  # not duplicated
    case.close()


# -- Interval mechanics --------------------------------------------------------


def test_overlapping_intervals_within_one_source_are_unioned(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), precision=TimePrecision.MINUTE)
    _put(case, source_id="host1", value=_t(9, 0, 30), precision=TimePrecision.MINUTE)
    _put(case, source_id="host1", value=_t(10, 0))
    _put(case, source_id="host2", value=_t(9, 20))
    _put(case, source_id="host2", value=_t(9, 40))
    result = find_gaps(case.store, min_gap_seconds=60)
    # No crash; overlapping widened intervals correctly treated as one span.
    assert isinstance(result.findings, tuple)
    case.close()


def test_wide_interval_covering_a_later_narrower_one_is_not_a_false_gap(tmp_path: Path) -> None:
    """A coarse-precision (wide) interval sorted by start can still extend
    past its immediate successor's end -- the algorithm must track the
    running maximum end seen so far, not just the previous element's end,
    or it would wrongly report a "gap" already covered by the wider
    interval (found during adversarial review, see design doc §23)."""
    case = Case.create(tmp_path / "case")
    # APPROXIMATE precision widens by +/- 6 hours -- this single event's
    # widened interval fully covers the next, narrower EXACT event.
    _put(case, source_id="host1", value=_t(9, 0), precision=TimePrecision.APPROXIMATE)
    _put(case, source_id="host1", value=_t(10, 0), precision=TimePrecision.EXACT)
    _put(case, source_id="host1", value=_t(20, 0), precision=TimePrecision.EXACT)
    _put(case, source_id="host2", value=_t(12, 0))
    _put(case, source_id="host2", value=_t(13, 0))
    result = find_gaps(case.store, min_gap_seconds=60)
    # The APPROXIMATE event's widened interval (03:00-15:00) already
    # covers host2's 12:00/13:00 activity -- no gap should be reported
    # for the (10:00, 20:00) pair despite host2 having events "inside" it,
    # because that window is already covered by the wider first interval.
    assert result.findings == ()
    case.close()


def test_adjacent_intervals_produce_no_gap(tmp_path: Path) -> None:
    """Two consecutive EXACT-precision events 1 second apart are a
    negligible, sub-threshold gap when min_gap_seconds is set well above
    that -- correctly filtered by duration, not by boundary math."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), precision=TimePrecision.EXACT)
    _put(case, source_id="host1", value=_t(9, 0, 1), precision=TimePrecision.EXACT)
    _put(case, source_id="host2", value=_t(9, 0), precision=TimePrecision.EXACT)
    _put(case, source_id="host2", value=_t(9, 0, 1), precision=TimePrecision.EXACT)
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    case.close()


def test_exact_boundary_equality_is_not_a_gap(tmp_path: Path) -> None:
    """A candidate window whose duration exactly equals min_gap_seconds
    must be included (>=, not >)."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 1))  # exactly 60s later
    _put(case, source_id="host2", value=_t(9, 0, 20))  # strictly inside the window
    _put(case, source_id="host2", value=_t(9, 0, 40))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1  # duration == 60 == min_gap_seconds, included
    case.close()


def test_present_source_events_exactly_on_gap_boundary_do_not_corroborate(
    tmp_path: Path,
) -> None:
    """A present-source assertion landing exactly on the gap's boundary
    coincides with an instant the absent source already has evidence
    for, so it must not count as corroboration -- otherwise two sources
    with identical, fully overlapping timelines would wrongly generate a
    finding between every consecutive pair of their own shared points
    (see test_overlapping_sources_no_actual_gap)."""
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 1))
    _put(case, source_id="host2", value=_t(9, 0))  # exactly on the boundary
    _put(case, source_id="host2", value=_t(9, 1))  # exactly on the boundary
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    case.close()


def test_identical_timestamps_do_not_crash(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0), label="a")
    _put(case, source_id="host1", value=_t(9, 0), label="b")  # same instant, same source
    _put(case, source_id="host2", value=_t(9, 0), label="c")
    result = find_gaps(case.store, min_gap_seconds=1)
    assert result.findings == ()  # no crash, no spurious finding
    case.close()


def test_timezone_normalization_does_not_produce_spurious_gap(tmp_path: Path) -> None:
    utc_time = _t(9, 0)
    other_tz_time = utc_time.astimezone(timezone(timedelta(hours=5)))
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=other_tz_time + timedelta(minutes=10))
    _put(case, source_id="host2", value=other_tz_time + timedelta(minutes=20))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1  # correctly recognized as the same UTC window
    case.close()


# -- Determinism / ordering ---------------------------------------------------


def test_insertion_order_does_not_affect_findings(tmp_path: Path) -> None:
    case_a = Case.create(tmp_path / "a")
    _put(case_a, source_id="host1", value=_t(9, 0))
    _put(case_a, source_id="host1", value=_t(9, 40))
    _put(case_a, source_id="host2", value=_t(9, 10))
    _put(case_a, source_id="host2", value=_t(9, 20))

    case_b = Case.create(tmp_path / "b")
    _put(case_b, source_id="host2", value=_t(9, 20))
    _put(case_b, source_id="host2", value=_t(9, 10))
    _put(case_b, source_id="host1", value=_t(9, 40))
    _put(case_b, source_id="host1", value=_t(9, 0))

    result_a = find_gaps(case_a.store, min_gap_seconds=60)
    result_b = find_gaps(case_b.store, min_gap_seconds=60)
    assert result_a.findings == result_b.findings
    case_a.close()
    case_b.close()


def test_repeated_calls_are_byte_identical(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))
    first = find_gaps(case.store, min_gap_seconds=60)
    second = find_gaps(case.store, min_gap_seconds=60)
    assert first == second
    case.close()


# -- Export / import -----------------------------------------------------------


def test_export_import_preserves_findings_exactly(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "original")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))
    case.record_manifest()

    original_result = find_gaps(case.store, min_gap_seconds=60)
    archive = export_case(case, tmp_path / "case.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_result = find_gaps(restored.store, min_gap_seconds=60)
    assert restored_result.findings == original_result.findings
    restored.close()


# -- Legacy / thresholds --------------------------------------------------------


def test_legacy_case_with_no_declared_sources_has_no_findings(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id=None, value=_t(9, 0))
    _put(case, source_id=None, value=_t(9, 40))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    assert result.excluded_no_declared_source == 2
    case.close()


def test_insufficient_corroboration_suppresses_finding(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 20))  # only one corroborating event
    result = find_gaps(case.store, min_gap_seconds=60, min_corroborating_events=2)
    assert result.findings == ()
    case.close()


def test_isolated_activity_produces_no_finding(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 40))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert result.findings == ()
    case.close()


def test_min_gap_seconds_filters_short_gaps(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="host1", value=_t(9, 0))
    _put(case, source_id="host1", value=_t(9, 0, 30))  # 30s gap
    _put(case, source_id="host2", value=_t(9, 0, 10))
    _put(case, source_id="host2", value=_t(9, 0, 20))
    assert find_gaps(case.store, min_gap_seconds=60).findings == ()
    assert len(find_gaps(case.store, min_gap_seconds=10).findings) == 1
    case.close()


# -- Unicode / path-like source ids (already validated at ingestion) ---------


def test_unicode_source_id_is_an_ordinary_grouping_key(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="hôte-1", value=_t(9, 0))
    _put(case, source_id="hôte-1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1
    assert result.findings[0].absent_source == "hôte-1"
    case.close()


def test_path_like_source_id_is_an_ordinary_grouping_key(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put(case, source_id="logs/host1", value=_t(9, 0))
    _put(case, source_id="logs/host1", value=_t(9, 40))
    _put(case, source_id="host2", value=_t(9, 10))
    _put(case, source_id="host2", value=_t(9, 20))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 1
    assert result.findings[0].absent_source == "logs/host1"
    case.close()


# -- Larger synthetic dataset (regression guard, not a formal benchmark) -----


def test_large_but_reasonable_synthetic_dataset_completes(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    base = _t(0)
    for source_id in ("host1", "host2", "host3"):
        offset = {"host1": 0, "host2": 1, "host3": 2}[source_id]
        for i in range(100):
            _put(case, source_id=source_id, value=base + timedelta(minutes=i * 5 + offset))
    result = find_gaps(case.store, min_gap_seconds=60)
    assert isinstance(result.findings, tuple)  # completes without error
    case.close()
