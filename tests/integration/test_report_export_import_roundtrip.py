"""Report-level reproducibility: export -> import -> report must render
byte-identical output to report-on-the-original-case, and repeated report
generation against an unchanged case must be byte-identical.

New test module -- does not modify tests/integration/test_export_import_roundtrip.py.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.base import SourceDescriptor
from witnessgraph.ingest.pipeline import ingest_source
from witnessgraph.portable import export_case, import_case
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _build_populated_case(root: Path) -> Case:
    case = Case.create(root)
    source = SourceDescriptor(path=FIXTURES / "sample_events.jsonl")
    ingest_source(case, JsonlAdapter(), source, collected_at=NOW)
    evidence_ids = [e.id for e in case.store.list_evidence()]
    entity = Entity(
        entity_type="host", identifiers={"hostname": "ws-report"}, derived_from=(evidence_ids[0],)
    )
    case.store.put_entity(entity)
    hyp = Hypothesis(
        statement="a report-reproducibility test hypothesis",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=evidence_ids[0]),),
        inferred_by="analyst:report-test",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    case.record_manifest()
    return case


def _report_for(case: Case, case_name: str) -> str:
    return render_report(
        case_name=case_name,
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )


def test_report_is_identical_across_repeated_generation(tmp_path: Path) -> None:
    case = _build_populated_case(tmp_path / "original")
    first = _report_for(case, "original")
    second = _report_for(case, "original")
    assert first == second
    case.close()


def test_report_identical_before_and_after_export_import(tmp_path: Path) -> None:
    original = _build_populated_case(tmp_path / "original")
    original_report = _report_for(original, "original")

    archive = export_case(original, tmp_path / "case.wgcase")
    original.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_report = _report_for(restored, "original")  # same logical case_name
    assert restored_report == original_report
    restored.close()
