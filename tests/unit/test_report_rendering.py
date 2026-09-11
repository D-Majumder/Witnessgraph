"""Unit tests for witnessgraph.report.render: section content, ordering, empty
sections, optional values, and evidence/inference separation."""

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

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _evidence(content: bytes = b"hello world", locator: str = "src.log:1") -> EvidenceItem:
    return EvidenceItem.create(
        raw_bytes=content,
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator=locator,
        collected_at=NOW,
    )


def test_empty_case_renders_all_seven_sections_as_empty(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    manifest = case.compute_manifest()
    report = render_report(
        case_name="my-case", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    for heading in (
        "# Witnessgraph Investigation Report",
        "## Evidence Inventory",
        "## Timeline",
        "## Entities",
        "## Hypotheses",
        "## Contradictions",
        "## Integrity Summary",
    ):
        assert heading in report
    assert report.count("(none)") == 5  # evidence, timeline, entities, hypotheses, contradictions
    assert "Case: `my-case`" in report
    assert "(no recorded manifest)" in report
    case.close()


def test_evidence_inventory_sorted_by_id_and_shows_custody(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    e1 = _evidence(b"aaa", "loc-a")
    e2 = _evidence(b"bbb", "loc-b")
    case.store.put_evidence(e1)
    case.store.put_evidence(e2)
    manifest = case.compute_manifest()
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    expected_order = sorted([e1.id, e2.id])
    idx0 = report.index(expected_order[0])
    idx1 = report.index(expected_order[1])
    assert idx0 < idx1
    assert "chain_of_custody" in report
    assert "adapter:jsonl@0.1.0" in report
    case.close()


def test_observed_at_absent_renders_not_set(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.store.put_evidence(_evidence())
    manifest = case.compute_manifest()
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    assert "observed_at: (not set)" in report


def test_entity_first_seen_last_seen_absent_render_not_set(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _evidence()
    case.store.put_evidence(ev)
    entity = Entity(entity_type="host", identifiers={"hostname": "w1"}, derived_from=(ev.id,))
    case.store.put_entity(entity)
    manifest = case.compute_manifest()
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    assert "first_seen: (not set)" in report
    assert "last_seen: (not set)" in report


def test_timeline_orders_by_earliest_time_assertion(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _evidence()
    case.store.put_evidence(ev)
    later = NormalizedEvent(event_type="later", derived_from=(ev.id,), created_at=NOW)
    earlier = NormalizedEvent(event_type="earlier", derived_from=(ev.id,), created_at=NOW)
    case.store.put_normalized_event(later)
    case.store.put_normalized_event(earlier)
    case.store.put_time_assertion(
        TimeAssertion(
            subject_event_id=later.id,
            value=datetime(2026, 6, 1, tzinfo=UTC),
            precision=TimePrecision.EXACT,
            source_evidence_id=ev.id,
            asserted_by="adapter:jsonl",
            created_at=NOW,
        )
    )
    case.store.put_time_assertion(
        TimeAssertion(
            subject_event_id=earlier.id,
            value=datetime(2026, 1, 2, tzinfo=UTC),
            precision=TimePrecision.EXACT,
            source_evidence_id=ev.id,
            asserted_by="adapter:jsonl",
            created_at=NOW,
        )
    )
    manifest = case.compute_manifest()
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    assert report.index(f"`{earlier.id}`") < report.index(f"`{later.id}`")


def test_all_time_assertions_shown_not_just_earliest(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _evidence()
    case.store.put_evidence(ev)
    event = NormalizedEvent(event_type="toggle", derived_from=(ev.id,), created_at=NOW)
    case.store.put_normalized_event(event)
    a1 = TimeAssertion(
        subject_event_id=event.id,
        value=NOW,
        precision=TimePrecision.EXACT,
        source_evidence_id=ev.id,
        asserted_by="source-a",
        created_at=NOW,
    )
    a2 = TimeAssertion(
        subject_event_id=event.id,
        value=datetime(2026, 1, 1, 15, 0, 0, tzinfo=UTC),
        precision=TimePrecision.EXACT,
        source_evidence_id=ev.id,
        asserted_by="source-b",
        created_at=NOW,
    )
    case.store.put_time_assertion(a1)
    case.store.put_time_assertion(a2)
    manifest = case.compute_manifest()
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    assert f"`{a1.id}`" in report
    assert f"`{a2.id}`" in report


def test_hypothesis_supporting_and_contradicting_are_visually_separate(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev1 = _evidence(b"one")
    ev2 = _evidence(b"two")
    case.store.put_evidence(ev1)
    case.store.put_evidence(ev2)
    hyp = Hypothesis(
        statement="the workstation was compromised",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=ev1.id),),
        contradicting_evidence=(EvidenceRef(kind="evidence_item", id=ev2.id),),
        inferred_by="analyst:test",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    manifest = case.compute_manifest()
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    supporting_idx = report.index("Supporting evidence:")
    contradicting_idx = report.index("Contradicting evidence:")
    assert supporting_idx < report.index(ev1.id, supporting_idx) < contradicting_idx
    assert contradicting_idx < report.index(ev2.id, contradicting_idx)
    # evidence/inference separation: the hypothesis statement must not leak
    # into the Timeline or Evidence Inventory sections.
    timeline_section = report[report.index("## Timeline") : report.index("## Entities")]
    evidence_section = report[
        report.index("## Evidence Inventory") : report.index("## Timeline")
    ]
    assert "compromised" not in timeline_section
    assert "compromised" not in evidence_section


def test_dangling_evidence_ref_renders_without_crashing(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    hyp = Hypothesis(
        statement="a claim citing an id that no longer resolves",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id="does-not-exist"),),
        inferred_by="analyst:test",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    manifest = case.compute_manifest()
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=manifest, recorded_manifest=None
    )
    assert "does-not-exist" in report
    assert hyp.status == HypothesisStatus.PROPOSED


def test_integrity_summary_discloses_uncovered_fields(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    manifest = case.record_manifest()
    report = render_report(
        case_name="c",
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=manifest,
    )
    assert "MATCH" in report
    for field in (
        "chain_of_custody",
        "collected_at",
        "source_locator",
        "source_adapter",
        "adapter_version",
        "ingest_parameters",
        "observed_at",
    ):
        assert field in report
    case.close()


def test_integrity_summary_reports_mismatch(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    recorded = case.record_manifest()
    case.store.put_evidence(_evidence())  # change content after recording
    report = render_report(
        case_name="c",
        store=case.store,
        recomputed_manifest=case.compute_manifest(),
        recorded_manifest=recorded,
    )
    assert "MISMATCH" in report
    case.close()
