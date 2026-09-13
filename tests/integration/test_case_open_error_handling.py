"""Every CLI command that opens an existing case must fail cleanly -- a
single-line stderr message and a nonzero exit code -- when the case
directory doesn't exist or its case.db is unreadable, never a raw Python
traceback. `test_report_cli.py` already covers `report`/`verify`/`replay`/
`import`; this file covers the remaining commands, all of which share the
same `_open_case_or_fail` helper (`witnessgraph.cli.main`).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from witnessgraph.cli.main import app

runner = CliRunner()

# Each entry is a full argv template; "{case}" is replaced with the case
# directory under test. Extra ids/values are dummy strings/valid-shaped
# values -- the case-open failure must occur before any of them are looked
# up or validated against the (nonexistent/unreadable) store.
COMMANDS: list[tuple[str, list[str]]] = [
    ("timeline", ["timeline", "{case}"]),
    ("entities-list", ["entities", "list", "{case}"]),
    ("entities-show", ["entities", "show", "{case}", "some-id"]),
    ("entities-create", ["entities", "create", "{case}", "host", "--derived-from", "some-id"]),
    ("relationships-list", ["relationships", "list", "{case}"]),
    ("relationships-show", ["relationships", "show", "{case}", "some-id"]),
    (
        "relationships-create",
        [
            "relationships", "create", "{case}", "connected_to",
            "--source", "a", "--target", "b", "--derived-from", "some-id",
        ],
    ),
    ("hypothesis-list", ["hypothesis", "list", "{case}"]),
    ("gaps", ["gaps", "{case}", "--min-gap-seconds", "60"]),
    ("contradictions", ["contradictions", "{case}"]),
    ("export", ["export", "{case}", "{case}.wgcase"]),
    ("findings-list", ["findings", "list", "{case}"]),
    ("contradiction-findings-list", ["contradiction-findings", "list", "{case}"]),
    (
        "time-assertions-create",
        [
            "time-assertions",
            "create",
            "{case}",
            "some-event-id",
            "--value",
            "2026-01-01T00:00:00+00:00",
            "--precision",
            "second",
            "--source-evidence",
            "some-evidence-id",
            "--by",
            "analyst:jane",
        ],
    ),
    ("ingest", ["ingest", "{case}", "jsonl", "{case}/nonexistent.jsonl"]),
]


def _corrupt_case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "corrupt"
    case_dir.mkdir()
    (case_dir / "case.db").write_bytes(b"not a sqlite database, just garbage")
    return case_dir


@pytest.mark.parametrize("argv_template", [c[1] for c in COMMANDS], ids=[c[0] for c in COMMANDS])
def test_missing_case_dir_fails_cleanly(tmp_path: Path, argv_template: list[str]) -> None:
    missing = tmp_path / "does-not-exist"
    argv = [part.format(case=str(missing)) for part in argv_template]
    result = runner.invoke(app, argv)
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert b"does not look like a Witnessgraph case" in result.stderr_bytes


@pytest.mark.parametrize("argv_template", [c[1] for c in COMMANDS], ids=[c[0] for c in COMMANDS])
def test_corrupted_case_db_fails_cleanly(tmp_path: Path, argv_template: list[str]) -> None:
    case_dir = _corrupt_case(tmp_path)
    argv = [part.format(case=str(case_dir)) for part in argv_template]
    result = runner.invoke(app, argv)
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert b"readable Witnessgraph case database" in result.stderr_bytes
