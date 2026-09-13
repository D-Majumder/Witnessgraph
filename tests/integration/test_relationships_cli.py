"""End-to-end CLI coverage for `witnessgraph relationships` (v1.1): the
first version to give Witnessgraph graph edges between entities, not just
isolated nodes. Exercises the real CLI via typer.testing.CliRunner,
mirroring test_v04_source_identity_integration.py's style.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.entities import Entity
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.report.render import render_report
from witnessgraph.report.render_json import build_report_json_tree
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


_BOX_DRAWING_CHARS = "─│┌┐└┘├┤┬┴┼"


def _flatten(text: str) -> str:
    """Collapse whitespace/newlines and strip Rich's box-drawing border
    characters, so a substring check survives a long error message being
    word-wrapped across multiple lines inside a bordered panel."""
    stripped = text.translate({ord(c): " " for c in _BOX_DRAWING_CHARS})
    return " ".join(stripped.split())


def _make_case_with_two_entities(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A case with one EvidenceItem and two Entities derived from it.
    Returns (case_dir, evidence_id, host_entity_id, ip_entity_id)."""
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    evidence = EvidenceItem.create(
        raw_bytes=b"synthetic log line",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="synthetic.jsonl:1",
        collected_at=NOW,
    )
    case.store.put_evidence(evidence)
    host = Entity(
        entity_type="host", identifiers={"hostname": "corp-ws-1"}, derived_from=(evidence.id,)
    )
    ip = Entity(
        entity_type="ip", identifiers={"address": "203.0.113.7"}, derived_from=(evidence.id,)
    )
    case.store.put_entity(host)
    case.store.put_entity(ip)
    case.record_manifest()
    case.close()
    return case_dir, evidence.id, host.id, ip.id


# -- create -----------------------------------------------------------------


