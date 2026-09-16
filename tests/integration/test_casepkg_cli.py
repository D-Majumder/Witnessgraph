"""End-to-end CLI coverage for `witnessgraph case-package` (researcher
edition): init/validate/import/export, both plain-JSON and
`.witnessgraph-case` archive forms, and round-trip reproducibility."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.casepkg.archive import read_case_package_archive
from witnessgraph.cli.main import app
from witnessgraph.store.case import Case

runner = CliRunner()


def test_init_writes_a_valid_demo_package(tmp_path: Path) -> None:
    output = tmp_path / "demo.json"
    result = runner.invoke(app, ["case-package", "init", str(output)])
    assert result.exit_code == 0, result.output
    assert output.exists()
    data = json.loads(output.read_text())
    assert data["schema_version"] == 1
    assert "DEMO" in data["case_metadata"]["title"]


def test_init_then_validate_reports_valid(tmp_path: Path) -> None:
    output = tmp_path / "demo.json"
    runner.invoke(app, ["case-package", "init", str(output)])
    result = runner.invoke(app, ["case-package", "validate", str(output)])
    assert result.exit_code == 0, result.output
    assert "VALID" in result.output


def test_validate_rejects_malformed_json(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("not json")
    result = runner.invoke(app, ["case-package", "validate", str(bad)])
    assert result.exit_code == 1
    assert "INVALID" in result.output


def test_validate_missing_file_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["case-package", "validate", str(tmp_path / "nope.json")])
    assert result.exit_code == 1
    assert "no such file" in result.output


def test_validate_does_not_modify_the_file(tmp_path: Path) -> None:
    output = tmp_path / "demo.json"
    runner.invoke(app, ["case-package", "init", str(output)])
    before = output.read_bytes()
    runner.invoke(app, ["case-package", "validate", str(output)])
    after = output.read_bytes()
    assert before == after


def test_import_then_verify_matches(tmp_path: Path) -> None:
    package_path = tmp_path / "demo.json"
    runner.invoke(app, ["case-package", "init", str(package_path)])
    dest = tmp_path / "mycase"
    result = runner.invoke(app, ["case-package", "import", str(package_path), str(dest)])
    assert result.exit_code == 0, result.output
    assert "manifest hash:" in result.output

    case = Case.open(dest)
    assert len(case.store.list_entities()) == 2
    assert len(case.store.list_evidence()) == 1
    manifest = case.load_recorded_manifest()
    assert manifest is not None
    assert manifest.manifest_hash == case.compute_manifest().manifest_hash
    case.close()


def test_import_of_invalid_package_creates_no_directory(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "package_version": "1.0",
                "case_metadata": {
                    "title": "t",
                    "created_by": "x",
                    "created_at": "2026-01-01T00:00:00Z",
                },
                "entities": [
                    {"local_id": "e1", "entity_type": "host", "derived_from": ["missing"]}
                ],
            }
        )
    )
    dest = tmp_path / "shouldnotexist"
    result = runner.invoke(app, ["case-package", "import", str(bad), str(dest)])
    assert result.exit_code == 1
    assert not dest.exists()


def test_export_then_reimport_produces_identical_manifest(tmp_path: Path) -> None:
    package_path = tmp_path / "demo.json"
    runner.invoke(app, ["case-package", "init", str(package_path)])
    case_dir = tmp_path / "case1"
    runner.invoke(app, ["case-package", "import", str(package_path), str(case_dir)])

    exported = tmp_path / "exported.json"
    result = runner.invoke(app, ["case-package", "export", str(case_dir), str(exported)])
    assert result.exit_code == 0, result.output

    case2_dir = tmp_path / "case2"
    result = runner.invoke(app, ["case-package", "import", str(exported), str(case2_dir)])
    assert result.exit_code == 0, result.output

    case1 = Case.open(case_dir)
    case2 = Case.open(case2_dir)
    hash1 = case1.compute_manifest().manifest_hash
    hash2 = case2.compute_manifest().manifest_hash
    case1.close()
    case2.close()
    assert hash1 == hash2


def test_archive_form_round_trips_and_verifies_integrity(tmp_path: Path) -> None:
    package_path = tmp_path / "demo.json"
    runner.invoke(app, ["case-package", "init", str(package_path)])
    case_dir = tmp_path / "case1"
    runner.invoke(app, ["case-package", "import", str(package_path), str(case_dir)])

    archive = tmp_path / "case.witnessgraph-case"
    result = runner.invoke(app, ["case-package", "export", str(case_dir), str(archive)])
    assert result.exit_code == 0, result.output

    raw, manifest = read_case_package_archive(archive)
    assert manifest.schema_version == 1
    parsed = json.loads(raw)
    assert parsed["schema_version"] == 1

    case2_dir = tmp_path / "case2"
    result = runner.invoke(app, ["case-package", "import", str(archive), str(case2_dir)])
    assert result.exit_code == 0, result.output


def test_export_already_existing_path_fails(tmp_path: Path) -> None:
    package_path = tmp_path / "demo.json"
    runner.invoke(app, ["case-package", "init", str(package_path)])
    case_dir = tmp_path / "case1"
    runner.invoke(app, ["case-package", "import", str(package_path), str(case_dir)])

    existing = tmp_path / "already-here.json"
    existing.write_text("{}")
    result = runner.invoke(app, ["case-package", "export", str(case_dir), str(existing)])
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_gui_style_workflow_entities_and_relationships_are_visible_via_services(
    tmp_path: Path,
) -> None:
    """A researcher's imported case should be usable through the same
    service layer the API/frontend already read from -- no special-casing
    needed for a case-package-imported case vs. a CLI-built one."""
    package_path = tmp_path / "demo.json"
    runner.invoke(app, ["case-package", "init", str(package_path)])
    case_dir = tmp_path / "mycase"
    runner.invoke(app, ["case-package", "import", str(package_path), str(case_dir)])

    from witnessgraph.service import entities_service

    case = Case.open(case_dir)
    entities = entities_service.list_entities(case)
    case.close()
    assert len(entities) == 2
    assert {e["entity_type"] for e in entities} == {"host", "user"}
