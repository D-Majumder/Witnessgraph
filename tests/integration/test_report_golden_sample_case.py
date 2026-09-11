"""New v0.2 golden report test.

Builds its own Store using the existing, UNMODIFIED
examples/sample-case/data/* files as raw evidence content -- but,
unlike tests/integration/test_golden_sample_case.py, does not run them
through the real ingestion adapters (whose NormalizedEvent/TimeAssertion
ids are randomly generated per DESIGN.md's known v0.1 follow-up, so a
literal byte-for-byte golden comparison is only possible with
deterministic, hand-assigned ids for derived objects). This module does
not import from, modify, or otherwise touch
tests/integration/test_golden_sample_case.py or
examples/sample-case/data/*.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis, HypothesisStatus
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case

EXAMPLE_DATA = Path(__file__).parent.parent.parent / "examples" / "sample-case" / "data"
GOLDEN_FIXTURE = Path(__file__).parent / "fixtures" / "sample_case_report.md"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _build_golden_case(root: Path) -> Case:
    case = Case.create(root)

    events_evidence = EvidenceItem.create(
        raw_bytes=(EXAMPLE_DATA / "events.jsonl").read_bytes(),
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="examples/sample-case/data/events.jsonl",
        collected_at=NOW,
    )
    timeline_evidence = EvidenceItem.create(
        raw_bytes=(EXAMPLE_DATA / "timeline.csv").read_bytes(),
        source_adapter="csv_timeline",
        adapter_version="0.1.0",
        source_locator="examples/sample-case/data/timeline.csv",
        collected_at=NOW,
    )
    syslog_evidence = EvidenceItem.create(
        raw_bytes=(EXAMPLE_DATA / "auth.syslog").read_bytes(),
        source_adapter="syslog",
        adapter_version="0.1.0",
        source_locator="examples/sample-case/data/auth.syslog",
        collected_at=NOW,
    )
    case.store.put_evidence(events_evidence)
    case.store.put_evidence(timeline_evidence)
    case.store.put_evidence(syslog_evidence)

    event = NormalizedEvent(
        id="a0000000-0000-0000-0000-000000000001",
        event_type="process_start",
        attributes={"host": "corp-ws-042", "process": "powershell.exe"},
        derived_from=(events_evidence.id,),
        created_at=NOW,
    )
    case.store.put_normalized_event(event)

    assertion = TimeAssertion(
        id="b0000000-0000-0000-0000-000000000001",
        subject_event_id=event.id,
        value=datetime(2026, 1, 1, 8, 30, 0, tzinfo=UTC),
        precision=TimePrecision.SECOND,
        source_evidence_id=events_evidence.id,
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    case.store.put_time_assertion(assertion)

    entity = Entity(
        id="c0000000-0000-0000-0000-000000000001",
        entity_type="host",
        identifiers={"hostname": "corp-ws-042"},
        derived_from=(events_evidence.id,),
    )
    case.store.put_entity(entity)

    hypothesis = Hypothesis(
        id="d0000000-0000-0000-0000-000000000001",
        statement="corp-ws-042 ran obfuscated PowerShell after opening a macro document",
        status=HypothesisStatus.SUPPORTED,
        supporting_evidence=(
            EvidenceRef(kind="evidence_item", id=events_evidence.id),
            EvidenceRef(kind="evidence_item", id=syslog_evidence.id),
        ),
        inferred_by="analyst:golden-report-test",
        created_at=NOW,
    )
    case.store.put_hypothesis(hypothesis)

    case.record_manifest()
    return case


def test_golden_sample_case_report_matches_committed_fixture(tmp_path: Path) -> None:
    case = _build_golden_case(tmp_path / "golden-case")
    report = render_report(
        case_name="sample-case",
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    expected = GOLDEN_FIXTURE.read_text(encoding="utf-8")
    assert report == expected
    case.close()
