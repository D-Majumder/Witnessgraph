"""v1.0 Tour 1: `witnessgraph time-assertions create` -- an explicit,
analyst-declared TimeAssertion claim, grounded in cited evidence, about
when a NormalizedEvent occurred.

This is additive only: no existing command's behavior, and no existing
table/manifest/report format, changes. See docs' design discussion for
why ``source_evidence_id`` is intentionally allowed to differ from the
subject event's own ``derived_from`` -- a claim may be grounded in
evidence external to the event it is about (e.g. a manually researched
external timestamp for a syslog line that itself carries no usable
absolute time).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from witnessgraph.cli.main import app
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.correlate.contradictions import detect_time_contradictions
from witnessgraph.correlate.gaps import find_gaps
from witnessgraph.portable import export_case, import_case
from witnessgraph.replay.replay import replay_and_verify
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)
runner = CliRunner()


def _evidence(label: str, *, source_id: str | None = None, adapter: str = "jsonl") -> EvidenceItem:
    return EvidenceItem.create(
        raw_bytes=label.encode(),
        source_adapter=adapter,
        adapter_version="0.1.0",
        source_locator=f"{label}.jsonl:1",
        collected_at=NOW,
        source_id=source_id,
    )


def _event(evidence: EvidenceItem, *, event_type: str = "line") -> NormalizedEvent:
    return NormalizedEvent.create(
        event_type=event_type, attributes={}, derived_from=(evidence.id,), created_at=NOW
    )


def _build_basic_case(root: Path) -> tuple[Case, str, str]:
    """One event with one evidence item it was derived from."""
    case = Case.create(root)
    evidence = _evidence("a", source_id="host1")
    case.store.put_evidence(evidence)
    event = _event(evidence)
    case.store.put_normalized_event(event)
    case.record_manifest()
    return case, event.id, evidence.id


def _put_external_evidence(case: Case) -> str:
    """Store a second, unrelated evidence item -- for citing as "external"
    source evidence -- and return its id."""
    external_evidence = _evidence("external", source_id="host2")
    case.store.put_evidence(external_evidence)
    case.record_manifest()
    return external_evidence.id


# -- CLI: create, happy path ------------------------------------------------------


def test_create_new_assertion_prints_source_attribution(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code == 0
    out = result.stdout_bytes
    assert b"created time assertion" in out
    # source attribution must be visible and explicit about which evidence
    # coverage is attributed through.
    assert evidence_id.encode() in out
    assert b"attributed" in out
    assert b"analyst:jane" in out or b"'analyst:jane'" in out

    case = Case.open(tmp_path / "case")
    assertions = case.store.list_time_assertions()
    assert len(assertions) == 1
    assert assertions[0].asserted_by == "analyst:jane"
    assert assertions[0].source_evidence_id == evidence_id
    case.close()


def test_create_uses_claim_not_adjudicated_fact_language(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code == 0
    assert b"claim" in result.stdout_bytes.lower()


# -- CLI: help text terminology ----------------------------------------------------


def test_create_help_uses_claim_language_not_evidentiary_time() -> None:
    result = runner.invoke(app, ["time-assertions", "create", "--help"])
    assert result.exit_code == 0
    help_text = result.stdout.lower()
    assert "claim" in help_text
    assert "adjudicat" in help_text
    assert "analyst-declared evidentiary time" not in help_text


# -- CLI: duplicate / idempotent creation -------------------------------------------


def test_duplicate_creation_reports_already_exists_and_persists_one_row(
    tmp_path: Path,
) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    args = [
        "time-assertions", "create", str(case_dir), event_id,
        "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
        "--source-evidence", evidence_id, "--by", "analyst:jane",
    ]
    first = runner.invoke(app, args)
    assert first.exit_code == 0
    assert b"created time assertion" in first.stdout_bytes

    second = runner.invoke(app, args)
    assert second.exit_code == 0
    assert b"already exists" in second.stdout_bytes

    case = Case.open(case_dir)
    assert len(case.store.list_time_assertions()) == 1
    case.close()


# -- CLI: --by validation -----------------------------------------------------------


def test_create_requires_by_with_no_default(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id,
        ],
    )
    assert result.exit_code != 0


def test_create_rejects_whitespace_only_by_before_any_write(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "   ",
        ],
    )
    assert result.exit_code != 0
    assert b"--by" in result.stderr_bytes
    assert b"blank" in result.stderr_bytes.lower()

    case = Case.open(case_dir)
    assert case.store.list_time_assertions() == []
    case.close()


def test_create_rejects_empty_string_by(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "",
        ],
    )
    assert result.exit_code != 0


# -- CLI: --value validation ---------------------------------------------------------


def test_create_rejects_naive_timestamp(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code != 0
    assert b"--value" in result.stderr_bytes
    assert b"timezone" in result.stderr_bytes.lower()

    case = Case.open(case_dir)
    assert case.store.list_time_assertions() == []
    case.close()


def test_create_rejects_malformed_timestamp(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "not-a-timestamp", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code != 0
    assert b"--value" in result.stderr_bytes


@pytest.mark.parametrize(
    "value",
    [
        "2026-01-01T09:00:00+00:00",
        "2026-01-01T09:00:00-05:00",
        "2026-01-01T09:00:00+05:30",
        "2026-01-01T09:00:00Z",
    ],
)
def test_create_accepts_various_timezone_aware_offsets(tmp_path: Path, value: str) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", value, "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code == 0


# -- CLI: --precision -----------------------------------------------------------------


@pytest.mark.parametrize(
    "precision", ["exact", "second", "minute", "hour", "day", "approximate"]
)
def test_create_accepts_all_precision_values(tmp_path: Path, precision: str) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", precision,
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code == 0


def test_create_rejects_invalid_precision(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "fortnight",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code != 0


# -- CLI: event / evidence id validation ------------------------------------------------


def test_create_rejects_unknown_event_id(tmp_path: Path) -> None:
    case, _event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), "nonexistent-event",
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code != 0
    assert b"NormalizedEvent" in result.stderr_bytes


def test_create_rejects_unknown_evidence_id(tmp_path: Path) -> None:
    case, event_id, _evidence_id = _build_basic_case(tmp_path / "case")
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", "nonexistent-evidence", "--by", "analyst:jane",
        ],
    )
    assert result.exit_code != 0
    assert b"EvidenceItem" in result.stderr_bytes


def test_create_allows_source_evidence_outside_event_derived_from(tmp_path: Path) -> None:
    """B4/decision 5: source_evidence_id is intentionally allowed to differ
    from the subject event's own derived_from."""
    case, event_id, _own_evidence_id = _build_basic_case(tmp_path / "case")
    external_evidence_id = _put_external_evidence(case)
    assert external_evidence_id != _own_evidence_id
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(tmp_path / "case"), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", external_evidence_id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code == 0

    case = Case.open(tmp_path / "case")
    assertion = case.store.list_time_assertions()[0]
    assert assertion.source_evidence_id == external_evidence_id
    event = case.store.get_normalized_event(event_id)
    assert event is not None
    assert external_evidence_id not in event.derived_from
    case.close()


