"""DESIGN.md principle 4: every exported case must be independently reproducible."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import replay_and_verify
from witnessgraph.store.case import Case

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _build_populated_case(root: Path) -> Case:
    case = Case.create(root)
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    result = ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    assert result.evidence_count > 0

    evidence_ids = [e.id for e in case.store.list_evidence()]
    entity = Entity(
        entity_type="host", identifiers={"hostname": "ws-01"}, derived_from=(evidence_ids[0],)
    )
    case.store.put_entity(entity)

    hyp = Hypothesis(
        statement="alice's workstation made an outbound connection after logon",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=evidence_ids[0]),),
        inferred_by="analyst:test",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    return case


def test_export_then_import_produces_identical_manifest_hash(tmp_path: Path) -> None:
    original_case = _build_populated_case(tmp_path / "original")
    original_manifest = original_case.record_manifest()

    archive = export_case(original_case, tmp_path / "case.wgcase")
    original_case.close()

    restored_case = import_case(archive, tmp_path / "restored")
    restored_manifest = restored_case.compute_manifest()

    assert restored_manifest.manifest_hash == original_manifest.manifest_hash
    assert restored_manifest.collection_hashes == original_manifest.collection_hashes
    restored_case.close()


def test_restored_case_contents_match_original(tmp_path: Path) -> None:
    original_case = _build_populated_case(tmp_path / "original")
    archive = export_case(original_case, tmp_path / "case.wgcase")
    original_ids = {e.id for e in original_case.store.list_evidence()}
    original_case.close()

    restored_case = import_case(archive, tmp_path / "restored")
    restored_ids = {e.id for e in restored_case.store.list_evidence()}
    assert restored_ids == original_ids
    assert len(restored_case.store.list_hypotheses()) == 1
    assert len(restored_case.store.list_entities()) == 1
    restored_case.close()


def test_replay_matches_recorded_manifest_after_import(tmp_path: Path) -> None:
    original_case = _build_populated_case(tmp_path / "original")
    archive = export_case(original_case, tmp_path / "case.wgcase")
    original_case.close()

    restored_case = import_case(archive, tmp_path / "restored")
    result = replay_and_verify(restored_case)
    assert result.matches_recorded
    assert result.recorded_manifest is not None
    assert result.recomputed_manifest.manifest_hash == result.recorded_manifest.manifest_hash
    restored_case.close()


def test_export_then_reimport_twice_yields_same_hash_both_times(tmp_path: Path) -> None:
    """Re-running the whole export/import round trip independently should be
    just as reproducible the second time -- this guards against any hidden
    dependency on wall-clock time or process state."""
    original_case = _build_populated_case(tmp_path / "original")
    original_manifest = original_case.record_manifest()
    original_case.close()

    hashes = set()
    for i in range(2):
        source_case = Case.open(tmp_path / "original")
        archive = export_case(source_case, tmp_path / f"case-{i}.wgcase")
        source_case.close()
        restored = import_case(archive, tmp_path / f"restored-{i}")
        hashes.add(restored.compute_manifest().manifest_hash)
        restored.close()

    assert hashes == {original_manifest.manifest_hash}
