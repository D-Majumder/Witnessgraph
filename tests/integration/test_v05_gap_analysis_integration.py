"""docs/phase5-v0.5-gap-analysis-design.md: CLI, report-rendering, and
export/import coverage for `witnessgraph gaps` / render_report's optional
Coverage Gaps section.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.correlate.gaps import find_gaps
from witnessgraph.portable import export_case, import_case
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


def _put(case: Case, *, source_id: str | None, value: datetime, label: str) -> TimeAssertion:
    evidence = EvidenceItem.create(
        raw_bytes=label.encode(), source_adapter="jsonl", adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1", collected_at=NOW, source_id=source_id,
    )
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line", attributes={"label": label}, derived_from=(evidence.id,), created_at=NOW
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


def _build_case_with_gap(root: Path) -> Case:
    case = Case.create(root)
    _put(case, source_id="host1", value=_t(9, 0), label="a")
    _put(case, source_id="host1", value=_t(9, 40), label="b")
    _put(case, source_id="host2", value=_t(9, 10), label="c")
    _put(case, source_id="host2", value=_t(9, 20), label="d")
    case.record_manifest()
    return case


# -- CLI ----------------------------------------------------------------------


def test_cli_gaps_reports_finding(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_case_with_gap(case_dir)
    case.close()

    result = runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60"])
    assert result.exit_code == 0
    assert b"host1" in result.stdout_bytes
    assert b"host2" in result.stdout_bytes
    assert b"no observed evidence" in result.stdout_bytes


def test_cli_gaps_reports_none_found_on_empty_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60"])
    assert result.exit_code == 0
    assert b"no coverage gaps found" in result.stdout_bytes


def test_cli_gaps_requires_min_gap_seconds(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(app, ["gaps", str(case_dir)])
    assert result.exit_code != 0  # required option omitted


def test_cli_gaps_rejects_zero_min_corroborating_events(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app,
        ["gaps", str(case_dir), "--min-gap-seconds", "60", "--min-corroborating-events", "0"],
    )
    assert result.exit_code != 0


def test_cli_gaps_rejects_negative_min_corroborating_events(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app,
        ["gaps", str(case_dir), "--min-gap-seconds", "60", "--min-corroborating-events", "-1"],
    )
    assert result.exit_code != 0


def test_cli_report_unaffected_by_default_no_gap_flag(tmp_path: Path) -> None:
    """The existing `report` command's output must be byte-identical to
    before this milestone -- gap analysis is opt-in only, never wired
    into `report`'s default behavior in this scope."""
    case_dir = tmp_path / "case"
    case = _build_case_with_gap(case_dir)
    case.close()

    result = runner.invoke(app, ["report", str(case_dir)])
    assert result.exit_code == 0
    assert b"## Coverage Gaps" not in result.stdout_bytes


# -- Report rendering (direct, library-level) --------------------------------


def test_report_with_gap_analysis_includes_coverage_gaps_section(tmp_path: Path) -> None:
    case = _build_case_with_gap(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60)
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(), gap_analysis=result,
    )
    assert "## Coverage Gaps" in report
    assert "host1" in report
    assert "host2" in report
    case.close()


def test_report_without_gap_analysis_omits_section_entirely(tmp_path: Path) -> None:
    case = _build_case_with_gap(tmp_path / "case")
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Coverage Gaps" not in report
    case.close()


def test_report_with_gap_analysis_is_deterministic(tmp_path: Path) -> None:
    case = _build_case_with_gap(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60)
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


# -- Export / import with gap analysis ----------------------------------------


def test_gap_analysis_report_identical_before_and_after_export_import(tmp_path: Path) -> None:
    original = _build_case_with_gap(tmp_path / "original")
    original_result = find_gaps(original.store, min_gap_seconds=60)
    original_report = render_report(
        case_name="c", store=original.store, recomputed_manifest=original.compute_manifest(),
        recorded_manifest=original.load_recorded_manifest(), gap_analysis=original_result,
    )

    archive = export_case(original, tmp_path / "case.wgcase")
    original.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_result = find_gaps(restored.store, min_gap_seconds=60)
    restored_report = render_report(
        case_name="c", store=restored.store, recomputed_manifest=restored.compute_manifest(),
        recorded_manifest=restored.load_recorded_manifest(), gap_analysis=restored_result,
    )
    assert restored_report == original_report
    restored.close()


# -- Both contradiction and gap findings coexist ------------------------------


def test_contradiction_and_gap_findings_coexist_independently(tmp_path: Path) -> None:
    case = _build_case_with_gap(tmp_path / "case")

    # Add a genuine contradiction: two assertions about the SAME event
    # with EXACT precision that disagree.
    evidence = EvidenceItem.create(
        raw_bytes=b"contradiction-evidence", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="x.jsonl:1", collected_at=NOW, source_id="host1",
    )
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line", derived_from=(evidence.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event.id, value=_t(11, 0), precision=TimePrecision.EXACT,
            source_evidence_id=evidence.id, asserted_by="source-a", created_at=NOW,
        )
    )
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event.id, value=_t(12, 0), precision=TimePrecision.EXACT,
            source_evidence_id=evidence.id, asserted_by="source-b", created_at=NOW,
        )
    )

    gap_result = find_gaps(case.store, min_gap_seconds=60)
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(), gap_analysis=gap_result,
    )
    assert "## Contradictions" in report
    assert "## Coverage Gaps" in report
    contradictions_idx = report.index("## Contradictions")
    gaps_idx = report.index("## Coverage Gaps")
    contradictions_section = report[contradictions_idx:gaps_idx]
    gaps_section = report[gaps_idx:]
    assert "(none)" not in contradictions_section.split("\n\n")[0]
    assert "host1" in gaps_section
    case.close()


# -- `--format json` -----------------------------------------------------------


def test_gaps_format_json_shape_and_determinism(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_case_with_gap(case_dir)
    case.close()

    args = ["gaps", str(case_dir), "--min-gap-seconds", "60", "--format", "json"]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    doc = json.loads(first.stdout)
    assert len(doc["findings"]) == 1
    finding = doc["findings"][0]
    assert {finding["absent_source"], finding["present_source"]} == {"host1", "host2"}
    assert finding["absent_source_refinement"] is None
    assert doc["refine_source_by_attribute"] is None
    assert doc["excluded_no_time_assertion"] == 0
    assert doc["tracked"] is None
    assert first.stdout == second.stdout


def test_gaps_format_json_empty_case_is_empty_array(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--format", "json"]
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["findings"] == []
    assert doc["tracked"] is None


def test_gaps_format_json_with_track_reports_tracked_summary(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_case_with_gap(case_dir)
    case.close()

    result = runner.invoke(
        app,
        ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track", "--format", "json"],
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["tracked"] == {"new": 1, "already_tracked": 0}

    case = Case.open(case_dir)
    assert len(case.store.list_tracked_findings()) == 1  # tracking still happened
    case.close()


def test_gaps_format_json_does_not_change_default_text(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_case_with_gap(case_dir)
    case.close()
    result = runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60"])
    assert result.exit_code == 0
    assert "{" not in result.stdout


def test_gaps_rejects_bad_format(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()
    result = runner.invoke(
        app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--format", "xml"]
    )
    assert result.exit_code != 0