def test_create_new_relationship_succeeds(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    assert result.exit_code == 0
    assert "created relationship" in result.stdout


def test_create_is_idempotent_on_identical_rerun(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    args = [
        "relationships", "create", str(case_dir), "connected_to",
        "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
    ]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "created relationship" in first.stdout
    assert "already exists -- unchanged" in second.stdout

    case = Case.open(case_dir)
    assert len(case.store.list_relationships()) == 1
    case.close()


def test_create_with_attributes_round_trips(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
            "--attribute", "protocol=tcp", "--attribute", "port=443",
        ],
    )
    assert result.exit_code == 0
    rel_id = result.stdout.split()[2].rstrip(":")

    show = runner.invoke(app, ["relationships", "show", str(case_dir), rel_id])
    assert show.exit_code == 0
    doc = json.loads(show.stdout)
    assert doc["attributes"] == {"protocol": "tcp", "port": "443"}
    assert doc["source_entity_id"] == host_id
    assert doc["target_entity_id"] == ip_id
    assert doc["relationship_type"] == "connected_to"
    assert doc["derived_from"] == [ev_id]


def test_create_rejects_unknown_source_entity(tmp_path: Path) -> None:
    case_dir, ev_id, _host_id, ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", "no-such-entity", "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "not a known Entity id" in _flatten(result.stderr)


def test_create_rejects_unknown_target_entity(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, _ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", "no-such-entity", "--derived-from", ev_id,
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "not a known Entity id" in _flatten(result.stderr)


def test_create_rejects_unknown_derived_from_id(tmp_path: Path) -> None:
    case_dir, _ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", "no-such-evidence",
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "not a known EvidenceItem/NormalizedEvent id" in _flatten(result.stderr)


def test_create_rejects_self_loop(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, _ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", host_id, "--derived-from", ev_id,
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "must differ" in _flatten(result.stderr)


def test_create_rejects_malformed_attribute(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
            "--attribute", "no-equals-sign",
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "key=value" in _flatten(result.stderr)


def test_create_rejects_blank_relationship_type(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "   ",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


# -- list / show --------------------------------------------------------------


def test_list_on_empty_case_reports_none(tmp_path: Path) -> None:
    case_dir, _ev_id, _host_id, _ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(app, ["relationships", "list", str(case_dir)])
    assert result.exit_code == 0
    assert result.stdout.strip() == "no relationships"


def test_list_shows_multiple_relationships_sorted_by_id(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "resolved_from",
            "--source", ip_id, "--target", host_id, "--derived-from", ev_id,
        ],
    )
    result = runner.invoke(app, ["relationships", "list", str(case_dir)])
    assert result.exit_code == 0
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines == sorted(lines)  # sorted by id, ascending


def test_list_filtered_by_entity_shows_only_matching(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    case = Case.open(case_dir)
    third = Entity(entity_type="user", identifiers={"name": "alice"}, derived_from=(ev_id,))
    case.store.put_entity(third)
    case.close()

    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "authenticated_as",
            "--source", third.id, "--target", host_id, "--derived-from", ev_id,
        ],
    )

    filtered = runner.invoke(app, ["relationships", "list", str(case_dir), "--entity", ip_id])
    assert filtered.exit_code == 0
    lines = [line for line in filtered.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    assert ip_id in lines[0]

    filtered_host = runner.invoke(
        app, ["relationships", "list", str(case_dir), "--entity", host_id]
    )
    lines_host = [line for line in filtered_host.stdout.splitlines() if line.strip()]
    assert len(lines_host) == 2  # host is source of one, target of the other


def test_show_unknown_relationship_fails_cleanly(tmp_path: Path) -> None:
    case_dir, _ev_id, _host_id, _ip_id = _make_case_with_two_entities(tmp_path)
    result = runner.invoke(app, ["relationships", "show", str(case_dir), "no-such-id"])
    assert result.exit_code != 0
    assert "no such relationship" in _flatten(result.stderr)


# -- report integration (Markdown + JSON) --------------------------------------


def test_relationship_appears_in_markdown_report(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
            "--attribute", "protocol=tcp",
        ],
    )
    case = Case.open(case_dir)
    report = render_report(
        case_name="case",
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    case.close()
    assert "## Relationships" in report
    assert f"source_entity_id: `{host_id}`" in report
    assert f"target_entity_id: `{ip_id}`" in report
    assert "connected_to" in report
    assert "protocol" in report and "tcp" in report
    # Relationships section must render before Hypotheses (evidence ->
    # entities -> relationships -> hypotheses).
    assert report.index("## Relationships") < report.index("## Hypotheses")
    assert report.index("## Entities") < report.index("## Relationships")


def test_relationship_appears_in_json_report(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    case = Case.open(case_dir)
    tree = build_report_json_tree(
        case_name="case",
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    case.close()
    assert len(tree["relationships"]) == 1
    entry = tree["relationships"][0]
    assert entry["source_entity_id"] == host_id
    assert entry["target_entity_id"] == ip_id
    assert entry["relationship_type"] == "connected_to"
    assert entry["derived_from"] == [ev_id]


def test_report_json_full_document_includes_relationships_via_cli(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    result = runner.invoke(app, ["report", str(case_dir), "--format", "json"])
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert len(doc["relationships"]) == 1
    assert doc["relationships"][0]["relationship_type"] == "connected_to"


# -- export / import / verify --------------------------------------------------


def test_export_import_round_trip_preserves_relationships(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    archive = tmp_path / "case.wgcase"
    export_result = runner.invoke(app, ["export", str(case_dir), str(archive)])
    assert export_result.exit_code == 0

    restored_dir = tmp_path / "restored"
    import_result = runner.invoke(app, ["import", str(archive), str(restored_dir)])
    assert import_result.exit_code == 0

    restored = Case.open(restored_dir)
    restored_relationships = restored.store.list_relationships()
    restored.close()
    assert len(restored_relationships) == 1
    assert restored_relationships[0].relationship_type == "connected_to"

    verify_result = runner.invoke(app, ["verify", str(restored_dir)])
    assert verify_result.exit_code == 0
    assert "MATCH" in verify_result.stdout


def test_verify_matches_after_creating_a_relationship(tmp_path: Path) -> None:
    case_dir, ev_id, host_id, ip_id = _make_case_with_two_entities(tmp_path)
    runner.invoke(
        app,
        [
            "relationships", "create", str(case_dir), "connected_to",
            "--source", host_id, "--target", ip_id, "--derived-from", ev_id,
        ],
    )
    result = runner.invoke(app, ["verify", str(case_dir)])
    assert result.exit_code == 0
    assert "MATCH" in result.stdout