# -- Adapter-derived asserted_by convention (B3) --------------------------------------


def test_adapter_derived_asserted_by_uses_reserved_prefix_distinct_from_analyst(
    tmp_path: Path,
) -> None:
    """B3: ingest-derived TimeAssertions use the reserved `adapter:<name>`
    format, structurally distinct from any `--by`-supplied analyst identity."""
    case = Case.create(tmp_path / "case")
    evidence = _evidence("a")
    case.store.put_evidence(evidence)
    event = NormalizedEvent.create(
        event_type="line",
        attributes={"timestamp": "2026-01-01T09:00:00+00:00"},
        derived_from=(evidence.id,),
        created_at=NOW,
    )
    case.store.put_normalized_event(event)
    from witnessgraph.ingest.pipeline import _derive_time_assertion

    assertion = _derive_time_assertion(event, evidence)
    assert assertion is not None
    assert assertion.asserted_by == f"adapter:{evidence.source_adapter}"
    assert not assertion.asserted_by.startswith("analyst")
    case.close()


# -- Contradiction detection interplay with analyst identity --------------------------


def test_same_value_different_analysts_no_contradiction(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    for analyst in ("analyst:jane", "analyst:bob"):
        result = runner.invoke(
            app,
            [
                "time-assertions", "create", str(case_dir), event_id,
                "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
                "--source-evidence", evidence_id, "--by", analyst,
            ],
        )
        assert result.exit_code == 0

    case = Case.open(case_dir)
    assertions = case.store.list_time_assertions()
    assert len(assertions) == 2  # distinct ids: asserted_by is part of identity
    contradictions = detect_time_contradictions(case.store)
    assert contradictions == []
    case.close()


def test_different_value_different_analysts_contradiction(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:30:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:bob",
        ],
    )

    case = Case.open(case_dir)
    contradictions = detect_time_contradictions(case.store)
    assert len(contradictions) == 1
    asserted_by_pair = {
        contradictions[0].assertion_a.asserted_by,
        contradictions[0].assertion_b.asserted_by,
    }
    assert asserted_by_pair == {"analyst:jane", "analyst:bob"}
    case.close()


# -- Syslog event + external source evidence: gap-analysis participation --------------


