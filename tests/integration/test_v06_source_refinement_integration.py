"""v0.6: CLI and report-level coverage for optional source-identity
refinement (`witnessgraph gaps --refine-source-by-attribute`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.correlate.gaps import find_gaps
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


def _put(
    case: Case,
    *,
    source_id: str | None,
    value: datetime,
    attributes: dict[str, str] | None,
    label: str,
) -> TimeAssertion:
    evidence = EvidenceItem.create(
        raw_bytes=label.encode(), source_adapter="jsonl", adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1", collected_at=NOW, source_id=source_id,
    )
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line", attributes=attributes or {}, derived_from=(evidence.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    assertion = TimeAssertion.create(
        subject_event_id=event.id, value=value, precision=TimePrecision.EXACT,
        source_evidence_id=evidence.id, asserted_by="test", created_at=NOW,
    )
    case.store.put_time_assertion(assertion)
    return assertion


def _t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def _build_collision_case(root: Path) -> Case:
    """Two real hosts sharing one coarse source_id, distinguished only by
    a 'host' attribute -- the exact scenario refinement exists to help."""
    case = Case.create(root)
    _put(case, source_id="shared", value=_t(9, 0), attributes={"host": "real-a"}, label="a")
    _put(case, source_id="shared", value=_t(9, 40), attributes={"host": "real-a"}, label="b")
    _put(case, source_id="shared", value=_t(9, 10), attributes={"host": "real-b"}, label="c")
    _put(case, source_id="shared", value=_t(9, 20), attributes={"host": "real-b"}, label="d")
    case.record_manifest()
    return case


# -- CLI ----------------------------------------------------------------------


def test_cli_gaps_without_refinement_flag_is_unchanged(tmp_path: Path) -> None:
    """No-refinement CLI output must contain no v0.6-specific text and no
    finding (the coarse merge masks the real-a gap, exactly as v0.5)."""
    case_dir = tmp_path / "case"
    case = _build_collision_case(case_dir)
    case.close()

    result = runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60"])
    assert result.exit_code == 0
    assert b"no coverage gaps found" in result.stdout_bytes
    assert b"refined" not in result.stdout_bytes


def test_cli_gaps_with_refinement_flag_reveals_finding_and_discloses_it(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_collision_case(case_dir)
    case.close()

    result = runner.invoke(
        app,
        ["gaps", str(case_dir), "--min-gap-seconds", "60",
         "--refine-source-by-attribute", "host"],
    )
    assert result.exit_code == 0
    assert b"source identity refined by attribute `host`" in result.stdout_bytes
    assert b"does not prove physical source identity" in result.stdout_bytes
    assert b"refined: real-a" in result.stdout_bytes
    assert b"refined: real-b" in result.stdout_bytes


def test_cli_gaps_refinement_with_no_matching_attribute_falls_back(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    _put(case, source_id="host1", value=_t(9, 0), attributes=None, label="a")
    _put(case, source_id="host1", value=_t(9, 40), attributes=None, label="b")
    _put(case, source_id="host2", value=_t(9, 10), attributes=None, label="c")
    _put(case, source_id="host2", value=_t(9, 20), attributes=None, label="d")
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app,
        ["gaps", str(case_dir), "--min-gap-seconds", "60",
         "--refine-source-by-attribute", "host"],
    )
    assert result.exit_code == 0
    assert b"source identity refined by attribute `host`" in result.stdout_bytes
    assert b"refined:" not in result.stdout_bytes  # no finding used a refinement value
    assert b"source `host1` has no observed evidence" in result.stdout_bytes


# -- Report ---------------------------------------------------------------------


def test_report_with_refinement_discloses_it(tmp_path: Path) -> None:
    case = _build_collision_case(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(), gap_analysis=result,
    )
    assert "Source identity refined by attribute `host`" in report
    assert "does not prove physical source identity" in report
    assert "(refined: `real-a`)" in report
    assert "(refined: `real-b`)" in report
    case.close()


def test_report_without_refinement_is_unchanged(tmp_path: Path) -> None:
    """No-refinement report output must contain no v0.6-specific text."""
    case = _build_collision_case(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60)
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(), gap_analysis=result,
    )
    assert "refined" not in report
    assert "## Coverage Gaps" in report
    assert "(none)" in report
    case.close()


def test_report_with_refinement_is_deterministic(tmp_path: Path) -> None:
    case = _build_collision_case(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60, refine_source_by_attribute="host")
    first = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(), gap_analysis=result,
    )
    second = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(), gap_analysis=result,
    )
    assert first == second
    case.close()
