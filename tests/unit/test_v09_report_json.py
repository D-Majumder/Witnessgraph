"""v0.9: unit tests for witnessgraph.report.render_json -- structured,
machine-readable report output.

Covers: exact per-section shape/field selection, enum/datetime
serialization, canonical encoding, determinism, insertion-order
independence, the coverage_gaps null-vs-empty distinction, always-array
tracked-* collections, Unicode/control-character round-trip fidelity
(explicitly NOT neutralized, unlike Markdown), cross-kind isolation, and
tracked-finding/-contradiction still_reproduced asymmetry.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis, HypothesisStatus
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.core.tracked_finding import FindingStatus
from witnessgraph.correlate.contradiction_tracking import track_contradictions
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.correlate.gaps import find_gaps
from witnessgraph.correlate.tracking import track_findings
from witnessgraph.report.render_json import SCHEMA_VERSION, render_report_json_bytes
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _put_evidence(case: Case, label: str, **kwargs: object) -> EvidenceItem:
    ev = EvidenceItem.create(
        raw_bytes=label.encode(),
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1",
        collected_at=NOW,
        **kwargs,  # type: ignore[arg-type]
    )
    case.store.put_evidence(ev)
    return ev


def _render(case: Case, **kwargs: object) -> dict:  # type: ignore[type-arg]
    manifest = case.compute_manifest()
    raw = render_report_json_bytes(
        case_name="x",
        store=case.store,
        recomputed_manifest=manifest,
        recorded_manifest=case.load_recorded_manifest(),
        **kwargs,  # type: ignore[arg-type]
    )
    return json.loads(raw)  # type: ignore[no-any-return]


# -- Top-level shape / schema_version --------------------------------------------


def test_schema_version_is_exactly_1(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    doc = _render(case)
    assert doc["schema_version"] == 1
    assert SCHEMA_VERSION == 1
    case.close()


def test_top_level_keys_are_exactly_the_specified_set(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    doc = _render(case)
    assert set(doc.keys()) == {
        "schema_version", "case_name", "manifest", "evidence", "timeline",
        "entities", "relationships", "hypotheses", "contradictions", "coverage_gaps",
        "tracked_findings", "tracked_contradictions",
    }
    case.close()


def test_case_name_is_passed_through(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    doc = _render(case)
    assert doc["case_name"] == "x"
    case.close()


# -- manifest / verdict -----------------------------------------------------------


def test_manifest_verdict_match(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    doc = _render(case)
    assert doc["manifest"]["verdict"] == "MATCH"
    assert doc["manifest"]["recorded"] is not None
    assert (
        doc["manifest"]["recomputed"]["manifest_hash"]
        == doc["manifest"]["recorded"]["manifest_hash"]
    )
    case.close()


def test_manifest_verdict_no_recorded_manifest(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    # No case.record_manifest() call -- no manifest.json exists.
    doc = _render(case)
    assert doc["manifest"]["verdict"] == "NO_RECORDED_MANIFEST"
    assert doc["manifest"]["recorded"] is None
    case.close()


def test_manifest_verdict_mismatch(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    _put_evidence(case, "a")  # changes recomputed hash after recording
    doc = _render(case)
    assert doc["manifest"]["verdict"] == "MISMATCH"
    case.close()


# -- evidence / chain_of_custody ---------------------------------------------------


def test_evidence_shape_and_sorting(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev1 = _put_evidence(case, "b", source_id="host2")
    ev2 = _put_evidence(case, "a", source_id="host1")
    case.record_manifest()
    doc = _render(case)
    ids = [e["id"] for e in doc["evidence"]]
    assert ids == sorted([ev1.id, ev2.id])
    entry = next(e for e in doc["evidence"] if e["id"] == ev2.id)
    assert entry["source_adapter"] == "jsonl"
    assert entry["adapter_version"] == "0.1.0"
    assert entry["source_locator"] == "a.jsonl:1"
    assert entry["raw_size_bytes"] == 1
    assert entry["observed_at"] is None
    assert len(entry["chain_of_custody"]) == 1
    custody = entry["chain_of_custody"][0]
    assert custody["source_id"] == "host1"
    assert set(custody.keys()) == {"actor", "action", "timestamp", "source_locator", "source_id"}
    assert set(entry.keys()) == {
        "id", "source_adapter", "adapter_version", "source_locator", "raw_size_bytes",
        "collected_at", "observed_at", "chain_of_custody",
    }
    case.close()


# -- entities -----------------------------------------------------------------------


def test_entities_shape_and_values(tmp_path: Path) -> None:
    """Regression for adversarial-review gap: entities[] previously had
    zero test coverage of its shape -- every prior test left it empty."""
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    entity = Entity(
        entity_type="host",
        identifiers={"hostname": "web-01", "ip": "203.0.113.7"},
        first_seen=NOW,
        last_seen=NOW + timedelta(hours=1),
        derived_from=(ev.id,),
    )
    case.store.put_entity(entity)
    case.record_manifest()
    doc = _render(case)

    assert len(doc["entities"]) == 1
    entry = doc["entities"][0]
    assert entry["id"] == entity.id
    assert entry["entity_type"] == "host"
    assert entry["identifiers"] == {"hostname": "web-01", "ip": "203.0.113.7"}
    assert entry["first_seen"] == "2026-01-01T12:00:00Z"
    assert entry["last_seen"] == "2026-01-01T13:00:00Z"
    assert entry["derived_from"] == [ev.id]
    assert set(entry.keys()) == {
        "id", "entity_type", "identifiers", "first_seen", "last_seen", "derived_from",
    }
    case.close()


def test_entities_null_first_seen_last_seen(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    entity = Entity(entity_type="ip", identifiers={}, derived_from=(ev.id,))
    case.store.put_entity(entity)
    case.record_manifest()
    doc = _render(case)
    entry = doc["entities"][0]
    assert entry["first_seen"] is None
    assert entry["last_seen"] is None
    assert entry["identifiers"] == {}
    case.close()


# -- timeline -----------------------------------------------------------------------


def test_timeline_shape_and_time_assertion_field_selection(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    event = NormalizedEvent.create(
        event_type="line", attributes={"k": "v"}, derived_from=(ev.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    assertion = TimeAssertion.create(
        subject_event_id=event.id, value=NOW, precision=TimePrecision.SECOND,
        source_evidence_id=ev.id, asserted_by="test", created_at=NOW,
    )
    case.store.put_time_assertion(assertion)
    case.record_manifest()
    doc = _render(case)
    assert len(doc["timeline"]) == 1
    entry = doc["timeline"][0]
    assert entry["id"] == event.id
    assert entry["event_type"] == "line"
    assert entry["attributes"] == {"k": "v"}
    assert entry["derived_from"] == [ev.id]
    assert entry["entity_ids"] == []
    assert len(entry["time_assertions"]) == 1
    ta = entry["time_assertions"][0]
    assert ta["id"] == assertion.id
    assert ta["precision"] == "second"
    assert ta["asserted_by"] == "test"
    assert ta["source_evidence_id"] == ev.id
    # asserted_by shown, but created_at/subject_event_id are NOT (parity with Markdown).
    assert set(ta.keys()) == {"id", "value", "precision", "asserted_by", "source_evidence_id"}
    case.close()


# -- enums --------------------------------------------------------------------------


def test_time_precision_enum_serialized_as_value(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    event = NormalizedEvent.create(
        event_type="line", attributes={}, derived_from=(ev.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event.id, value=NOW, precision=TimePrecision.APPROXIMATE,
            source_evidence_id=ev.id, asserted_by="t", created_at=NOW,
        )
    )
    case.record_manifest()
    doc = _render(case)
    assert doc["timeline"][0]["time_assertions"][0]["precision"] == "approximate"
    case.close()


def test_hypothesis_status_enum_serialized_as_value(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    hyp = Hypothesis(
        statement="s", supporting_evidence=(EvidenceRef(kind="evidence_item", id=ev.id),),
        status=HypothesisStatus.SUPPORTED, inferred_by="analyst:x", created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    case.record_manifest()
    doc = _render(case)
    assert doc["hypotheses"][0]["status"] == "supported"
    case.close()


def test_hypothesis_exact_field_set_including_contradicting_evidence(tmp_path: Path) -> None:
    """Regression for adversarial-review gap: hypotheses[]'s exact key
    set (specifically with a populated contradicting_evidence) was never
    asserted, unlike evidence[]/timeline[].time_assertions[]."""
    case = Case.create(tmp_path / "case")
    ev1 = _put_evidence(case, "a")
    ev2 = _put_evidence(case, "b")
    hyp = Hypothesis(
        statement="s",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=ev1.id),),
        contradicting_evidence=(EvidenceRef(kind="evidence_item", id=ev2.id),),
        status=HypothesisStatus.CONTRADICTED,
        inferred_by="analyst:x",
        created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    case.record_manifest()
    doc = _render(case)
    entry = doc["hypotheses"][0]
    assert set(entry.keys()) == {
        "id", "statement", "status", "inferred_by", "created_at",
        "supporting_evidence", "contradicting_evidence",
    }
    assert entry["supporting_evidence"] == [{"kind": "evidence_item", "id": ev1.id}]
    assert entry["contradicting_evidence"] == [{"kind": "evidence_item", "id": ev2.id}]
    case.close()


def test_datetime_is_serialized_as_utc_z_suffixed_in_actual_json_output(tmp_path: Path) -> None:
    """Direct test of the actual JSON report output's datetime string
    format (not the underlying canonical_json_bytes helper in
    isolation): a known non-UTC-offset datetime must appear as its exact
    UTC, Z-suffixed ISO-8601 equivalent."""
    case = Case.create(tmp_path / "case")
    non_utc = datetime(2026, 1, 1, 17, 0, 0, tzinfo=timezone(timedelta(hours=5)))
    ev = EvidenceItem.create(
        raw_bytes=b"x", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="x.jsonl:1", collected_at=non_utc,
    )
    case.store.put_evidence(ev)
    case.record_manifest()

    raw = render_report_json_bytes(
        case_name="x", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert b'"collected_at":"2026-01-01T12:00:00Z"' in raw

    doc = json.loads(raw)
    assert doc["evidence"][0]["collected_at"] == "2026-01-01T12:00:00Z"
    case.close()


def test_finding_status_enum_serialized_as_value(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put_evidence(case, "a", source_id="host1")
    for label, sid, hour, minute in [
        ("a2", "host1", 9, 0), ("b2", "host1", 9, 40),
        ("c2", "host2", 9, 10), ("d2", "host2", 9, 20),
    ]:
        ev = _put_evidence(case, label, source_id=sid)
        event = NormalizedEvent.create(
            event_type="line", attributes={}, derived_from=(ev.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=datetime(2026, 1, 1, hour, minute, tzinfo=UTC),
                precision=TimePrecision.EXACT, source_evidence_id=ev.id,
                asserted_by="t", created_at=NOW,
            )
        )
    case.record_manifest()
    result = find_gaps(case.store, min_gap_seconds=60)
    with case.transaction():
        track_findings(case.store, result, min_gap_seconds=60, min_corroborating_events=2)
    fid = case.store.list_tracked_findings()[0].id
    case.store.annotate_tracked_finding(
        fid, status=FindingStatus.DISMISSED, annotated_by="analyst:x", annotated_at=NOW, note=None,
    )
    case.record_manifest()
    doc = _render(case)
    assert doc["tracked_findings"][0]["status"] == "dismissed"
    case.close()


# -- contradictions (ephemeral, un-tracked) -----------------------------------------


def test_ephemeral_contradictions_shape_and_deterministic_ordering(tmp_path: Path) -> None:
    """Regression for adversarial-review gap: the plain, un-tracked
    contradictions[] section (mirroring _render_contradictions, distinct
    from tracked_contradictions[]) previously had zero coverage -- every
    prior test left it empty. This exercises real contradiction data
    WITHOUT calling track_contradictions at all."""
    case = Case.create(tmp_path / "case")
    ev_a = _put_evidence(case, "a")
    ev_b = _put_evidence(case, "b")
    event = NormalizedEvent.create(
        event_type="line", attributes={}, derived_from=(ev_a.id, ev_b.id), created_at=NOW
    )
    case.store.put_normalized_event(event)
    assertion_a = TimeAssertion.create(
        subject_event_id=event.id, value=NOW, precision=TimePrecision.EXACT,
        source_evidence_id=ev_a.id, asserted_by="source-a", created_at=NOW,
    )
    assertion_b = TimeAssertion.create(
        subject_event_id=event.id, value=NOW + timedelta(hours=3), precision=TimePrecision.EXACT,
        source_evidence_id=ev_b.id, asserted_by="source-b", created_at=NOW,
    )
    case.store.put_time_assertion(assertion_a)
    case.store.put_time_assertion(assertion_b)
    case.record_manifest()

    # Deliberately NOT tracked -- proves the ephemeral section independently
    # of correlate.contradiction_tracking / tracked_contradictions[].
    assert case.store.list_tracked_contradictions() == []

    doc = _render(case)
    assert len(doc["contradictions"]) == 1
    entry = doc["contradictions"][0]
    assert set(entry.keys()) == {"subject_event_id", "assertions"}
    assert entry["subject_event_id"] == event.id
    assert len(entry["assertions"]) == 2

    expected_order = sorted([assertion_a.id, assertion_b.id])
    assert [a["id"] for a in entry["assertions"]] == expected_order

    for assertion_entry in entry["assertions"]:
        assert set(assertion_entry.keys()) == {
            "id", "value", "precision", "source_evidence_id",
        }
    by_id = {a["id"]: a for a in entry["assertions"]}
    assert by_id[assertion_a.id]["source_evidence_id"] == ev_a.id
    assert by_id[assertion_a.id]["precision"] == "exact"
    assert by_id[assertion_b.id]["source_evidence_id"] == ev_b.id

    assert doc["tracked_contradictions"] == []  # unaffected, still empty
    case.close()


# -- coverage_gaps: null vs. run-empty --------------------------------------------


def test_coverage_gaps_is_null_when_not_run(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    doc = _render(case)
    assert doc["coverage_gaps"] is None
    case.close()


def test_coverage_gaps_is_populated_object_with_empty_findings_when_run_and_empty(
    tmp_path: Path,
) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    result = find_gaps(case.store, min_gap_seconds=60)
    doc = _render(case, gap_analysis=result)
    assert doc["coverage_gaps"] is not None
    assert doc["coverage_gaps"]["findings"] == []
    assert set(doc["coverage_gaps"].keys()) == {
        "refine_source_by_attribute", "findings", "excluded_no_time_assertion",
        "excluded_no_declared_source", "excluded_ambiguous_source",
        "excluded_unrefined_fallback_with_refined_sibling",
    }
    case.close()


def test_coverage_gaps_bounding_ids_are_order_significant_not_sorted(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    for label, sid, hour, minute in [
        ("a", "host1", 9, 0), ("b", "host1", 9, 40), ("c", "host2", 9, 10), ("d", "host2", 9, 20),
    ]:
        ev = _put_evidence(case, label, source_id=sid)
        event = NormalizedEvent.create(
            event_type="line", attributes={}, derived_from=(ev.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=datetime(2026, 1, 1, hour, minute, tzinfo=UTC),
                precision=TimePrecision.EXACT, source_evidence_id=ev.id,
                asserted_by="t", created_at=NOW,
            )
        )
    case.record_manifest()
    result = find_gaps(case.store, min_gap_seconds=60)
    doc = _render(case, gap_analysis=result)
    finding = doc["coverage_gaps"]["findings"][0]
    assert finding["bounding_absent_assertion_ids"] == list(
        result.findings[0].bounding_absent_assertion_ids
    )
    case.close()


# -- tracked_findings / tracked_contradictions: always arrays, never omitted -------


def test_tracked_findings_and_contradictions_are_empty_arrays_not_omitted(
    tmp_path: Path,
) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    doc = _render(case)
    assert doc["tracked_findings"] == []
    assert doc["tracked_contradictions"] == []
    case.close()


def test_tracked_finding_includes_live_still_reproduced(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    for label, sid, hour, minute in [
        ("a", "host1", 9, 0), ("b", "host1", 9, 40), ("c", "host2", 9, 10), ("d", "host2", 9, 20),
    ]:
        ev = _put_evidence(case, label, source_id=sid)
        event = NormalizedEvent.create(
            event_type="line", attributes={}, derived_from=(ev.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=datetime(2026, 1, 1, hour, minute, tzinfo=UTC),
                precision=TimePrecision.EXACT, source_evidence_id=ev.id,
                asserted_by="t", created_at=NOW,
            )
        )
    case.record_manifest()
    result = find_gaps(case.store, min_gap_seconds=60)
    with case.transaction():
        track_findings(case.store, result, min_gap_seconds=60, min_corroborating_events=2)
    case.record_manifest()
    doc = _render(case)
    assert len(doc["tracked_findings"]) == 1
    entry = doc["tracked_findings"][0]
    assert entry["still_reproduced"] is True
    assert "still_reproduced" in entry
    assert set(entry.keys()) == {
        "id", "absent_source", "present_source", "absent_source_refinement",
        "present_source_refinement", "interval_start", "interval_end",
        "corroborating_time_assertion_ids", "bounding_absent_assertion_ids",
        "min_gap_seconds", "min_corroborating_events", "refine_source_by_attribute",
        "status", "annotated_by", "annotated_at", "note", "still_reproduced",
    }
    case.close()


def test_tracked_contradiction_explicitly_omits_still_reproduced(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev_a = _put_evidence(case, "a")
    ev_b = _put_evidence(case, "b")
    event = NormalizedEvent.create(
        event_type="line", attributes={}, derived_from=(ev_a.id, ev_b.id), created_at=NOW
    )
    case.store.put_normalized_event(event)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event.id, value=NOW, precision=TimePrecision.EXACT,
            source_evidence_id=ev_a.id, asserted_by="source-a", created_at=NOW,
        )
    )
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event.id, value=NOW.replace(hour=3), precision=TimePrecision.EXACT,
            source_evidence_id=ev_b.id, asserted_by="source-b", created_at=NOW,
        )
    )
    case.record_manifest()
    found = detect_time_contradictions(case.store)
    with case.transaction():
        track_contradictions(case.store, found)
    case.record_manifest()
    doc = _render(case)
    assert len(doc["tracked_contradictions"]) == 1
    entry = doc["tracked_contradictions"][0]
    assert "still_reproduced" not in entry
    assert set(entry.keys()) == {
        "id", "subject_event_id", "assertion_ids", "status",
        "annotated_by", "annotated_at", "note",
    }
    assert entry["assertion_ids"] == sorted(entry["assertion_ids"])
    # A freshly tracked, never-annotated contradiction defaults to "open"
    # -- asserted explicitly, not merely implied by key presence.
    assert entry["status"] == "open"
    assert entry["annotated_by"] is None
    case.close()


# -- cross-kind isolation ----------------------------------------------------------


def test_tracked_findings_and_contradictions_do_not_cross_contaminate(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    for label, sid, hour, minute in [
        ("a", "host1", 9, 0), ("b", "host1", 9, 40), ("c", "host2", 9, 10), ("d", "host2", 9, 20),
    ]:
        ev = _put_evidence(case, label, source_id=sid)
        event = NormalizedEvent.create(
            event_type="line", attributes={}, derived_from=(ev.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=datetime(2026, 1, 1, hour, minute, tzinfo=UTC),
                precision=TimePrecision.EXACT, source_evidence_id=ev.id,
                asserted_by="t", created_at=NOW,
            )
        )
    ev_a = _put_evidence(case, "extra-a")
    ev_b = _put_evidence(case, "extra-b")
    event2 = NormalizedEvent.create(
        event_type="line", attributes={}, derived_from=(ev_a.id, ev_b.id), created_at=NOW
    )
    case.store.put_normalized_event(event2)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event2.id, value=NOW, precision=TimePrecision.EXACT,
            source_evidence_id=ev_a.id, asserted_by="source-a", created_at=NOW,
        )
    )
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=event2.id, value=NOW.replace(hour=3), precision=TimePrecision.EXACT,
            source_evidence_id=ev_b.id, asserted_by="source-b", created_at=NOW,
        )
    )
    case.record_manifest()

    result = find_gaps(case.store, min_gap_seconds=60)
    with case.transaction():
        track_findings(case.store, result, min_gap_seconds=60, min_corroborating_events=2)
    found = detect_time_contradictions(case.store)
    with case.transaction():
        track_contradictions(case.store, found)
    case.record_manifest()

    doc = _render(case)
    assert len(doc["tracked_findings"]) == 1
    assert len(doc["tracked_contradictions"]) == 1
    assert "assertion_ids" not in doc["tracked_findings"][0]
    assert "absent_source" not in doc["tracked_contradictions"][0]
    case.close()


# -- determinism / ordering ---------------------------------------------------------


def test_repeated_rendering_is_byte_identical(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    _put_evidence(case, "a")
    case.record_manifest()
    manifest = case.compute_manifest()
    b1 = render_report_json_bytes(
        case_name="x", store=case.store, recomputed_manifest=manifest,
        recorded_manifest=case.load_recorded_manifest(),
    )
    b2 = render_report_json_bytes(
        case_name="x", store=case.store, recomputed_manifest=manifest,
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert b1 == b2
    case.close()


def test_insertion_order_independence(tmp_path: Path) -> None:
    case_a = Case.create(tmp_path / "a")
    ev1 = _put_evidence(case_a, "z")
    ev2 = _put_evidence(case_a, "a")
    case_a.record_manifest()

    case_b = Case.create(tmp_path / "b")
    case_b.store.put_evidence(ev2)
    case_b.store.put_evidence(ev1)
    case_b.record_manifest()

    doc_a = _render(case_a)
    doc_b = _render(case_b)
    assert [e["id"] for e in doc_a["evidence"]] == [e["id"] for e in doc_b["evidence"]]
    case_a.close()
    case_b.close()


def test_timeline_insertion_order_independence(tmp_path: Path) -> None:
    """Extends order-independence coverage beyond evidence[] to
    timeline[] -- minimal fixture: two events, inserted in reverse order
    across two cases."""

    def _event_and_assertion(case: Case, label: str, hour: int) -> None:
        ev = _put_evidence(case, label)
        event = NormalizedEvent.create(
            event_type="line", attributes={}, derived_from=(ev.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=datetime(2026, 1, 1, hour, tzinfo=UTC),
                precision=TimePrecision.EXACT, source_evidence_id=ev.id,
                asserted_by="t", created_at=NOW,
            )
        )

    case_a = Case.create(tmp_path / "a")
    _event_and_assertion(case_a, "late", 10)
    _event_and_assertion(case_a, "early", 9)
    case_a.record_manifest()

    case_b = Case.create(tmp_path / "b")
    _event_and_assertion(case_b, "early", 9)
    _event_and_assertion(case_b, "late", 10)
    case_b.record_manifest()

    doc_a = _render(case_a)
    doc_b = _render(case_b)
    assert [e["id"] for e in doc_a["timeline"]] == [e["id"] for e in doc_b["timeline"]]
    case_a.close()
    case_b.close()


def test_tracked_findings_and_contradictions_insertion_order_independence(
    tmp_path: Path,
) -> None:
    """Extends order-independence coverage to tracked_findings[]/
    tracked_contradictions[] -- minimal fixture: two already-built
    TrackedGapFinding/TrackedTimeContradiction rows, created in reverse
    order across two cases (avoids re-running full gap/contradiction
    detection twice just to prove a store-level/JSON-level sort
    property)."""
    from witnessgraph.core.tracked_finding import TrackedGapFinding
    from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction

    def _finding(absent_source: str) -> TrackedGapFinding:
        return TrackedGapFinding(
            id=TrackedGapFinding.identity_hash(
                absent_source=absent_source, present_source="p",
                absent_source_refinement=None, present_source_refinement=None,
                interval_start=NOW, interval_end=NOW + timedelta(hours=1),
                corroborating_time_assertion_ids=("a1", "a2"),
                bounding_absent_assertion_ids=("b1", "b2"),
            ),
            absent_source=absent_source, present_source="p",
            absent_source_refinement=None, present_source_refinement=None,
            interval_start=NOW, interval_end=NOW + timedelta(hours=1),
            corroborating_time_assertion_ids=("a1", "a2"),
            bounding_absent_assertion_ids=("b1", "b2"),
            min_gap_seconds=60.0, min_corroborating_events=2,
            refine_source_by_attribute=None,
        )

    def _contradiction(subject_event_id: str) -> TrackedTimeContradiction:
        return TrackedTimeContradiction(
            id=TrackedTimeContradiction.identity_hash(
                subject_event_id=subject_event_id, assertion_ids=("x1", "x2")
            ),
            subject_event_id=subject_event_id, assertion_ids=("x1", "x2"),
        )

    f1, f2 = _finding("host-z"), _finding("host-a")
    c1, c2 = _contradiction("evt-z"), _contradiction("evt-a")

    case_a = Case.create(tmp_path / "a")
    case_a.store.create_tracked_finding(f1)
    case_a.store.create_tracked_finding(f2)
    case_a.store.create_tracked_contradiction(c1)
    case_a.store.create_tracked_contradiction(c2)
    case_a.record_manifest()

    case_b = Case.create(tmp_path / "b")
    case_b.store.create_tracked_finding(f2)
    case_b.store.create_tracked_finding(f1)
    case_b.store.create_tracked_contradiction(c2)
    case_b.store.create_tracked_contradiction(c1)
    case_b.record_manifest()

    doc_a = _render(case_a)
    doc_b = _render(case_b)
    assert [t["id"] for t in doc_a["tracked_findings"]] == [
        t["id"] for t in doc_b["tracked_findings"]
    ]
    assert [t["id"] for t in doc_a["tracked_contradictions"]] == [
        t["id"] for t in doc_b["tracked_contradictions"]
    ]
    case_a.close()
    case_b.close()


# -- canonical encoding --------------------------------------------------------------


def test_canonical_encoding_is_compact_sorted_keys_no_trailing_newline(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.record_manifest()
    manifest = case.compute_manifest()
    raw = render_report_json_bytes(
        case_name="x", store=case.store, recomputed_manifest=manifest,
        recorded_manifest=case.load_recorded_manifest(),
    )
    text = raw.decode("ascii")
    assert not text.endswith("\n")
    assert "\n" not in text  # fully compact, single line
    assert ": " not in text and ", " not in text  # compact separators, no extra whitespace
    # Top-level keys byte-order is alphabetical (canonical_json_bytes sort_keys=True).
    top_level_order = ["case_name", "contradictions", "coverage_gaps", "entities",
                        "evidence", "hypotheses", "manifest", "relationships",
                        "schema_version", "timeline", "tracked_contradictions",
                        "tracked_findings"]
    positions = [text.index(f'"{k}"') for k in top_level_order]
    assert positions == sorted(positions)
    case.close()


# -- Unicode / control-character round-trip fidelity (NOT neutralized) -------------


def test_zero_width_character_round_trips_exactly_unneutralized(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = EvidenceItem.create(
        raw_bytes=b"data", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="path​with-zw.log:1", collected_at=NOW,
    )
    case.store.put_evidence(ev)
    case.record_manifest()
    doc = _render(case)
    locator = doc["evidence"][0]["source_locator"]
    # Exact round-trip: the real U+200B character, not a lossy Markdown-
    # style literal-text placeholder substitution (which report.render's
    # _neutralize() would have produced instead).
    assert locator == "path​with-zw.log:1"
    assert len(locator) == len("path​with-zw.log:1")
    assert "​" in locator
    # No Markdown code-span fencing was applied to this JSON string value.
    assert "`" not in locator
    case.close()


def test_bidi_override_character_round_trips_exactly_unneutralized(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    hyp = Hypothesis(
        statement="the attacker used a RLO‮ character",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=ev.id),),
        inferred_by="analyst:test", created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    case.record_manifest()
    doc = _render(case)
    assert doc["hypotheses"][0]["statement"] == "the attacker used a RLO‮ character"
    case.close()


def test_control_character_is_valid_json_and_round_trips(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = EvidenceItem.create(
        raw_bytes=b"data", source_adapter="jsonl", adapter_version="0.1.0",
        source_locator="path/with\rcarriage.log:1", collected_at=NOW,
    )
    case.store.put_evidence(ev)
    case.record_manifest()
    raw = render_report_json_bytes(
        case_name="x", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    # A raw, unescaped CR byte must never appear in valid JSON output.
    assert b"\r" not in raw
    doc = json.loads(raw)
    assert doc["evidence"][0]["source_locator"] == "path/with\rcarriage.log:1"
    case.close()


def test_quotes_backslashes_and_newlines_round_trip_correctly(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    tricky = 'quote"backslash\\newline\nend'
    hyp = Hypothesis(
        statement=tricky, supporting_evidence=(EvidenceRef(kind="evidence_item", id=ev.id),),
        inferred_by="analyst:test", created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    case.record_manifest()
    doc = _render(case)
    assert doc["hypotheses"][0]["statement"] == tricky
    case.close()


def test_sql_shell_like_string_is_treated_as_opaque_text(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    ev = _put_evidence(case, "a")
    malicious = "x'; DROP TABLE evidence_items; --"
    hyp = Hypothesis(
        statement=malicious, supporting_evidence=(EvidenceRef(kind="evidence_item", id=ev.id),),
        inferred_by="analyst:test", created_at=NOW,
    )
    case.store.put_hypothesis(hyp)
    case.record_manifest()
    doc = _render(case)
    assert doc["hypotheses"][0]["statement"] == malicious
    assert len(case.store.list_evidence()) == 1  # store intact
    case.close()
