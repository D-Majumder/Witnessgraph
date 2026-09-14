"""v0.8: CLI, report, manifest/verify independence, export/import, crash
recovery, legacy-v0.7-compatibility, and cross-table-isolation coverage
for persisted time-contradiction tracking (`witnessgraph contradictions
--track`, `witnessgraph contradiction-findings {list,show,ack}`).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.core.tracked_finding import FindingStatus
from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction
from witnessgraph.correlate.contradiction_tracking import track_contradictions
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import replay_and_verify
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case
from witnessgraph.store.sqlite_store import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


def _put_evidence(case: Case, label: str) -> EvidenceItem:
    evidence = EvidenceItem.create(
        raw_bytes=label.encode(), source_adapter="jsonl", adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1", collected_at=NOW,
    )
    case.store.put_evidence(evidence)
    return evidence


def _build_contradiction_case(root: Path) -> Case:
    """One event with two disagreeing TimeAssertions from two sources."""
    case = Case.create(root)
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
            subject_event_id=event.id, value=NOW + timedelta(hours=3),
            precision=TimePrecision.EXACT,
            source_evidence_id=ev_b.id, asserted_by="source-b", created_at=NOW,
        )
    )
    case.record_manifest()
    return case


def _build_gap_case(root: Path) -> Case:
    """A v0.7-style gap case, for cross-table isolation tests."""
    case = Case.create(root)
    for label, source_id, hour, minute in [
        ("a", "host1", 9, 0), ("b", "host1", 9, 40), ("c", "host2", 9, 10), ("d", "host2", 9, 20),
    ]:
        evidence = EvidenceItem.create(
            raw_bytes=label.encode(), source_adapter="jsonl", adapter_version="0.1.0",
            source_locator=f"{label}.jsonl:1", collected_at=NOW, source_id=source_id,
        )
        case.store.put_evidence(evidence)
        event = NormalizedEvent.create(
            event_type="line", attributes={}, derived_from=(evidence.id,), created_at=NOW
        )
        case.store.put_normalized_event(event)
        case.store.put_time_assertion(
            TimeAssertion.create(
                subject_event_id=event.id, value=datetime(2026, 1, 1, hour, minute, tzinfo=UTC),
                precision=TimePrecision.EXACT, source_evidence_id=evidence.id,
                asserted_by="test", created_at=NOW,
            )
        )
    case.record_manifest()
    return case


# -- CLI: contradictions --track -------------------------------------------------


def test_contradictions_without_track_flag_persists_nothing(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()

    result = runner.invoke(app, ["contradictions", str(case_dir)])
    assert result.exit_code == 0
    assert b"tracked:" not in result.stdout_bytes

    case = Case.open(case_dir)
    assert case.store.list_tracked_contradictions() == []
    case.close()


def test_contradictions_track_creates_tracked_contradiction(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()

    result = runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    assert result.exit_code == 0
    assert b"tracked: 1 new contradiction(s), 0 already tracked" in result.stdout_bytes

    case = Case.open(case_dir)
    tracked = case.store.list_tracked_contradictions()
    assert len(tracked) == 1
    assert tracked[0].status == FindingStatus.OPEN
    assert tracked[0].annotated_by is None
    case.close()


def test_contradictions_track_is_idempotent_on_rerun(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()

    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    result = runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    assert result.exit_code == 0
    assert b"tracked: 0 new contradiction(s), 1 already tracked" in result.stdout_bytes

    case = Case.open(case_dir)
    assert len(case.store.list_tracked_contradictions()) == 1
    case.close()


def test_ack_then_retrack_preserves_annotation(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()

    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()

    ack_result = runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), contradiction_id,
         "--status", "dismissed", "--by", "analyst:jane", "--note", "likely clock skew"],
    )
    assert ack_result.exit_code == 0

    retrack_result = runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    assert retrack_result.exit_code == 0
    assert b"tracked: 0 new contradiction(s), 1 already tracked" in retrack_result.stdout_bytes

    case = Case.open(case_dir)
    stored = case.store.get_tracked_contradiction(contradiction_id)
    assert stored is not None
    assert stored.status == FindingStatus.DISMISSED
    assert stored.annotated_by == "analyst:jane"
    assert stored.note == "likely clock skew"
    case.close()


# -- CLI: contradiction-findings ack ---------------------------------------------


def test_contradiction_findings_ack_requires_by_with_no_default(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()

    result = runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), contradiction_id, "--status", "reviewed"],
    )
    assert result.exit_code != 0


def test_contradiction_findings_ack_rejects_whitespace_only_by(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()

    result = runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), contradiction_id,
         "--status", "reviewed", "--by", "   "],
    )
    assert result.exit_code != 0
    assert b"--by" in result.stderr_bytes
    assert b"blank" in result.stderr_bytes.lower()

    case = Case.open(case_dir)
    stored = case.store.get_tracked_contradiction(contradiction_id)
    assert stored is not None
    assert stored.status == FindingStatus.OPEN
    case.close()


def test_contradiction_findings_ack_unknown_id_fails_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), "nonexistent-id",
         "--status", "reviewed", "--by", "analyst:jane"],
    )
    assert result.exit_code != 0
    assert b"no such tracked contradiction" in result.stderr_bytes


def test_contradiction_findings_ack_rejects_invalid_status(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()

    result = runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), contradiction_id,
         "--status", "not-a-real-status", "--by", "analyst:jane"],
    )
    assert result.exit_code != 0


# -- CLI: contradiction-findings list / show -------------------------------------


def test_contradiction_findings_list_empty_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(app, ["contradiction-findings", "list", str(case_dir)])
    assert result.exit_code == 0
    assert b"no tracked contradictions" in result.stdout_bytes


def test_contradiction_findings_show_unknown_id_fails_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(app, ["contradiction-findings", "show", str(case_dir), "nonexistent"])
    assert result.exit_code != 0
    assert b"no such tracked contradiction" in result.stderr_bytes


# -- CLI isolation: no cross-table id fallback -----------------------------------


def test_findings_show_does_not_find_a_contradiction_id(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()

    result = runner.invoke(app, ["findings", "show", str(case_dir), contradiction_id])
    assert result.exit_code != 0
    assert b"no such tracked finding" in result.stderr_bytes


def test_contradiction_findings_show_does_not_find_a_gap_finding_id(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    result = runner.invoke(app, ["contradiction-findings", "show", str(case_dir), finding_id])
    assert result.exit_code != 0
    assert b"no such tracked contradiction" in result.stderr_bytes


def test_gap_and_contradiction_tracking_in_same_case_are_independent(tmp_path: Path) -> None:
    """Tracking both kinds in the same case must leave each table exactly
    reflecting its own kind, never cross-populated."""
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    ev_a = _put_evidence(case, "extra-a")
    ev_b = _put_evidence(case, "extra-b")
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
            subject_event_id=event.id, value=NOW + timedelta(hours=3),
            precision=TimePrecision.EXACT,
            source_evidence_id=ev_b.id, asserted_by="source-b", created_at=NOW,
        )
    )
    case.record_manifest()
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])

    case = Case.open(case_dir)
    assert len(case.store.list_tracked_findings()) == 1
    assert len(case.store.list_tracked_contradictions()) == 1
    case.close()


# -- Report -----------------------------------------------------------------------


def test_report_omits_tracked_contradictions_section_when_empty(tmp_path: Path) -> None:
    case = _build_contradiction_case(tmp_path / "case")
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Tracked Contradictions" not in report
    case.close()


def test_report_includes_tracked_contradictions_and_disclosure(tmp_path: Path) -> None:
    case = _build_contradiction_case(tmp_path / "case")
    found = detect_time_contradictions(case.store)
    with case.transaction():
        track_contradictions(case.store, found)
    case.record_manifest()

    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Tracked Contradictions" in report
    assert "not yet reviewed" in report
    assert (
        "Review status is workflow metadata only; reviewed or dismissed does "
        "not mean the contradiction is resolved, adjudicated, or that either "
        "assertion is more correct. Witnessgraph does not determine which "
        "disagreeing assertion is true."
    ) in report
    assert "## Tracked Findings" not in report  # no gap findings tracked here
    case.close()


def test_report_does_not_expose_a_still_reproduced_indicator_for_contradictions(
    tmp_path: Path,
) -> None:
    case = _build_contradiction_case(tmp_path / "case")
    found = detect_time_contradictions(case.store)
    with case.transaction():
        track_contradictions(case.store, found)
    case.record_manifest()

    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    section = report.split("## Tracked Contradictions")[1].split("## Integrity Summary")[0]
    assert "still reproduced" not in section
    case.close()


def test_report_untrusted_rendering_of_note_and_annotated_by(tmp_path: Path) -> None:
    case = _build_contradiction_case(tmp_path / "case")
    found = detect_time_contradictions(case.store)
    with case.transaction():
        track_contradictions(case.store, found)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.store.annotate_tracked_contradiction(
        contradiction_id, status=FindingStatus.REVIEWED,
        annotated_by="analyst​-x", annotated_at=NOW, note="note​with-zw",
    )
    case.record_manifest()

    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "​" not in report
    assert "\\u200B" in report
    case.close()


def test_note_with_sql_shell_like_text_is_treated_as_opaque(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()

    malicious = "x'; DROP TABLE evidence_items; --"
    result = runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), contradiction_id,
         "--status", "reviewed", "--by", "analyst:x", "--note", malicious],
    )
    assert result.exit_code == 0

    case = Case.open(case_dir)
    stored = case.store.get_tracked_contradiction(contradiction_id)
    assert stored is not None
    assert stored.note == malicious
    assert len(case.store.list_evidence()) == 2  # store is intact
    case.close()


# -- Manifest / verify independence ---------------------------------------------


def test_manifest_unchanged_after_tracking(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    before = case.compute_manifest().manifest_hash
    case.close()

    runner.invoke(app, ["contradictions", str(case_dir), "--track"])

    case = Case.open(case_dir)
    after = case.compute_manifest().manifest_hash
    assert before == after
    case.close()


def test_manifest_unchanged_after_all_three_annotation_statuses(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    before = case.compute_manifest().manifest_hash
    case.close()

    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()

    for status in ("open", "reviewed", "dismissed"):
        runner.invoke(
            app,
            ["contradiction-findings", "ack", str(case_dir), contradiction_id,
             "--status", status, "--by", "analyst:x"],
        )
        case = Case.open(case_dir)
        assert case.compute_manifest().manifest_hash == before
        case.close()


def test_verify_verdict_unchanged_after_tracking_and_annotation(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()

    case = Case.open(case_dir)
    before = replay_and_verify(case)
    case.close()
    assert before.matches_recorded

    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()
    runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), contradiction_id,
         "--status", "dismissed", "--by", "analyst:x"],
    )

    case = Case.open(case_dir)
    after = replay_and_verify(case)
    case.close()
    assert after.matches_recorded
    assert after.recomputed_manifest.manifest_hash == before.recomputed_manifest.manifest_hash


# -- Crash / transaction rollback ------------------------------------------------


def test_track_contradictions_rolls_back_all_new_rows_on_failure(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    # Two independent events, each with a disagreeing pair.
    for evt_label in ("evt-1", "evt-2"):
        ev_a = _put_evidence(case, f"{evt_label}-a")
        ev_b = _put_evidence(case, f"{evt_label}-b")
        event = NormalizedEvent(
            id=evt_label, event_type="line", derived_from=(ev_a.id, ev_b.id), created_at=NOW
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
                subject_event_id=event.id, value=NOW + timedelta(hours=3),
                precision=TimePrecision.EXACT, source_evidence_id=ev_b.id,
                asserted_by="source-b", created_at=NOW,
            )
        )
    case.record_manifest()

    found = detect_time_contradictions(case.store)
    assert len(found) == 2

    before_evidence = len(case.store.list_evidence())
    before_hash = case.compute_manifest().manifest_hash

    call_count = {"n": 0}
    real_create = case.store.create_tracked_contradiction

    def _flaky_create(contradiction: TrackedTimeContradiction) -> TrackedTimeContradiction:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated crash mid-track")
        return real_create(contradiction)

    case.store.create_tracked_contradiction = _flaky_create  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        with case.transaction():
            track_contradictions(case.store, found)

    case.store.create_tracked_contradiction = real_create  # type: ignore[method-assign]
    assert case.store.list_tracked_contradictions() == []  # fully rolled back
    assert len(case.store.list_evidence()) == before_evidence
    assert case.compute_manifest().manifest_hash == before_hash

    # Clean retry converges.
    with case.transaction():
        outcomes = track_contradictions(case.store, found)
    assert sum(1 for o in outcomes if o.newly_created) == 2
    assert len(case.store.list_tracked_contradictions()) == 2
    case.close()


# -- Export / import -------------------------------------------------------------


def test_export_import_preserves_tracked_contradictions_and_annotation(tmp_path: Path) -> None:
    case = _build_contradiction_case(tmp_path / "original")
    found = detect_time_contradictions(case.store)
    with case.transaction():
        track_contradictions(case.store, found)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.store.annotate_tracked_contradiction(
        contradiction_id, status=FindingStatus.DISMISSED, annotated_by="analyst:x",
        annotated_at=NOW, note="benign",
    )
    case.record_manifest()
    original = case.store.list_tracked_contradictions()

    archive = export_case(case, tmp_path / "case.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_contradictions = restored.store.list_tracked_contradictions()
    assert restored_contradictions == original
    restored.close()


# -- Legacy compatibility: pre-v0.7 and genuine-v0.7 cases -----------------------


def _create_legacy_pre_v07_case_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS evidence_items (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS normalized_events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS time_assertions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hypotheses (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        """
    )
    conn.commit()
    conn.close()


