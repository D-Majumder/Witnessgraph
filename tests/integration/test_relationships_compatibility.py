"""Compatibility of the v1.1 (relationships) manifest algorithm with
pre-v1.1 (manifest_version 2) case data.

Mirrors test_v03_compatibility.py's approach exactly, applied to the new
bump: builds a case with a manifest.json recorded under the old
(pre-relationships, version 2) algorithm and confirms v1.1 code can open,
report on, verify, and export/import it unchanged -- and that a v2
recorded manifest against a v3 recompute is reported as version-
incomparable, never a false MISMATCH, exactly like the v0.1/v0.2 -> v0.3
transition this precedent is drawn from.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.ids import canonical_json_bytes, sha256_hex
from witnessgraph.core.provenance import content_hash_of
from witnessgraph.core.relationships import Relationship
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import replay_and_verify
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _build_pre_relationships_case(root: Path) -> Case:
    """A case shaped exactly like something pre-v1.1 code would have
    produced: no relationships table content, and a manifest.json written
    by the v2 (pre-relationships) algorithm -- reproduced here verbatim,
    not imported from provenance.py, so this fixture stays a faithful
    snapshot even if that module changes further in the future."""
    case = Case.create(root)
    evidence = EvidenceItem.create(
        raw_bytes=b"pre-relationships evidence",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="legacy.jsonl:1",
        collected_at=NOW,
    )
    case.store.put_evidence(evidence)

    entity = Entity(
        entity_type="host", identifiers={"hostname": "legacy-host"}, derived_from=(evidence.id,)
    )
    case.store.put_entity(entity)

    # Old (v2) manifest algorithm: no "relationships" collection at all.
    def _collection_hash(hashes: dict[str, str]) -> str:
        return sha256_hex(canonical_json_bytes(sorted(hashes.items())))

    collections = {
        "evidence_items": {evidence.id: evidence.raw_content_hash},
        "normalized_events": {},
        "entities": {entity.id: content_hash_of(entity)},
        "time_assertions": {},
        "hypotheses": {},
    }
    collection_hashes = {name: _collection_hash(h) for name, h in collections.items()}
    manifest_hash = sha256_hex(canonical_json_bytes(sorted(collection_hashes.items())))
    legacy_manifest_json = json.dumps(
        {
            "collection_hashes": collection_hashes,
            "manifest_hash": manifest_hash,
            "manifest_version": 2,
        }
    )
    (case.root / "manifest.json").write_text(legacy_manifest_json)

    return case


def test_pre_relationships_case_opens_and_reports_without_error(tmp_path: Path) -> None:
    case = _build_pre_relationships_case(tmp_path / "legacy")
    report = render_report(
        case_name="legacy",
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Relationships" in report
    assert "(none)" in report  # the lazily-created relationships table is empty
    case.close()


def test_pre_relationships_case_manifest_loads_as_version_2(tmp_path: Path) -> None:
    case = _build_pre_relationships_case(tmp_path / "legacy")
    recorded = case.load_recorded_manifest()
    assert recorded is not None
    assert recorded.manifest_version == 2
    case.close()


def test_pre_relationships_case_replay_reports_not_comparable_not_a_false_mismatch(
    tmp_path: Path,
) -> None:
    """A v2-recorded manifest against a v3-recomputed one must be reported
    as version-incomparable, never as a false MISMATCH -- the case was not
    tampered with, the algorithm changed to add the relationships
    collection (see core/provenance.py's v1.1 docstring note)."""
    case = _build_pre_relationships_case(tmp_path / "legacy")
    result = replay_and_verify(case)
    assert result.version_comparable is False
    assert result.recorded_manifest is not None
    assert result.recorded_manifest.manifest_version == 2
    assert result.recomputed_manifest.manifest_version == 3
    case.close()


def test_relationships_table_is_lazily_created_and_usable_on_a_pre_v1_1_case(
    tmp_path: Path,
) -> None:
    """The new `relationships` SQLite table does not exist in a pre-v1.1
    case.db, but SqliteStore's `CREATE TABLE IF NOT EXISTS` schema (run
    unconditionally on every open) bootstraps it lazily -- no migration
    step is required, and creating a relationship on a case opened this
    way works exactly as it would on a freshly created case."""
    case = _build_pre_relationships_case(tmp_path / "legacy")
    entity_a = case.store.list_entities()[0]
    evidence = case.store.list_evidence()[0]
    entity_b = Entity(
        entity_type="ip", identifiers={"address": "203.0.113.7"}, derived_from=(evidence.id,)
    )
    case.store.put_entity(entity_b)

    relationship = Relationship.create(
        relationship_type="connected_to",
        source_entity_id=entity_a.id,
        target_entity_id=entity_b.id,
        derived_from=(evidence.id,),
        created_at=NOW,
    )
    case.store.put_relationship(relationship)
    assert case.store.get_relationship(relationship.id) == relationship
    assert len(case.store.list_relationships()) == 1
    case.close()


def test_pre_relationships_case_export_import_round_trip_preserves_old_ids(
    tmp_path: Path,
) -> None:
    case = _build_pre_relationships_case(tmp_path / "legacy")
    legacy_entity_id = case.store.list_entities()[0].id
    archive = export_case(case, tmp_path / "legacy.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    ids = {e.id for e in restored.store.list_entities()}
    assert legacy_entity_id in ids
    assert restored.store.list_relationships() == []
    restored.close()
