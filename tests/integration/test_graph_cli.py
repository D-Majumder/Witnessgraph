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

    components_result = runner.invoke(app, ["graph", "components", str(case_dir)])
    assert components_result.exit_code == 0
    assert "nothing to partition" in components_result.stdout


# -- components -----------------------------------------------------------


def _make_two_cluster_case(tmp_path: Path) -> Path:
    """Cluster 1: a 3-cycle A->B->C->A. Cluster 2: X->Y. Plus an
    isolated entity Z with no relationships at all."""
    b = _CaseBuilder(tmp_path / "case")
    b.edge("A", "B")
    b.edge("B", "C")
    b.edge("C", "A")
    b.edge("X", "Y")
    b.entity("Z")
    b.finish()
    return b.case_dir


def test_components_on_empty_case_reports_nothing_to_partition(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()
    result = runner.invoke(app, ["graph", "components", str(case_dir)])
    assert result.exit_code == 0
    assert "nothing to partition" in result.stdout


def test_components_reports_two_clusters_and_excludes_isolated_entity(
    tmp_path: Path,
) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(app, ["graph", "components", str(case_dir)])
    assert result.exit_code == 0
    assert "2 component(s)" in result.stdout
    assert "entity-A" in result.stdout
    assert "entity-X" in result.stdout
    assert "entity-Z" not in result.stdout  # isolated entity excluded entirely


def test_components_cycle_does_not_hang_and_is_one_component(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(app, ["graph", "components", str(case_dir), "--format", "json"])
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    cycle_component = next(c for c in doc["components"] if "entity-A" in c["entity_ids"])
    assert set(cycle_component["entity_ids"]) == {"entity-A", "entity-B", "entity-C"}
    assert len(cycle_component["relationships"]) == 3


def test_components_direction_irrelevant_at_cli_level(tmp_path: Path) -> None:
    """A --connected_to--> B must still join A and B into one component
    even though `graph neighbors` from B (direction=out) finds nothing."""
    b = _CaseBuilder(tmp_path / "case")
    b.edge("A", "B")
    b.finish()
    neighbors_from_b = runner.invoke(app, ["graph", "neighbors", str(b.case_dir), "entity-B"])
    assert "no entities reached" in neighbors_from_b.stdout

    components = runner.invoke(app, ["graph", "components", str(b.case_dir)])
    assert "entity-A" in components.stdout
    assert "entity-B" in components.stdout


def test_components_min_size_filters_and_reports_totals(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "components", str(case_dir), "--min-size", "3"]
    )
    assert result.exit_code == 0
    assert "1 component(s)" in result.stdout
    assert "entity-X" not in result.stdout  # the 2-entity cluster is filtered out


def test_components_min_size_excluding_everything_is_clean_not_an_error(
    tmp_path: Path,
) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "components", str(case_dir), "--min-size", "10"]
    )
    assert result.exit_code == 0
    assert "no components with at least 10" in result.stdout


