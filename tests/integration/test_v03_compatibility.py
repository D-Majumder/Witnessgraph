"""docs/phase3-v0.3-design.md §11/§15/§16: compatibility of v0.3 code with
v0.1/v0.2-era case data.

Builds a case that looks exactly like something v0.1/v0.2 code would have
produced -- random-UUID NormalizedEvent/TimeAssertion ids (bare
constructor, not .create()), and a manifest.json with no manifest_version
field at all (simulating a file written before that field existed) -- and
confirms v0.3 code can open, report on, verify, replay, and export/import
it unchanged, and that ingesting something new into it produces
content-addressed ids for the new records while old records keep their
original ids untouched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis
from witnessgraph.core.ids import canonical_json_bytes, sha256_hex
from witnessgraph.core.provenance import content_hash_of
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import replay_and_verify
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _build_legacy_case(root: Path) -> tuple[Case, str, str]:
    """Build a case matching the pre-v0.3 (v0.1/v0.2) shape exactly:
    random-UUID derived-object ids, and a manifest.json written by the old
    (content_hash_of-based, unversioned) algorithm -- reproduced here
    verbatim, not imported from provenance.py, so this fixture stays a
    faithful snapshot of the old behavior even if that module changes
    further in the future.
    """
    case = Case.create(root)
    evidence = EvidenceItem.create(
        raw_bytes=b"legacy log line",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="legacy.jsonl:1",
        collected_at=NOW,
    )
    case.store.put_evidence(evidence)

    event = NormalizedEvent(  # bare constructor -- random UUID, v0.1/v0.2 style
        event_type="legacy_event",
        attributes={"user": "alice"},
        derived_from=(evidence.id,),
        created_at=NOW,
    )
    case.store.put_normalized_event(event)

    assertion = TimeAssertion(  # bare constructor -- random UUID
        subject_event_id=event.id,
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id=evidence.id,
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    case.store.put_time_assertion(assertion)

    entity = Entity(
        entity_type="host", identifiers={"hostname": "legacy-host"}, derived_from=(evidence.id,)
    )
    case.store.put_entity(entity)

    hyp = Hypothesis(
        statement="legacy hypothesis",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=evidence.id),),
        inferred_by="analyst:legacy",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)

    # Old (v1) manifest algorithm: content_hash_of() for normalized_events/
    # time_assertions, no manifest_version field at all in the JSON.
    def _collection_hash(hashes: dict[str, str]) -> str:
        return sha256_hex(canonical_json_bytes(sorted(hashes.items())))

    collections = {
        "evidence_items": {evidence.id: evidence.raw_content_hash},
        "normalized_events": {event.id: content_hash_of(event)},
        "entities": {entity.id: content_hash_of(entity)},
        "time_assertions": {assertion.id: content_hash_of(assertion)},
        "hypotheses": {hyp.id: content_hash_of(hyp)},
    }
    collection_hashes = {name: _collection_hash(h) for name, h in collections.items()}
    manifest_hash = sha256_hex(canonical_json_bytes(sorted(collection_hashes.items())))
    legacy_manifest_json = json.dumps(
        {"collection_hashes": collection_hashes, "manifest_hash": manifest_hash}
    )
    (case.root / "manifest.json").write_text(legacy_manifest_json)

    return case, event.id, evidence.id


def test_legacy_case_opens_and_reports_without_error(tmp_path: Path) -> None:
    case, _event_id, _evidence_id = _build_legacy_case(tmp_path / "legacy")
    report = render_report(
        case_name="legacy",
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "legacy_event" in report
    assert "## Integrity Summary" in report
    case.close()


def test_legacy_case_manifest_loads_as_version_1_by_default(tmp_path: Path) -> None:
    case, _event_id, _evidence_id = _build_legacy_case(tmp_path / "legacy")
    recorded = case.load_recorded_manifest()
    assert recorded is not None
    assert recorded.manifest_version == 1
    case.close()


def test_legacy_case_replay_reports_not_comparable_not_a_false_mismatch(tmp_path: Path) -> None:
    """A v1-recorded manifest against a v2-recomputed one must be reported as
    version-incomparable, never as a false MISMATCH (the case was not
    tampered with -- the algorithm changed, per docs/phase3-v0.3-design.md §11)."""
    case, _event_id, _evidence_id = _build_legacy_case(tmp_path / "legacy")
    result = replay_and_verify(case)
    assert result.version_comparable is False
    assert result.recorded_manifest is not None
    assert result.recorded_manifest.manifest_version == 1
    assert result.recomputed_manifest.manifest_version == 3
    case.close()


def test_ingesting_new_source_into_legacy_case_uses_v03_ids_for_new_records_only(
    tmp_path: Path,
) -> None:
    case, legacy_event_id, legacy_evidence_id = _build_legacy_case(tmp_path / "legacy")

    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    result = ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    assert result.evidence_count == 5

    events = case.store.list_normalized_events()
    ids = {e.id for e in events}
    assert legacy_event_id in ids  # old record untouched, same id as before

    new_events = [e for e in events if e.id != legacy_event_id]
    assert len(new_events) == 4
    for e in new_events:
        # every genuinely new event's id matches the deterministic v0.3 formula
        assert e.id == NormalizedEvent.identity_hash(
            event_type=e.event_type, attributes=e.attributes, derived_from=e.derived_from
        )
    case.close()


def test_legacy_case_export_import_round_trip_preserves_old_ids(tmp_path: Path) -> None:
    case, legacy_event_id, _evidence_id = _build_legacy_case(tmp_path / "legacy")
    archive = export_case(case, tmp_path / "legacy.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    ids = {e.id for e in restored.store.list_normalized_events()}
    assert legacy_event_id in ids
    restored.close()