def test_legacy_pre_v07_case_opens_cleanly_under_v08(tmp_path: Path) -> None:
    case_dir = tmp_path / "legacy_case"
    case_dir.mkdir()
    _create_legacy_pre_v07_case_db(case_dir / "case.db")

    store = SqliteStore(case_dir / "case.db")
    assert store.list_tracked_contradictions() == []
    assert store.list_tracked_findings() == []
    assert store.list_evidence() == []
    store.close()

    case = Case.open(case_dir)
    report = render_report(
        case_name="legacy", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Tracked Contradictions" not in report
    assert "## Tracked Findings" not in report
    case.close()


def _create_genuine_v07_case_db(db_path: Path, tracked_finding: dict[str, object]) -> None:
    """Build a case.db with exactly v0.7's six tables (including a
    populated tracked_gap_findings row) but WITHOUT tracked_time_contradictions
    -- simulating a real case created and tracked under v0.7, before v0.8
    ever existed."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS evidence_items (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS normalized_events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS time_assertions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS hypotheses (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tracked_gap_findings (id TEXT PRIMARY KEY, data TEXT NOT NULL);
        """
    )
    conn.execute(
        "INSERT INTO tracked_gap_findings (id, data) VALUES (?, ?)",
        (tracked_finding["id"], json.dumps(tracked_finding)),
    )
    conn.commit()
    conn.close()