def test_syslog_event_with_external_source_evidence_participates_in_gap_analysis(
    tmp_path: Path,
) -> None:
    """A syslog-derived NormalizedEvent whose own evidence declares no
    source (naive raw_timestamp only, no auto TimeAssertion) can still
    receive a manually created TimeAssertion citing a *different*,
    source-declared EvidenceItem -- and that assertion participates in
    gap analysis exactly like an ordinary one, grouped under the cited
    evidence's declared source."""
    case_dir = tmp_path / "case"
    case = Case.create(case_dir)

    def _t(hour: int, minute: int = 0) -> datetime:
        return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)

    # host1's first bracket point: an ordinary, directly-derived-style assertion.
    host1_evidence_a = _evidence("host1-a", source_id="host1")
    case.store.put_evidence(host1_evidence_a)
    host1_event_a = _event(host1_evidence_a)
    case.store.put_normalized_event(host1_event_a)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=host1_event_a.id, value=_t(9, 0), precision=TimePrecision.EXACT,
            source_evidence_id=host1_evidence_a.id, asserted_by="adapter:jsonl", created_at=NOW,
        )
    )

    # host1's second bracket point: a *syslog* event whose own evidence
    # declares no source, with a manual TimeAssertion citing separate,
    # external evidence that does declare "host1".
    syslog_evidence = _evidence("syslog-line", source_id=None, adapter="syslog")
    case.store.put_evidence(syslog_evidence)
    syslog_event = NormalizedEvent.create(
        event_type="syslog_line", attributes={"raw_timestamp": "Jan 15 09:40:00"},
        derived_from=(syslog_evidence.id,), created_at=NOW,
    )
    case.store.put_normalized_event(syslog_event)

    external_host1_evidence = _evidence("external-host1-record", source_id="host1")
    case.store.put_evidence(external_host1_evidence)
    case.record_manifest()
    case.close()

    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), syslog_event.id,
            "--value", "2026-01-01T09:40:00+00:00", "--precision", "second",
            "--source-evidence", external_host1_evidence.id, "--by", "analyst:jane",
        ],
    )
    assert result.exit_code == 0

    # host2 corroborates within the gap.
    case = Case.open(case_dir)
    host2_a = _evidence("host2-a", source_id="host2")
    case.store.put_evidence(host2_a)
    host2_event_a = _event(host2_a)
    case.store.put_normalized_event(host2_event_a)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=host2_event_a.id, value=_t(9, 10), precision=TimePrecision.EXACT,
            source_evidence_id=host2_a.id, asserted_by="adapter:jsonl", created_at=NOW,
        )
    )
    host2_b = _evidence("host2-b", source_id="host2")
    case.store.put_evidence(host2_b)
    host2_event_b = _event(host2_b)
    case.store.put_normalized_event(host2_event_b)
    case.store.put_time_assertion(
        TimeAssertion.create(
            subject_event_id=host2_event_b.id, value=_t(9, 20), precision=TimePrecision.EXACT,
            source_evidence_id=host2_b.id, asserted_by="adapter:jsonl", created_at=NOW,
        )
    )
    case.record_manifest()

    gap_result = find_gaps(case.store, min_gap_seconds=60)
    assert len(gap_result.findings) == 1
    finding = gap_result.findings[0]
    assert {finding.absent_source, finding.present_source} == {"host1", "host2"}
    assert gap_result.excluded_no_declared_source == 0
    case.close()


# -- Manifest / verify -----------------------------------------------------------------


