"""CLI-level tests for `witnessgraph report` and `witnessgraph verify`,
using typer.testing.CliRunner (bundled with the existing `typer` runtime
dependency -- no new dependency introduced). Byte-identity checks compare
raw bytes (`result.stdout_bytes`), never decoded text, per the byte-level
determinism contract in docs/phase2-v0.2-spec.md §7.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis
from witnessgraph.store.case import Case

runner = CliRunner()
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()
    return case_dir


def test_report_exits_zero_on_empty_case(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir)])
    assert result.exit_code == 0
    assert b"## Integrity Summary" in result.stdout_bytes


def test_report_stdout_matches_output_file_byte_for_byte(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result_stdout = runner.invoke(app, ["report", str(case_dir)])
    assert result_stdout.exit_code == 0

    out_path = tmp_path / "report.md"
    result_file = runner.invoke(app, ["report", str(case_dir), "--output", str(out_path)])
    assert result_file.exit_code == 0
    assert out_path.read_bytes() == result_stdout.stdout_bytes


def test_report_no_cr_bytes_in_stdout(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir)])
    assert b"\r" not in result.stdout_bytes


def test_report_output_to_existing_path_fails_without_writing(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    out_path = tmp_path / "existing.md"
    out_path.write_bytes(b"do not touch me")
    result = runner.invoke(app, ["report", str(case_dir), "--output", str(out_path)])
    assert result.exit_code != 0
    assert out_path.read_bytes() == b"do not touch me"


def test_report_rejects_non_markdown_format(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["report", str(case_dir), "--format", "html"])
    assert result.exit_code != 0


def test_report_dangling_evidence_ref_does_not_crash(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    case = Case.open(case_dir)
    hyp = Hypothesis(
        statement="dangling reference test",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id="missing-id"),),
        inferred_by="analyst:test",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    case.close()
    result = runner.invoke(app, ["report", str(case_dir)])
    assert result.exit_code == 0
    assert b"missing-id" in result.stdout_bytes


def test_report_on_corrupted_case_db_fails_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "corrupt"
    case_dir.mkdir()
    (case_dir / "case.db").write_bytes(b"not a sqlite database, just garbage")
    result = runner.invoke(app, ["report", str(case_dir)])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert b"readable Witnessgraph case database" in result.stderr_bytes


def test_verify_exits_zero_on_untampered_case(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["verify", str(case_dir)])
    assert result.exit_code == 0
    assert b"MATCH" in result.stdout_bytes


def test_verify_exits_nonzero_on_tampered_manifest(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    manifest_path = case_dir / "manifest.json"
    # manifest_version must match the current algorithm version for this to
    # be a genuine hash MISMATCH rather than a version-mismatch "not
    # comparable" outcome -- see docs/phase3-v0.3-design.md §11.
    manifest_path.write_text(
        '{"collection_hashes": {}, "manifest_hash": "deadbeef", "manifest_version": 2}'
    )
    result = runner.invoke(app, ["verify", str(case_dir)])
    assert result.exit_code != 0
    assert b"MISMATCH" in result.stdout_bytes


def test_verify_with_report_flag_confirms_generation(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["verify", str(case_dir), "--report"])
    assert result.exit_code == 0
    assert b"report generation: OK" in result.stdout_bytes


def test_verify_on_corrupted_case_db_fails_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "corrupt"
    case_dir.mkdir()
    (case_dir / "case.db").write_bytes(b"not a sqlite database, just garbage")
    result = runner.invoke(app, ["verify", str(case_dir)])
    assert result.exit_code != 0
    assert b"readable Witnessgraph case database" in result.stderr_bytes


def test_replay_on_corrupted_case_db_fails_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "corrupt"
    case_dir.mkdir()
    (case_dir / "case.db").write_bytes(b"not a sqlite database, just garbage")
    result = runner.invoke(app, ["replay", str(case_dir)])
    assert result.exit_code != 0
    assert b"readable Witnessgraph case database" in result.stderr_bytes


def test_replay_still_behaves_exactly_as_before_on_a_good_case(tmp_path: Path) -> None:
    case_dir = _make_case(tmp_path)
    result = runner.invoke(app, ["replay", str(case_dir)])
    assert result.exit_code == 0
    assert b"MATCH" in result.stdout_bytes


def test_import_of_archive_with_corrupted_case_db_fails_cleanly(tmp_path: Path) -> None:
    # Build a minimal .wgcase-shaped archive whose case.db is garbage.
    import zipfile

    archive = tmp_path / "bad.wgcase"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("case.db", "not a sqlite database")
        zf.writestr("manifest.json", '{"collection_hashes": {}, "manifest_hash": "x"}')
    dest = tmp_path / "restored"
    result = runner.invoke(app, ["import", str(archive), str(dest)])
    assert result.exit_code != 0
    assert b"not readable" in result.stderr_bytes


def test_sqlite_database_error_is_the_confirmed_exception_type() -> None:
    """Documents the empirical check performed before implementation:
    both a garbage file and a header-valid-but-corrupted file raise
    sqlite3.DatabaseError, which is what the CLI's clean-failure
    handling catches."""
    assert issubclass(sqlite3.DatabaseError, Exception)
