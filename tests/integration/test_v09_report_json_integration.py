"""v0.9: CLI-level tests for `witnessgraph report --format json`, using
typer.testing.CliRunner. Covers stdout/--output byte equality, no-
trailing-newline, corrupted-case parity with Markdown, unsupported-
format rejection (both 'html' and the existing Markdown-only contract),
and full-document CLI-level sanity.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.store.case import Case

runner = CliRunner()
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()
    return case_dir


def test_report_json_exits_zero_and_is_valid_json(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir), "--format", "json"])
    assert result.exit_code == 0
    doc = json.loads(result.stdout_bytes)
    assert doc["schema_version"] == 1


def test_report_json_stdout_matches_output_file_byte_for_byte(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result_stdout = runner.invoke(app, ["report", str(case_dir), "--format", "json"])
    assert result_stdout.exit_code == 0

    out_path = tmp_path / "report.json"
    result_file = runner.invoke(
        app, ["report", str(case_dir), "--format", "json", "--output", str(out_path)]
    )
    assert result_file.exit_code == 0
    assert out_path.read_bytes() == result_stdout.stdout_bytes


def test_report_json_has_no_trailing_newline(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir), "--format", "json"])
    assert result.exit_code == 0
    assert not result.stdout_bytes.endswith(b"\n")


def test_report_json_no_cr_bytes(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir), "--format", "json"])
    assert b"\r" not in result.stdout_bytes


def test_report_json_output_to_existing_path_fails_without_writing(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    out_path = tmp_path / "existing.json"
    out_path.write_bytes(b"do not touch me")
    result = runner.invoke(
        app, ["report", str(case_dir), "--format", "json", "--output", str(out_path)]
    )
    assert result.exit_code != 0
    assert out_path.read_bytes() == b"do not touch me"


def test_report_rejects_html_format_still(tmp_path: Path) -> None:
    """Pre-existing rejection contract must survive v0.9 unchanged."""
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir), "--format", "html"])
    assert result.exit_code != 0


def test_report_default_format_is_still_markdown(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir)])
    assert result.exit_code == 0
    assert b"## Integrity Summary" in result.stdout_bytes
    assert not result.stdout_bytes.startswith(b"{")


def test_report_json_on_corrupted_case_db_fails_cleanly_same_as_markdown(
    tmp_path: Path,
) -> None:
    case_dir = tmp_path / "corrupt"
    case_dir.mkdir()
    (case_dir / "case.db").write_bytes(b"not a sqlite database, just garbage")

    md_result = runner.invoke(app, ["report", str(case_dir)])
    json_result = runner.invoke(app, ["report", str(case_dir), "--format", "json"])

    assert md_result.exit_code != 0
    assert json_result.exit_code != 0
    assert md_result.exit_code == json_result.exit_code
    assert b"readable Witnessgraph case database" in md_result.stderr_bytes
    assert b"readable Witnessgraph case database" in json_result.stderr_bytes


def test_report_json_full_document_via_cli_with_tracked_kinds(tmp_path: Path) -> None:
    """End-to-end: build a case with evidence, a gap finding, and a
    contradiction, track both, then confirm the CLI JSON output contains
    correctly-shaped, isolated sections for each."""
    from witnessgraph.core.events import NormalizedEvent
    from witnessgraph.core.evidence import EvidenceItem
    from witnessgraph.core.time_model import TimeAssertion, TimePrecision

    case_dir = tmp_path / "full_case"
    case = Case.create(case_dir)

    for label, sid, hour, minute in [
        ("a", "host1", 9, 0), ("b", "host1", 9, 40), ("c", "host2", 9, 10), ("d", "host2", 9, 20),
    ]:
        ev = EvidenceItem.create(
            raw_bytes=label.encode(), source_adapter="jsonl", adapter_version="0.1.0",
            source_locator=f"{label}.jsonl:1", collected_at=NOW, source_id=sid,
        )
        case.store.put_evidence(ev)
        event = NormalizedEvent.create(
            event_type="line", attributes={}, derived_from=(ev.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=datetime(2026, 1, 1, hour, minute, tzinfo=UTC),
                precision=TimePrecision.EXACT, source_evidence_id=ev.id,
                asserted_by="t", created_at=NOW,
            )
        )

    ev_a = EvidenceItem.create(
        raw_bytes=b"extra-a", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="extra-a.jsonl:1", collected_at=NOW,
    )
    ev_b = EvidenceItem.create(
        raw_bytes=b"extra-b", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="extra-b.jsonl:1", collected_at=NOW,
    )
    case.store.put_evidence(ev_a)
    case.store.put_evidence(ev_b)
    event2 = NormalizedEvent.create(
        event_type="line", attributes={}, derived_from=(ev_a.id, ev_b.id), created_at=NOW
    )
    case.store.put_normalized_event(event2)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event2.id, value=NOW, precision=TimePrecision.EXACT,
            source_evidence_id=ev_a.id, asserted_by="source-a", created_at=NOW,
        )
    )
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event2.id, value=NOW.replace(hour=3), precision=TimePrecision.EXACT,
            source_evidence_id=ev_b.id, asserted_by="source-b", created_at=NOW,
        )
    )
    case.record_manifest()
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])

    result = runner.invoke(app, ["report", str(case_dir), "--format", "json"])
    assert result.exit_code == 0
    doc = json.loads(result.stdout_bytes)

    assert len(doc["evidence"]) == 6
    assert len(doc["tracked_findings"]) == 1
    assert len(doc["tracked_contradictions"]) == 1
    assert doc["tracked_findings"][0]["still_reproduced"] is True
    assert "still_reproduced" not in doc["tracked_contradictions"][0]
    assert doc["coverage_gaps"] is None  # report CLI never wires gap_analysis in
