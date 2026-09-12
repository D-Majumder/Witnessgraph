"""v0.7: CLI, report, manifest/verify independence, export/import, crash
recovery, and adversarial coverage for persisted gap-finding tracking
(`witnessgraph gaps --track`, `witnessgraph findings {list,show,ack}`).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.core.tracked_finding import FindingStatus, TrackedGapFinding
from witnessgraph.correlate.gaps import find_gaps
from witnessgraph.correlate.tracking import is_still_reproduced, track_findings
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import replay_and_verify
from witnessgraph.report.render import render_report
from witnessgraph.store.case import Case
from witnessgraph.store.sqlite_store import SqliteStore

NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


def _put(
    case: Case, *, source_id: str | None, value: datetime, label: str
) -> TimeAssertion:
    evidence = EvidenceItem.create(
        raw_bytes=label.encode(), source_adapter="jsonl", adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1", collected_at=NOW, source_id=source_id,
    )
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line", attributes={}, derived_from=(evidence.id,), created_at=NOW
    )
    case.store.put_normalized_event(event)
    assertion = TimeAssertion.create(
        subject_event_id=event.id, value=value, precision=TimePrecision.EXACT,
        source_evidence_id=evidence.id, asserted_by="test", created_at=NOW,
    )
    case.store.put_time_assertion(assertion)
    return assertion


def _t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def _build_gap_case(root: Path) -> Case:
    """host1 has a wide bracket with a gap; host2 corroborates within it."""
    case = Case.create(root)
    _put(case, source_id="host1", value=_t(9, 0), label="a")
    _put(case, source_id="host1", value=_t(9, 40), label="b")
    _put(case, source_id="host2", value=_t(9, 10), label="c")
    _put(case, source_id="host2", value=_t(9, 20), label="d")
    case.record_manifest()
    return case


def _build_two_gap_case(root: Path) -> Case:
    """Two independent coarse-source pairs, each producing its own finding."""
    case = Case.create(root)
    _put(case, source_id="host1", value=_t(9, 0), label="a")
    _put(case, source_id="host1", value=_t(9, 40), label="b")
    _put(case, source_id="host2", value=_t(9, 10), label="c")
    _put(case, source_id="host2", value=_t(9, 20), label="d")
    _put(case, source_id="host3", value=_t(10, 0), label="e")
    _put(case, source_id="host3", value=_t(10, 40), label="f")
    _put(case, source_id="host4", value=_t(10, 10), label="g")
    _put(case, source_id="host4", value=_t(10, 20), label="h")
    case.record_manifest()
    return case


# -- CLI: gaps --track ----------------------------------------------------------


def test_gaps_without_track_flag_persists_nothing(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()

    result = runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60"])
    assert result.exit_code == 0
    assert b"tracked:" not in result.stdout_bytes

    case = Case.open(case_dir)
    assert case.store.list_tracked_findings() == []
    case.close()


def test_gaps_track_creates_tracked_findings(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()

    result = runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    assert result.exit_code == 0
    assert b"tracked: 1 new finding(s), 0 already tracked" in result.stdout_bytes

    case = Case.open(case_dir)
    tracked = case.store.list_tracked_findings()
    assert len(tracked) == 1
    assert tracked[0].status == FindingStatus.OPEN
    assert tracked[0].annotated_by is None
    case.close()


def test_gaps_track_is_idempotent_on_rerun(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    result = runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    assert result.exit_code == 0
    assert b"tracked: 0 new finding(s), 1 already tracked" in result.stdout_bytes

    case = Case.open(case_dir)
    assert len(case.store.list_tracked_findings()) == 1
    case.close()


def test_ack_then_retrack_preserves_annotation(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    ack_result = runner.invoke(
        app,
        ["findings", "ack", str(case_dir), finding_id,
         "--status", "dismissed", "--by", "analyst:jane", "--note", "benign quiet period"],
    )
    assert ack_result.exit_code == 0

    retrack_result = runner.invoke(
        app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"]
    )
    assert retrack_result.exit_code == 0
    assert b"tracked: 0 new finding(s), 1 already tracked" in retrack_result.stdout_bytes

    case = Case.open(case_dir)
    stored = case.store.get_tracked_finding(finding_id)
    assert stored is not None
    assert stored.status == FindingStatus.DISMISSED
    assert stored.annotated_by == "analyst:jane"
    assert stored.note == "benign quiet period"
    case.close()


# -- CLI: findings ack ----------------------------------------------------------


def test_findings_ack_requires_by_with_no_default(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    result = runner.invoke(
        app, ["findings", "ack", str(case_dir), finding_id, "--status", "reviewed"]
    )
    assert result.exit_code != 0
    assert b"analyst" not in result.stdout_bytes.lower() or b"--by" in result.stdout_bytes


def test_findings_ack_rejects_whitespace_only_by_and_does_not_persist(tmp_path: Path) -> None:
    """CLI-level regression for the adversarial-review blocker: a
    whitespace-only --by must be rejected before it ever reaches the
    store, and the tracked finding's annotation must remain untouched."""
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    result = runner.invoke(
        app,
        ["findings", "ack", str(case_dir), finding_id,
         "--status", "reviewed", "--by", "   "],
    )
    assert result.exit_code != 0
    assert b"--by" in result.stderr_bytes
    assert b"blank" in result.stderr_bytes.lower()

    case = Case.open(case_dir)
    stored = case.store.get_tracked_finding(finding_id)
    assert stored is not None
    assert stored.status == FindingStatus.OPEN
    assert stored.annotated_by is None
    case.close()