def test_components_rejects_invalid_min_size(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(app, ["graph", "components", str(case_dir), "--min-size", "0"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_components_rejects_bad_format(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(app, ["graph", "components", str(case_dir), "--format", "xml"])
    assert result.exit_code != 0


def test_components_json_output_is_valid_and_deterministic(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    args = ["graph", "components", str(case_dir), "--format", "json"]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    doc = json.loads(first.stdout)
    assert doc["total_entities_in_graph"] == 5  # A, B, C, X, Y -- not Z
    assert doc["total_relationships"] == 4
    assert doc["total_components_found"] == 2
    assert len(doc["components"]) == 2
    for component in doc["components"]:
        for rel in component["relationships"]:
            assert rel["derived_from"]  # provenance present on every edge
    assert first.stdout == second.stdout


def test_components_provenance_traces_back_to_evidence(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "components", str(case_dir), "--min-size", "3", "--format", "json"]
    )
    doc = json.loads(result.stdout)
    component = doc["components"][0]
    rel_ids = {r["id"] for r in component["relationships"]}
    assert len(rel_ids) == 3  # three distinct relationships, not deduplicated away
    for rel in component["relationships"]:
        assert rel["relationship_type"] == "connected_to"
        assert len(rel["derived_from"]) == 1


def test_components_missing_case_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["graph", "components", str(tmp_path / "does-not-exist")])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "does not look like a Witnessgraph case" in _flatten(result.stderr)


# -- --explain: provenance/lineage expansion -----------------------------------


def test_explain_is_opt_in_default_output_unchanged(tmp_path: Path) -> None:
    """The single most important regression: omitting --explain must
    reproduce byte-identical output to before this capability existed."""
    case_dir = _make_chain_case(tmp_path)
    plain = runner.invoke(app, ["graph", "path", str(case_dir), "entity-A", "entity-B"])
    with_flag_absent = runner.invoke(app, ["graph", "path", str(case_dir), "entity-A", "entity-B"])
    assert plain.stdout == with_flag_absent.stdout
    assert "evidence" not in plain.stdout.lower()

    plain_json = runner.invoke(
        app, ["graph", "path", str(case_dir), "entity-A", "entity-B", "--format", "json"]
    )
    doc = json.loads(plain_json.stdout)
    assert "entities" not in doc
    assert "evidence_lineage" not in doc["steps"][0]["relationship"]


def test_path_explain_text_shows_evidence_and_entities(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "path", str(case_dir), "entity-A", "entity-C", "--explain"]
    )
    assert result.exit_code == 0
    assert "evidence:" in result.stdout
    assert "evidence_item" in result.stdout
    assert "entities:" in result.stdout
    assert "entity-A" in result.stdout
    assert "entity-B" in result.stdout
    assert "entity-C" in result.stdout


def test_path_explain_json_has_full_lineage(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app,
        ["graph", "path", str(case_dir), "entity-A", "entity-C", "--explain", "--format", "json"],
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert set(doc["entities"].keys()) == {"entity-A", "entity-B", "entity-C"}
    assert doc["entities"]["entity-A"]["found"] is True
    for step in doc["steps"]:
        lineage = step["relationship"]["evidence_lineage"]
        assert len(lineage) == 1
        assert lineage[0]["kind"] == "evidence_item"
        assert lineage[0]["evidence_item"]["source_adapter"] == "test"
        # Relationship identity fields are untouched by --explain.
        assert "source_entity_id" in step["relationship"]
        assert "target_entity_id" in step["relationship"]


def test_path_explain_no_path_still_clean_no_lineage_needed(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app,
        ["graph", "path", str(case_dir), "entity-A", "entity-D", "--explain", "--format", "json"],
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["found"] is False
    assert doc["steps"] == []


def test_neighbors_explain_resolves_reached_and_origin_entities(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app,
        ["graph", "neighbors", str(case_dir), "entity-A", "--max-depth", "2", "--explain",
         "--format", "json"],
    )
    doc = json.loads(result.stdout)
    assert set(doc["entities"].keys()) == {"entity-A", "entity-B", "entity-C"}
    for reached in doc["reached"]:
        assert reached["via"]["relationship"]["evidence_lineage"]


def test_components_explain_resolves_member_entities_and_relationships(
    tmp_path: Path,
) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "components", str(case_dir), "--explain", "--format", "json"]
    )
    doc = json.loads(result.stdout)
    assert "entity-Z" not in doc["entities"]  # isolated entity still excluded
    for component in doc["components"]:
        for rel in component["relationships"]:
            assert rel["evidence_lineage"]


def test_components_explain_text_includes_evidence_and_entities(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    result = runner.invoke(app, ["graph", "components", str(case_dir), "--explain"])
    assert result.exit_code == 0
    assert "evidence:" in result.stdout
    assert "entities:" in result.stdout


def test_explain_json_deterministic_across_repeated_calls(tmp_path: Path) -> None:
    case_dir = _make_two_cluster_case(tmp_path)
    args = ["graph", "components", str(case_dir), "--explain", "--format", "json"]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    assert first.stdout == second.stdout


def test_explain_on_case_with_no_relationships_is_clean(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()
    result = runner.invoke(app, ["graph", "components", str(case_dir), "--explain"])
    assert result.exit_code == 0
    assert "nothing to partition" in result.stdout


def test_explain_does_not_affect_missing_entity_error_handling(tmp_path: Path) -> None:
    case_dir = _make_chain_case(tmp_path)
    result = runner.invoke(
        app, ["graph", "path", str(case_dir), "no-such-entity", "entity-B", "--explain"]
    )
    assert result.exit_code != 0
    assert "no such entity" in _flatten(result.stderr)


def test_explain_with_dangling_entity_reports_not_found_not_a_crash(tmp_path: Path) -> None:
    """A relationship whose endpoint entity was never created (bypassing
    the CLI's own referential check, e.g. from a hand-edited case) must
    not crash --explain -- it reports found: false for that id."""
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
    rel = Relationship.create(
        relationship_type="connected_to",
        source_entity_id="ghost-a",
        target_entity_id="ghost-b",
        derived_from=(evidence.id,),
        created_at=NOW,
    )
    case.store.put_relationship(rel)
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app, ["graph", "components", str(case_dir), "--explain", "--format", "json"]
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["entities"]["ghost-a"]["found"] is False
    assert doc["entities"]["ghost-b"]["found"] is False
