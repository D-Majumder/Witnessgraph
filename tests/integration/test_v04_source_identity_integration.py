"""docs/phase4-v0.4-source-identity-design.md: end-to-end ingestion, CLI,
export/import, and report-determinism coverage for explicit
analyst-declared source identity.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.adapters.syslog_adapter import SyslogAdapter
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.portable import export_case, import_case
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


# -- Pipeline-level: two JSONL files, same adapter, different source_id ----


def test_two_jsonl_files_same_adapter_different_source_ids(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    host1_file = tmp_path / "host1.jsonl"
    host2_file = tmp_path / "host2.jsonl"
    host1_file.write_text('{"event_type": "logon", "user": "alice"}\n')
    host2_file.write_text('{"event_type": "logon", "user": "bob"}\n')

    ingest_source(
        case, JsonlAdapter(), SourceDescriptor(path=host1_file, source_id="host1"),
        collected_at=NOW,
    )
    ingest_source(
        case, JsonlAdapter(), SourceDescriptor(path=host2_file, source_id="host2"),
        collected_at=NOW,
    )

    items = case.store.list_evidence()
    assert len(items) == 2
    declared = {frozenset(i.declared_source_ids()) for i in items}
    assert declared == {frozenset({"host1"}), frozenset({"host2"})}
    case.close()


# -- Pipeline-level: two syslog inputs, same adapter, different source_id --


def test_two_syslog_inputs_same_adapter_different_source_ids(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    host1_file = tmp_path / "host1.syslog"
    host2_file = tmp_path / "host2.syslog"
    host1_file.write_text("Jan 12 03:04:05 host1 sshd[111]: Accepted publickey for alice\n")
    host2_file.write_text("Jan 12 03:04:06 host2 sshd[222]: Accepted publickey for bob\n")

    ingest_source(
        case, SyslogAdapter(), SourceDescriptor(path=host1_file, source_id="host1"),
        collected_at=NOW,
    )
    ingest_source(
        case, SyslogAdapter(), SourceDescriptor(path=host2_file, source_id="host2"),
        collected_at=NOW,
    )

    items = case.store.list_evidence()
    assert len(items) == 2
    declared = {frozenset(i.declared_source_ids()) for i in items}
    assert declared == {frozenset({"host1"}), frozenset({"host2"})}
    case.close()


def test_reingesting_same_source_with_same_source_id_is_idempotent(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl", source_id="host1")

    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    first_count = len(case.store.list_evidence())

    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    second_count = len(case.store.list_evidence())

    assert first_count == second_count == 5
    for item in case.store.list_evidence():
        assert item.declared_source_ids() in (frozenset(), frozenset({"host1"}))
    case.close()


# -- CLI-level --------------------------------------------------------------


def _make_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    result = runner.invoke(app, ["init", str(case_dir)])
    assert result.exit_code == 0
    return case_dir


def test_cli_ingest_with_source_id_appears_in_report(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(
        app,
        ["ingest", str(case_dir), "jsonl", str(FIXTURES / "sample_events.jsonl"),
         "--source-id", "host1"],
    )
    assert result.exit_code == 0

    report_result = runner.invoke(app, ["report", str(case_dir)])
    assert report_result.exit_code == 0
    assert b"source_id: `host1`" in report_result.stdout_bytes


def test_cli_ingest_without_source_id_reports_no_declared_source(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(
        app, ["ingest", str(case_dir), "jsonl", str(FIXTURES / "sample_events.jsonl")]
    )
    assert result.exit_code == 0

    report_result = runner.invoke(app, ["report", str(case_dir)])
    assert report_result.exit_code == 0
    assert b"source_id: (no declared source)" in report_result.stdout_bytes


def test_cli_rejects_empty_source_id_cleanly(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(
        app,
        ["ingest", str(case_dir), "jsonl", str(FIXTURES / "sample_events.jsonl"),
         "--source-id", ""],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_cli_rejects_source_id_with_control_character_cleanly(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(
        app,
        ["ingest", str(case_dir), "jsonl", str(FIXTURES / "sample_events.jsonl"),
         "--source-id", "host\x01"],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_cli_rejects_whitespace_only_source_id_cleanly(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(
        app,
        ["ingest", str(case_dir), "jsonl", str(FIXTURES / "sample_events.jsonl"),
         "--source-id", "   "],
    )
    assert result.exit_code != 0


# -- Export / import ---------------------------------------------------------


def test_export_import_preserves_declared_source_id(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "original")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl", source_id="host1")
    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    original_manifest = case.record_manifest()

    archive = export_case(case, tmp_path / "case.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_manifest = restored.compute_manifest()

    assert restored_manifest.manifest_hash == original_manifest.manifest_hash
    restored_items = restored.store.list_evidence()
    for item in restored_items:
        assert item.declared_source_ids() in (frozenset(), frozenset({"host1"}))
    assert any(item.declared_source_ids() == frozenset({"host1"}) for item in restored_items)
    restored.close()


# -- Report determinism -------------------------------------------------------


def test_report_with_source_id_is_deterministic_across_repeated_generation(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl", source_id="host1")
    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    case.record_manifest()

    first = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    second = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert first == second
    assert "source_id: `host1`" in first
    case.close()


def test_report_identical_before_and_after_export_import_with_source_id(tmp_path: Path) -> None:
    original = Case.create(tmp_path / "original")
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl", source_id="host1")
    ingest_source(original, JsonlAdapter(), source, collected_at=NOW)
    original.record_manifest()
    original_report = render_report(
        case_name="original", store=original.store,
        recomputed_manifest=original.compute_manifest(),
        recorded_manifest=original.load_recorded_manifest(),
    )

    archive = export_case(original, tmp_path / "case.wgcase")
    original.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_report = render_report(
        case_name="original", store=restored.store,
        recomputed_manifest=restored.compute_manifest(),
        recorded_manifest=restored.load_recorded_manifest(),
    )
    assert restored_report == original_report
    restored.close()
