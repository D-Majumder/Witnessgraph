"""Golden run of examples/sample-case: the full pipeline, end to end, via the library.

This mirrors examples/sample-case/run_example.py (which drives the same
pipeline via the CLI) but calls the library directly so it runs fast as
part of the normal test suite. Both must keep working; run_example.py is
exercised separately in CI/verification as the CLI-level demonstration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis, HypothesisStatus
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.ingest.adapters.csv_timeline_adapter import CsvTimelineAdapter
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.adapters.syslog_adapter import SyslogAdapter
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import replay_and_verify
from witnessgraph.store.case import Case

EXAMPLE_DATA = Path(__file__).parent.parent.parent / "examples" / "sample-case" / "data"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_golden_sample_case_full_pipeline(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")

    jsonl_source = SourceDescriptor(path=EXAMPLE_DATA / "events.jsonl")
    jsonl_result = ingest_source(case, JsonlAdapter(), jsonl_source, collected_at=NOW)

    csv_source = SourceDescriptor(path=EXAMPLE_DATA / "timeline.csv")
    csv_result = ingest_source(case, CsvTimelineAdapter(), csv_source, collected_at=NOW)

    syslog_source = SourceDescriptor(path=EXAMPLE_DATA / "auth.syslog")
    syslog_result = ingest_source(case, SyslogAdapter(), syslog_source, collected_at=NOW)

    assert jsonl_result.evidence_count == 4
    assert jsonl_result.normalized_event_count == 4
    assert jsonl_result.time_assertion_count == 4  # all four lines carry a valid timestamp

    assert csv_result.evidence_count == 3
    assert csv_result.time_assertion_count == 3

    assert syslog_result.evidence_count == 2
    assert syslog_result.normalized_event_count == 2
    assert syslog_result.time_assertion_count == 0  # BSD syslog lines carry no parseable timezone

    total_evidence = len(case.store.list_evidence())
    assert total_evidence == 4 + 3 + 2

    # entities: explicit, not auto-resolved
    first_evidence_id = case.store.list_evidence()[0].id
    entity = Entity(
        entity_type="host",
        identifiers={"hostname": "corp-ws-042"},
        derived_from=(first_evidence_id,),
    )
    case.store.put_entity(entity)
    assert len(case.store.list_entities()) == 1

    # timeline: every normalized event is orderable
    events = case.store.list_normalized_events()
    assert len(events) == 4 + 3 + 2

    # contradictions: none expected in this consistent synthetic dataset
    assert detect_time_contradictions(case.store) == []

    # hypothesis: evidence-backed claim
    hyp = Hypothesis(
        statement="jsmith's workstation ran obfuscated PowerShell after opening a macro document",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=first_evidence_id),),
        inferred_by="analyst:golden-test",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    supported = hyp.with_status(HypothesisStatus.SUPPORTED)
    case.store.put_hypothesis(supported)
    assert case.store.get_hypothesis(hyp.id).status == HypothesisStatus.SUPPORTED  # type: ignore[union-attr]

    # export -> fresh import -> identical manifest hash
    original_manifest = case.record_manifest()
    archive = export_case(case, tmp_path / "golden.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "golden-restored")
    result = replay_and_verify(restored)

    assert result.recomputed_manifest.manifest_hash == original_manifest.manifest_hash
    assert result.matches_recorded
    assert len(restored.store.list_evidence()) == total_evidence
    assert len(restored.store.list_entities()) == 1
    assert len(restored.store.list_hypotheses()) == 1
    restored.close()
