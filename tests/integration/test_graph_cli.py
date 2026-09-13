"""End-to-end CLI coverage for `witnessgraph graph neighbors`/`graph path`:
the first graph-analysis capability built on top of Relationships (v1.1).
Exercises the real CLI via typer.testing.CliRunner, mirroring
test_relationships_cli.py's style.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.entities import Entity
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.relationships import Relationship
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


def _flatten(text: str) -> str:
    box_chars = "─│┌┐└┘├┤┬┴┼"
    return " ".join(text.translate({ord(c): " " for c in box_chars}).split())


class _CaseBuilder:
    """A case with named entities and directed relationships, built
    directly against the store for speed -- mirrors tests/unit/test_graph.py's
    `_Graph` helper, but exposed as a case_dir for CLI-level tests."""

    def __init__(self, case_dir: Path) -> None:
        self.case_dir = case_dir
        self.case = Case.create(case_dir)
        self.evidence = EvidenceItem.create(
            raw_bytes=b"synthetic",
            source_adapter="test",
            adapter_version="0.0.0",
            source_locator="test:1",
            collected_at=NOW,
        )
        self.case.store.put_evidence(self.evidence)
        self.entities: dict[str, str] = {}

    def entity(self, name: str) -> str:
        if name not in self.entities:
            ent = Entity(
                id=f"entity-{name}",
                entity_type="node",
                identifiers={"name": name},
                derived_from=(self.evidence.id,),
            )
            self.case.store.put_entity(ent)
            self.entities[name] = ent.id
        return self.entities[name]

    def edge(self, source: str, target: str, relationship_type: str = "connected_to") -> str:
        rel = Relationship.create(
            relationship_type=relationship_type,
            source_entity_id=self.entity(source),
            target_entity_id=self.entity(target),
            derived_from=(self.evidence.id,),
            created_at=NOW,
        )
        self.case.store.put_relationship(rel)
        return rel.id

    def finish(self) -> None:
        self.case.record_manifest()
        self.case.close()


def _make_chain_case(tmp_path: Path) -> Path:
    """A -> B -> C, plus a disconnected D."""
    b = _CaseBuilder(tmp_path / "case")
    b.edge("A", "B")
    b.edge("B", "C")
    b.entity("D")
    b.finish()
    return b.case_dir


# -- neighbors ----------------------------------------------------------------


def test_neighbors_default_depth_shows_direct_only(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "neighbors", str(case_dir), "entity-A"])
    assert result.exit_code == 0
    assert "entity-B" in result.stdout
    assert "entity-C" not in result.stdout


def test_neighbors_bounded_depth_reaches_further(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "neighbors", str(case_dir), "entity-A", "--max-depth", "2"]
    )
    assert result.exit_code == 0
    assert "entity-B" in result.stdout
    assert "entity-C" in result.stdout


def test_neighbors_on_disconnected_entity_reports_none(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "neighbors", str(case_dir), "entity-D"])
    assert result.exit_code == 0
    assert "no entities reached" in result.stdout


def test_neighbors_unknown_entity_fails_cleanly(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "neighbors", str(case_dir), "no-such-entity"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "no such entity" in _flatten(result.stderr)


def test_neighbors_rejects_invalid_max_depth(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "neighbors", str(case_dir), "entity-A", "--max-depth", "0"]
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "--max-depth" in _flatten(result.stderr)


def test_neighbors_rejects_excessive_max_depth(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "neighbors", str(case_dir), "entity-A", "--max-depth", "9999"]
    )
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_neighbors_rejects_bad_format(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "neighbors", str(case_dir), "entity-A", "--format", "xml"]
    )
    assert result.exit_code != 0


def test_neighbors_direction_in(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "neighbors", str(case_dir), "entity-B", "--direction", "in"]
    )
    assert result.exit_code == 0
    assert "entity-A" in result.stdout


def test_neighbors_json_output_is_valid_and_deterministic(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    args = ["graph", "neighbors", str(case_dir), "entity-A", "--max-depth", "2", "--format", "json"]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    doc = json.loads(first.stdout)
    assert doc["origin_entity_id"] == "entity-A"
    assert doc["direction"] == "out"
    assert doc["max_depth"] == 2
    assert [r["entity_id"] for r in doc["reached"]] == ["entity-B", "entity-C"]
    assert doc["reached"][0]["via"]["relationship"]["derived_from"]
    assert first.stdout == second.stdout  # deterministic


# -- path -----------------------------------------------------------------


def test_path_finds_direct_edge(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "path", str(case_dir), "entity-A", "entity-B"])
    assert result.exit_code == 0
    assert "path found: 1 hop" in result.stdout


def test_path_finds_multi_hop_chain(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "path", str(case_dir), "entity-A", "entity-C"])
    assert result.exit_code == 0
    assert "path found: 2 hop" in result.stdout
    assert "step 1:" in result.stdout
    assert "step 2:" in result.stdout


def test_path_no_path_is_clean_not_an_error(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "path", str(case_dir), "entity-A", "entity-D"])
    assert result.exit_code == 0
    assert "no path found" in result.stdout


def test_path_wrong_direction_reports_no_path(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "path", str(case_dir), "entity-C", "entity-A"])
    assert result.exit_code == 0
    assert "no path found" in result.stdout


def test_path_same_source_and_target(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "path", str(case_dir), "entity-A", "entity-A"])
    assert result.exit_code == 0
    assert "0 hop" in result.stdout


def test_path_unknown_source_entity_fails_cleanly(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "path", str(case_dir), "no-such-entity", "entity-B"])
    assert result.exit_code != 0
    assert "no such entity" in _flatten(result.stderr)


def test_path_unknown_target_entity_fails_cleanly(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(app, ["graph", "path", str(case_dir), "entity-A", "no-such-entity"])
    assert result.exit_code != 0
    assert "no such entity" in _flatten(result.stderr)


def test_path_beyond_max_depth_reports_no_path(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "path", str(case_dir), "entity-A", "entity-C", "--max-depth", "1"]
    )
    assert result.exit_code == 0
    assert "no path found" in result.stdout


def test_path_json_output_shape_and_determinism(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    args = ["graph", "path", str(case_dir), "entity-A", "entity-C", "--format", "json"]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    doc = json.loads(first.stdout)
    assert doc["found"] is True
    assert doc["hop_count"] == 2
    assert len(doc["steps"]) == 2
    assert doc["steps"][0]["relationship"]["source_entity_id"] == "entity-A"
    assert doc["steps"][0]["relationship"]["target_entity_id"] == "entity-B"
    assert doc["steps"][0]["relationship"]["derived_from"]
    assert first.stdout == second.stdout


def test_path_json_no_path_represented_as_data_not_exception(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "path", str(case_dir), "entity-A", "entity-D", "--format", "json"]
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["found"] is False
    assert doc["hop_count"] is None
    assert doc["steps"] == []


def test_path_direction_both_finds_reverse_edge(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "path", str(case_dir), "entity-C", "entity-A", "--direction", "both"]
    )
    assert result.exit_code == 0
    assert "path found: 2 hop" in result.stdout


# -- cycles / branching (CLI-level smoke; algorithmic depth covered in
#    tests/unit/test_graph.py) -----------------------------------------------


def test_cycle_does_not_hang_the_cli(tmp_path: Path) -> None:
    b = _CaseBuilder(tmp_path / "case")
    b.edge("A", "B")
    b.edge("B", "C")
    b.edge("C", "A")
    b.finish()
    result = runner.invoke(
        app, ["graph", "neighbors", str(b.case_dir), "entity-A", "--max-depth", "10"]
    )
    assert result.exit_code == 0
    assert "entity-B" in result.stdout
    assert "entity-C" in result.stdout


def test_branching_graph_path_is_deterministic_across_repeated_cli_calls(tmp_path: Path) -> None:
    b = _CaseBuilder(tmp_path / "case")
    b.edge("A", "B")
    b.edge("A", "C")
    b.edge("B", "D")
    b.edge("C", "D")
    b.finish()
    args = ["graph", "path", str(b.case_dir), "entity-A", "entity-D", "--format", "json"]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    assert first.stdout == second.stdout


# -- empty / minimal cases -----------------------------------------------------


def test_empty_case_neighbors_of_only_entity(tmp_path: Path) -> None:
    b = _CaseBuilder(tmp_path / "case")
    b.entity("Solo")
    b.finish()
    result = runner.invoke(app, ["graph", "neighbors", str(b.case_dir), "entity-Solo"])
    assert result.exit_code == 0
    assert "no entities reached" in result.stdout


def test_case_with_no_entities_at_all_fails_cleanly_for_unknown_id(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()
    result = runner.invoke(app, ["graph", "neighbors", str(case_dir), "anything"])
    assert result.exit_code != 0
    assert "no such entity" in _flatten(result.stderr)


# -- backward compatibility: a case with entities but zero relationships ------


def test_graph_commands_work_on_a_case_predating_relationships(tmp_path: Path) -> None:
    """A case whose relationships table is empty (as any pre-v1.1 case's
    would be, lazily bootstrapped -- see test_relationships_compatibility.py)
    must not error; there is simply nothing to traverse."""
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    evidence = EvidenceItem.create(
        raw_bytes=b"x",
        source_adapter="t",
        adapter_version="0",
        source_locator="x",
        collected_at=NOW,
    )
    case.store.put_evidence(evidence)
    entity = Entity(entity_type="host", identifiers={}, derived_from=(evidence.id,))
    case.store.put_entity(entity)
    case.record_manifest()
    case.close()

    result = runner.invoke(app, ["graph", "neighbors", str(case_dir), entity.id])
    assert result.exit_code == 0
    assert "no entities reached" in result.stdout

    path_result = runner.invoke(app, ["graph", "path", str(case_dir), entity.id, entity.id])
    assert path_result.exit_code == 0
    assert "0 hop" in path_result.stdout