def test_findings_ack_rejects_empty_string_by(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    result = runner.invoke(
        app,
        ["findings", "ack", str(case_dir), finding_id,
         "--status", "reviewed", "--by", ""],
    )
    assert result.exit_code != 0


def test_findings_ack_unknown_id_fails_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app,
        ["findings", "ack", str(case_dir), "nonexistent-id",
         "--status", "reviewed", "--by", "analyst:jane"],
    )
    assert result.exit_code != 0
    assert b"no such tracked finding" in result.stderr_bytes


def test_findings_ack_rejects_invalid_status(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    result = runner.invoke(
        app,
        ["findings", "ack", str(case_dir), finding_id,
         "--status", "not-a-real-status", "--by", "analyst:jane"],
    )
    assert result.exit_code != 0


# -- CLI: findings list / show --------------------------------------------------


def test_findings_list_empty_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(app, ["findings", "list", str(case_dir)])
    assert result.exit_code == 0
    assert b"no tracked findings" in result.stdout_bytes


def test_findings_show_unknown_id_fails_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)
    case.record_manifest()
    case.close()

    result = runner.invoke(app, ["findings", "show", str(case_dir), "nonexistent"])
    assert result.exit_code != 0
    assert b"no such tracked finding" in result.stderr_bytes


def test_findings_list_shows_still_reproduced_state(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])

    result = runner.invoke(app, ["findings", "list", str(case_dir)])
    assert result.exit_code == 0
    assert b"still reproduced by current evidence: yes" in result.stdout_bytes


# -- Report ---------------------------------------------------------------------


def test_report_omits_tracked_findings_section_when_empty(tmp_path: Path) -> None:
    case = _build_gap_case(tmp_path / "case")
    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Tracked Findings" not in report
    case.close()