def test_manifest_recorded_after_create_and_after_duplicate(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    args = [
        "time-assertions", "create", str(case_dir), event_id,
        "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
        "--source-evidence", evidence_id, "--by", "analyst:jane",
    ]
    runner.invoke(app, args)
    case = Case.open(case_dir)
    verify_after_create = replay_and_verify(case)
    assert verify_after_create.matches_recorded
    case.close()

    runner.invoke(app, args)  # duplicate
    case = Case.open(case_dir)
    verify_after_duplicate = replay_and_verify(case)
    assert verify_after_duplicate.matches_recorded  # manifest recorded again, still matches
    case.close()


def test_stale_manifest_before_create_and_corrected_after(tmp_path: Path) -> None:
    """Pre-existing stale-manifest failure window: a manifest recorded
    before a write (here, the new TimeAssertion) legitimately mismatches
    until the case is next opened and its manifest re-recorded -- this is
    documented, pre-existing behavior, not something this feature changes
    or must fix."""
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    # Write directly through the store, bypassing record_manifest, to
    # simulate a stale on-disk manifest.
    case = Case.open(case_dir)
    assertion = TimeAssertion.create(
        subject_event_id=event_id, value=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
        precision=TimePrecision.SECOND, source_evidence_id=evidence_id,
        asserted_by="analyst:jane", created_at=NOW,
    )
    case.store.put_time_assertion(assertion)
    stale_result = replay_and_verify(case)
    assert not stale_result.matches_recorded
    case.close()

    # The CLI command always calls record_manifest(), so a subsequent
    # (duplicate) invocation corrects the on-disk manifest.
    runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    case = Case.open(case_dir)
    corrected_result = replay_and_verify(case)
    assert corrected_result.matches_recorded
    case.close()


def test_record_manifest_failure_after_successful_put_leaves_row_and_verify_detects_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    real_record_manifest = Case.record_manifest

    def _flaky_record_manifest(self: Case) -> object:
        raise RuntimeError("simulated manifest-recording crash")

    monkeypatch.setattr(Case, "record_manifest", _flaky_record_manifest)
    with pytest.raises(RuntimeError):
        runner_result = runner.invoke(
            app,
            [
                "time-assertions", "create", str(case_dir), event_id,
                "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
                "--source-evidence", evidence_id, "--by", "analyst:jane",
            ],
            catch_exceptions=False,
        )
        assert runner_result is not None  # unreachable; invoke raises via catch_exceptions=False
    monkeypatch.setattr(Case, "record_manifest", real_record_manifest)

    # The put itself already committed (SqliteStore commits put_time_assertion
    # immediately outside of an explicit transaction() block), so the row
    # persists even though manifest recording failed afterward.
    case = Case.open(case_dir)
    assert len(case.store.list_time_assertions()) == 1
    verify_result = replay_and_verify(case)
    assert not verify_result.matches_recorded
    case.close()


def test_timeline_command_unchanged_by_manual_assertion(tmp_path: Path) -> None:
    """Regression: `timeline` (unmodified in this Tour) continues to order
    normalized events by earliest known time assertion, including one
    created via the new command."""
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    before = runner.invoke(app, ["timeline", str(case_dir)])
    assert before.exit_code == 0
    assert b"(no time assertion)" in before.stdout_bytes

    runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )
    after = runner.invoke(app, ["timeline", str(case_dir)])
    assert after.exit_code == 0
    assert b"2026-01-01T09:00:00" in after.stdout_bytes


# -- Export / import ---------------------------------------------------------------


def test_export_import_preserves_manually_created_time_assertion(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "original")
    case.close()
    case_dir = tmp_path / "original"

    runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", "analyst:jane",
        ],
    )

    case = Case.open(case_dir)
    original_assertions = case.store.list_time_assertions()
    archive = export_case(case, tmp_path / "case.wgcase")
    case.close()

    restored = import_case(archive, tmp_path / "restored")
    assert restored.store.list_time_assertions() == original_assertions
    verify_result = replay_and_verify(restored)
    assert verify_result.matches_recorded
    restored.close()


# -- Untrusted-input safety ---------------------------------------------------------


def test_unicode_bidi_control_character_by_round_trips_safely(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    tricky_by = "analyst​-x‮-́name"
    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", tricky_by,
        ],
    )
    assert result.exit_code == 0

    case = Case.open(case_dir)
    stored = case.store.list_time_assertions()[0]
    assert stored.asserted_by == tricky_by  # stored verbatim, opaque to the store layer
    case.close()


def test_sql_shell_like_by_value_treated_as_opaque(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    malicious = "x'; DROP TABLE evidence_items; --"
    result = runner.invoke(
        app,
        [
            "time-assertions", "create", str(case_dir), event_id,
            "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
            "--source-evidence", evidence_id, "--by", malicious,
        ],
    )
    assert result.exit_code == 0

    case = Case.open(case_dir)
    stored = case.store.list_time_assertions()[0]
    assert stored.asserted_by == malicious
    assert len(case.store.list_evidence()) == 1  # store is intact
    case.close()


def test_different_analyst_produces_distinct_identity(tmp_path: Path) -> None:
    case, event_id, evidence_id = _build_basic_case(tmp_path / "case")
    case.close()
    case_dir = tmp_path / "case"

    args_common = [
        "time-assertions", "create", str(case_dir), event_id,
        "--value", "2026-01-01T09:00:00+00:00", "--precision", "second",
        "--source-evidence", evidence_id,
    ]
    runner.invoke(app, [*args_common, "--by", "analyst:jane"])
    runner.invoke(app, [*args_common, "--by", "analyst:bob"])

    case = Case.open(case_dir)
    assertions = case.store.list_time_assertions()
    assert len(assertions) == 2
    ids = {a.id for a in assertions}
    assert len(ids) == 2
    case.close()