def test_genuine_v07_case_tracked_gap_rows_untouched_under_v08(tmp_path: Path) -> None:
    """The central legacy-compatibility requirement: opening a REAL,
    already-populated v0.7 case (not just a pre-v0.7 empty one) under
    v0.8 code must leave its tracked_gap_findings row byte-for-byte
    untouched, while silently gaining an empty tracked_time_contradictions
    table."""
    case_dir = tmp_path / "genuine_v07_case"
    case_dir.mkdir()

    finding_id = str(uuid.uuid4())
    tracked_finding_row: dict[str, object] = {
        "id": finding_id,
        "absent_source": "host1",
        "present_source": "host2",
        "absent_source_refinement": None,
        "present_source_refinement": None,
        "interval_start": "2026-01-01T09:00:00Z",
        "interval_end": "2026-01-01T09:40:00Z",
        "corroborating_time_assertion_ids": ["a1", "a2"],
        "bounding_absent_assertion_ids": ["b1", "b2"],
        "min_gap_seconds": 60.0,
        "min_corroborating_events": 2,
        "refine_source_by_attribute": None,
        "status": "dismissed",
        "annotated_by": "analyst:pre-v08",
        "annotated_at": "2026-01-01T00:00:00Z",
        "note": "tracked under v0.7, before v0.8 ever existed",
    }
    _create_genuine_v07_case_db(case_dir / "case.db", tracked_finding_row)

    # Confirm, before opening with v0.8 code, that the contradictions
    # table genuinely does not exist yet.
    raw_conn = sqlite3.connect(str(case_dir / "case.db"))
    tables_before = {
        row[0] for row in raw_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    raw_conn.close()
    assert "tracked_time_contradictions" not in tables_before
    assert "tracked_gap_findings" in tables_before

    case = Case.open(case_dir)
    tracked_findings = case.store.list_tracked_findings()
    assert len(tracked_findings) == 1
    stored = tracked_findings[0]
    assert stored.id == finding_id
    assert stored.status == FindingStatus.DISMISSED
    assert stored.annotated_by == "analyst:pre-v08"
    assert stored.note == "tracked under v0.7, before v0.8 ever existed"

    assert case.store.list_tracked_contradictions() == []

    report = render_report(
        case_name="genuine-v07", store=case.store,
        recomputed_manifest=case.compute_manifest(), recorded_manifest=None,
    )
    assert "## Tracked Findings" in report  # the v0.7 row still renders
    assert "## Tracked Contradictions" not in report  # nothing tracked here
    case.close()

    raw_conn = sqlite3.connect(str(case_dir / "case.db"))
    tables_after = {
        row[0] for row in raw_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    row_after = raw_conn.execute(
        "SELECT data FROM tracked_gap_findings WHERE id = ?", (finding_id,)
    ).fetchone()
    raw_conn.close()
    assert "tracked_time_contradictions" in tables_after  # auto-created
    assert json.loads(row_after[0]) == tracked_finding_row  # byte-for-byte untouched


# -- `--format json` for `contradictions`/`contradiction-findings list` -------


def test_contradictions_format_json_shape_and_determinism(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()

    args = ["contradictions", str(case_dir), "--format", "json"]
    first = runner.invoke(app, args)
    second = runner.invoke(app, args)
    assert first.exit_code == 0
    doc = json.loads(first.stdout)
    assert len(doc["contradictions"]) == 1
    contradiction = doc["contradictions"][0]
    assert len(contradiction["assertions"]) == 2
    assert contradiction["assertions"][0]["id"] < contradiction["assertions"][1]["id"]
    assert doc["tracked"] is None  # --track not passed
    assert first.stdout == second.stdout


def test_contradictions_format_json_empty_case_is_empty_array(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    Case.create(case_dir).close()
    result = runner.invoke(app, ["contradictions", str(case_dir), "--format", "json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"contradictions": [], "tracked": None}


def test_contradictions_format_json_with_track_reports_tracked_summary(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()

    result = runner.invoke(
        app, ["contradictions", str(case_dir), "--track", "--format", "json"]
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert doc["tracked"] == {"new": 1, "already_tracked": 0}

    case = Case.open(case_dir)
    assert len(case.store.list_tracked_contradictions()) == 1  # tracking still happened
    case.close()


def test_contradictions_format_json_does_not_change_default_text(tmp_path: Path) -> None:
    """--format json is opt-in; omitting it reproduces the exact pre-existing text."""
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    result = runner.invoke(app, ["contradictions", str(case_dir)])
    assert result.exit_code == 0
    assert "{" not in result.stdout  # plain text, not JSON


def test_contradictions_rejects_bad_format(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    result = runner.invoke(app, ["contradictions", str(case_dir), "--format", "xml"])
    assert result.exit_code != 0


def test_contradiction_findings_list_format_json_shape(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])

    result = runner.invoke(
        app, ["contradiction-findings", "list", str(case_dir), "--format", "json"]
    )
    assert result.exit_code == 0
    doc = json.loads(result.stdout)
    assert len(doc["contradictions"]) == 1
    row = doc["contradictions"][0]
    assert row["status"] == "open"
    assert row["annotated_by"] is None
    assert "still_reproduced" not in row  # deliberately absent -- see the module docstring


def test_contradiction_findings_list_format_json_empty_is_empty_array(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    Case.create(case_dir).close()
    result = runner.invoke(
        app, ["contradiction-findings", "list", str(case_dir), "--format", "json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"contradictions": []}


def test_contradiction_findings_list_format_json_reflects_annotation(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_contradiction_case(case_dir)
    case.close()
    runner.invoke(app, ["contradictions", str(case_dir), "--track"])
    case = Case.open(case_dir)
    contradiction_id = case.store.list_tracked_contradictions()[0].id
    case.close()
    runner.invoke(
        app,
        ["contradiction-findings", "ack", str(case_dir), contradiction_id,
         "--status", "dismissed", "--by", "analyst:jane", "--note", "clock skew"],
    )

    result = runner.invoke(
        app, ["contradiction-findings", "list", str(case_dir), "--format", "json"]
    )
    row = json.loads(result.stdout)["contradictions"][0]
    assert row["status"] == "dismissed"
    assert row["annotated_by"] == "analyst:jane"
    assert row["note"] == "clock skew"