def test_report_includes_tracked_findings_and_disclosure(tmp_path: Path) -> None:
    case = _build_gap_case(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60)
    with case.transaction():
        track_findings(case.store, result, min_gap_seconds=60, min_corroborating_events=2)
    case.record_manifest()

    report = render_report(
        case_name="c", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Tracked Findings" in report
    assert "reviewed" in report and "validated" in report
    assert "annotation history is not retained" in report.lower()
    assert "not yet reviewed" in report
    case.close()


def test_report_untrusted_rendering_of_note_and_annotated_by(tmp_path: Path) -> None:
    case = _build_gap_case(tmp_path / "case")
    result = find_gaps(case.store, min_gap_seconds=60)
    with case.transaction():
        track_findings(case.store, result, min_gap_seconds=60, min_corroborating_events=2)
    finding_id = case.store.list_tracked_findings()[0].id
    case.store.annotate_tracked_finding(
        finding_id, status=FindingStatus.REVIEWED,
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
    case = _build_gap_case(case_dir)
    case.close()
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    malicious = "x'; DROP TABLE evidence_items; --"
    ack_result = runner.invoke(
        app,
        ["findings", "ack", str(case_dir), finding_id,
         "--status", "reviewed", "--by", "analyst:x", "--note", malicious],
    )
    assert ack_result.exit_code == 0

    case = Case.open(case_dir)
    stored = case.store.get_tracked_finding(finding_id)
    assert stored is not None
    assert stored.note == malicious
    assert len(case.store.list_evidence()) == 4  # store is intact
    case.close()


# -- Manifest / verify independence ---------------------------------------------


def test_manifest_unchanged_after_tracking(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    before = case.compute_manifest().manifest_hash
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "30", "--track"])

    case = Case.open(case_dir)
    after = case.compute_manifest().manifest_hash
    assert before == after
    case.close()


def test_manifest_unchanged_after_all_three_annotation_statuses(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    before = case.compute_manifest().manifest_hash
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()

    for status in ("open", "reviewed", "dismissed"):
        runner.invoke(
            app,
            ["findings", "ack", str(case_dir), finding_id,
             "--status", status, "--by", "analyst:x"],
        )
        case = Case.open(case_dir)
        assert case.compute_manifest().manifest_hash == before
        case.close()


def test_verify_verdict_unchanged_after_tracking_and_annotation(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()

    case = Case.open(case_dir)
    before = replay_and_verify(case)
    case.close()
    assert before.matches_recorded

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    finding_id = case.store.list_tracked_findings()[0].id
    case.close()
    runner.invoke(
        app,
        ["findings", "ack", str(case_dir), finding_id,
         "--status", "dismissed", "--by", "analyst:x"],
    )

    case = Case.open(case_dir)
    after = replay_and_verify(case)
    case.close()
    assert after.matches_recorded
    assert after.recomputed_manifest.manifest_hash == before.recomputed_manifest.manifest_hash


# -- Intentional identity churn on re-ingestion ---------------------------------


def test_reingestion_causing_new_corroboration_creates_new_identity(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    original_id = case.store.list_tracked_findings()[0].id
    case.close()

    # New evidence adds a THIRD host2 corroborating point inside the gap.
    case = Case.open(case_dir)
    _put(case, source_id="host2", value=_t(9, 15), label="extra")
    case.record_manifest()
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])

    case = Case.open(case_dir)
    tracked = case.store.list_tracked_findings()
    ids = {t.id for t in tracked}
    assert original_id in ids  # old row still stored, untouched
    assert len(ids) == 2  # a new, distinct id was created
    original = case.store.get_tracked_finding(original_id)
    assert original is not None
    assert not is_still_reproduced(case.store, original)
    case.close()


def test_disappeared_finding_status_is_never_auto_changed(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_gap_case(case_dir)
    case.close()

    runner.invoke(app, ["gaps", str(case_dir), "--min-gap-seconds", "60", "--track"])
    case = Case.open(case_dir)
    original_id = case.store.list_tracked_findings()[0].id
    case.close()
    runner.invoke(
        app,
        ["findings", "ack", str(case_dir), original_id,
         "--status", "open", "--by", "analyst:x"],
    )

    case = Case.open(case_dir)
    _put(case, source_id="host2", value=_t(9, 15), label="extra2")
    case.record_manifest()
    case.close()

    case = Case.open(case_dir)
    original = case.store.get_tracked_finding(original_id)
    assert original is not None
    assert original.status == FindingStatus.OPEN  # untouched by the tool
    assert not is_still_reproduced(case.store, original)
    case.close()


# -- Crash / transaction rollback ------------------------------------------------


def test_track_findings_rolls_back_all_new_rows_on_failure(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    case = _build_two_gap_case(case_dir)
    result = find_gaps(case.store, min_gap_seconds=60)
    assert len(result.findings) == 2

    call_count = {"n": 0}
    real_create = case.store.create_tracked_finding

    def _flaky_create(finding: TrackedGapFinding) -> TrackedGapFinding:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated crash mid-track")
        return real_create(finding)

    case.store.create_tracked_finding = _flaky_create  # type: ignore[method-assign]

    with pytest.raises(RuntimeError):
        with case.transaction():
            track_findings(case.store, result, min_gap_seconds=60, min_corroborating_events=2)

    case.store.create_tracked_finding = real_create  # type: ignore[method-assign]
    assert case.store.list_tracked_findings() == []  # fully rolled back
    case.close()


def test_annotate_tracked_finding_signature_has_no_anchor_parameter() -> None:
    """API-shape guard, at the store level: SqliteStore.annotate_tracked_finding
    accepts only id/status/annotated_by/annotated_at/note -- there is no
    parameter through which a caller could supply a different interval,
    source, or citation set for an existing row."""
    import inspect

    params = set(inspect.signature(SqliteStore.annotate_tracked_finding).parameters) - {"self"}
    assert params == {"id", "status", "annotated_by", "annotated_at", "note"}


def test_annotate_tracked_finding_does_not_move_anchor_end_to_end(tmp_path: Path) -> None:
    """Behavioral confirmation, on a real store: after multiple annotation
    updates, every anchor field of the stored row is byte-identical to
    what create_tracked_finding first wrote."""
    case = Case.create(tmp_path / "case")
    original = _tracked_finding_fixture()
    case.store.create_tracked_finding(original)

    case.store.annotate_tracked_finding(
        original.id, status=FindingStatus.REVIEWED, annotated_by="analyst:a",
        annotated_at=NOW, note="first",
    )
    final = case.store.annotate_tracked_finding(
        original.id, status=FindingStatus.DISMISSED, annotated_by="analyst:b",
        annotated_at=NOW, note="second",
    )

    assert final.id == original.id
    assert final.absent_source == original.absent_source
    assert final.present_source == original.present_source
    assert final.absent_source_refinement == original.absent_source_refinement
    assert final.present_source_refinement == original.present_source_refinement
    assert final.interval_start == original.interval_start
    assert final.interval_end == original.interval_end
    assert final.corroborating_time_assertion_ids == original.corroborating_time_assertion_ids
    assert final.bounding_absent_assertion_ids == original.bounding_absent_assertion_ids
    assert final.min_gap_seconds == original.min_gap_seconds
    assert final.min_corroborating_events == original.min_corroborating_events
    assert final.refine_source_by_attribute == original.refine_source_by_attribute
    case.close()


def _tracked_finding_fixture() -> TrackedGapFinding:
    return TrackedGapFinding(
        id=TrackedGapFinding.identity_hash(
            absent_source="host1", present_source="host2",
            absent_source_refinement=None, present_source_refinement=None,
            interval_start=_t(9, 0), interval_end=_t(9, 30),
            corroborating_time_assertion_ids=("a1", "a2"),
            bounding_absent_assertion_ids=("b1", "b2"),
        ),
        absent_source="host1", present_source="host2",
        absent_source_refinement=None, present_source_refinement=None,
        interval_start=_t(9, 0), interval_end=_t(9, 30),
        corroborating_time_assertion_ids=("a1", "a2"),
        bounding_absent_assertion_ids=("b1", "b2"),
        min_gap_seconds=60.0, min_corroborating_events=2,
        refine_source_by_attribute=None,
    )


# -- Export / import -------------------------------------------------------------


def test_export_import_preserves_tracked_findings_and_annotation(tmp_path: Path) -> None:
    case = _build_gap_case(tmp_path / "original")
    result = find_gaps(case.store, min_gap_seconds=60)
    with case.transaction():
        track_findings(case.store, result, min_gap_seconds=60, min_corroborating_events=2)
    finding_id = case.store.list_tracked_findings()[0].id
    case.store.annotate_tracked_finding(
        finding_id, status=FindingStatus.DISMISSED, annotated_by="analyst:x",
        annotated_at=NOW, note="benign",
    )
    case.record_manifest()
    original_findings = case.store.list_tracked_findings()

    archive = export_case(case, tmp_path / "case.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    restored_findings = restored.store.list_tracked_findings()
    assert restored_findings == original_findings
    restored.close()


# -- Backward compatibility with genuinely pre-v0.7 cases -----------------------


def _create_legacy_pre_v07_case_db(db_path: Path) -> None:
    """Build a case.db containing only the pre-v0.7 tables, simulating a
    case created by v0.1-v0.6 code (no tracked_gap_findings table)."""
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


def test_legacy_case_without_tracked_findings_table_opens_cleanly(tmp_path: Path) -> None:
    case_dir = tmp_path / "legacy_case"
    case_dir.mkdir()
    _create_legacy_pre_v07_case_db(case_dir / "case.db")

    store = SqliteStore(case_dir / "case.db")
    assert store.list_tracked_findings() == []
    # Existing tables/behavior are completely unaffected.
    assert store.list_evidence() == []
    store.close()

    case = Case.open(case_dir)
    assert case.store.list_tracked_findings() == []
    report = render_report(
        case_name="legacy", store=case.store, recomputed_manifest=case.compute_manifest(),
        recorded_manifest=case.load_recorded_manifest(),
    )
    assert "## Tracked Findings" not in report
    case.close()
