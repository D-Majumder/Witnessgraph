"""v0.7: TrackedGapFinding identity/model invariants and SqliteStore
persistence semantics for persisted gap-finding tracking.

Uses only synthetic fixtures -- no real systems contacted or scanned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from witnessgraph.core.tracked_finding import FindingStatus, TrackedGapFinding
from witnessgraph.correlate.gaps import GapFinding
from witnessgraph.correlate.tracking import tracked_finding_to_json
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _t(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


def _finding(**overrides: object) -> GapFinding:
    base: dict[str, object] = {
        "absent_source": "host1",
        "present_source": "host2",
        "interval_start": _t(9, 0),
        "interval_end": _t(9, 30),
        "corroborating_time_assertion_ids": ("a1", "a2"),
        "bounding_absent_assertion_ids": ("b1", "b2"),
        "absent_source_refinement": None,
        "present_source_refinement": None,
    }
    base.update(overrides)
    return GapFinding(**base)  # type: ignore[arg-type]


def _id_for(finding: GapFinding) -> str:
    return TrackedGapFinding.identity_hash(
        absent_source=finding.absent_source,
        present_source=finding.present_source,
        absent_source_refinement=finding.absent_source_refinement,
        present_source_refinement=finding.present_source_refinement,
        interval_start=finding.interval_start,
        interval_end=finding.interval_end,
        corroborating_time_assertion_ids=finding.corroborating_time_assertion_ids,
        bounding_absent_assertion_ids=finding.bounding_absent_assertion_ids,
    )


def _tracked_from(finding: GapFinding, **overrides: object) -> TrackedGapFinding:
    fields: dict[str, object] = {
        "id": _id_for(finding),
        "absent_source": finding.absent_source,
        "present_source": finding.present_source,
        "absent_source_refinement": finding.absent_source_refinement,
        "present_source_refinement": finding.present_source_refinement,
        "interval_start": finding.interval_start,
        "interval_end": finding.interval_end,
        "corroborating_time_assertion_ids": finding.corroborating_time_assertion_ids,
        "bounding_absent_assertion_ids": finding.bounding_absent_assertion_ids,
        "min_gap_seconds": 60.0,
        "min_corroborating_events": 2,
        "refine_source_by_attribute": None,
    }
    fields.update(overrides)
    return TrackedGapFinding(**fields)  # type: ignore[arg-type]


# -- Identity determinism -----------------------------------------------------


def test_identity_is_deterministic_across_independent_builds() -> None:
    a = _id_for(_finding())
    b = _id_for(_finding())
    assert a == b


def test_identity_changes_when_absent_source_changes() -> None:
    assert _id_for(_finding()) != _id_for(_finding(absent_source="other"))


def test_identity_changes_when_present_source_changes() -> None:
    assert _id_for(_finding()) != _id_for(_finding(present_source="other"))


def test_identity_changes_when_interval_start_changes() -> None:
    assert _id_for(_finding()) != _id_for(_finding(interval_start=_t(9, 5)))


def test_identity_changes_when_interval_end_changes() -> None:
    assert _id_for(_finding()) != _id_for(_finding(interval_end=_t(9, 35)))


def test_identity_changes_when_corroborating_ids_change() -> None:
    assert _id_for(_finding()) != _id_for(
        _finding(corroborating_time_assertion_ids=("a1", "a2", "a3"))
    )


def test_identity_changes_when_bounding_ids_change() -> None:
    assert _id_for(_finding()) != _id_for(_finding(bounding_absent_assertion_ids=("b1", "b3")))


def test_identity_changes_when_absent_refinement_changes() -> None:
    assert _id_for(_finding()) != _id_for(_finding(absent_source_refinement="real-a"))


def test_identity_changes_when_present_refinement_changes() -> None:
    assert _id_for(_finding()) != _id_for(_finding(present_source_refinement="real-b"))


def test_identity_excludes_analysis_parameters() -> None:
    finding = _finding()
    a = _tracked_from(finding, min_gap_seconds=60.0, min_corroborating_events=2)
    b = _tracked_from(finding, min_gap_seconds=30.0, min_corroborating_events=3)
    assert a.id == b.id


def test_identity_excludes_refine_source_by_attribute_parameter() -> None:
    finding = _finding()
    a = _tracked_from(finding, refine_source_by_attribute=None)
    b = _tracked_from(finding, refine_source_by_attribute="host")
    assert a.id == b.id


def test_identity_excludes_annotation_fields() -> None:
    finding = _finding()
    a = _tracked_from(finding)
    b = _tracked_from(
        finding,
        status=FindingStatus.DISMISSED,
        annotated_by="analyst:x",
        annotated_at=NOW,
        note="some note",
    )
    assert a.id == b.id


# -- Model invariants ----------------------------------------------------------


def test_fresh_tracked_finding_defaults_to_open_with_no_annotation() -> None:
    tracked = _tracked_from(_finding())
    assert tracked.status == FindingStatus.OPEN
    assert tracked.annotated_by is None
    assert tracked.annotated_at is None
    assert tracked.note is None


def test_refine_source_by_attribute_is_str_or_none_not_empty_string() -> None:
    tracked = _tracked_from(_finding())
    assert tracked.refine_source_by_attribute is None  # not ""


def test_annotated_by_without_annotated_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _tracked_from(_finding(), annotated_by="analyst:x", annotated_at=None)


def test_annotated_at_without_annotated_by_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _tracked_from(_finding(), annotated_by=None, annotated_at=NOW)


def test_blank_annotated_by_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _tracked_from(_finding(), annotated_by="   ", annotated_at=NOW)


def test_with_annotation_rejects_whitespace_only_annotated_by() -> None:
    """Regression for the blocker found in adversarial implementation
    review: with_annotation() previously relied on model_copy(update=...)
    to re-run validation, but Pydantic v2's model_copy deliberately does
    NOT re-run validators -- so this call path silently accepted a
    whitespace-only annotated_by even though the constructor rejects it.
    This exercises the actual update path (with_annotation), not the
    constructor, which is the distinction that let the original defect
    through the test suite undetected."""
    original = _tracked_from(_finding())
    with pytest.raises(ValueError, match="must not be blank"):
        original.with_annotation(
            status=FindingStatus.REVIEWED, annotated_by="   ", annotated_at=NOW, note=None
        )


def test_with_annotation_rejects_empty_string_annotated_by() -> None:
    original = _tracked_from(_finding())
    with pytest.raises(ValueError, match="must not be blank"):
        original.with_annotation(
            status=FindingStatus.REVIEWED, annotated_by="", annotated_at=NOW, note=None
        )


def test_with_annotation_whitespace_only_annotated_by_does_not_mutate_original() -> None:
    """A rejected with_annotation() call must not have side effects on the
    original, already-frozen object -- it should simply raise, leaving
    the caller's existing reference exactly as it was."""
    original = _tracked_from(
        _finding(), status=FindingStatus.DISMISSED, annotated_by="analyst:x",
        annotated_at=NOW, note="first",
    )
    with pytest.raises(ValueError):
        original.with_annotation(
            status=FindingStatus.OPEN, annotated_by="   ", annotated_at=NOW, note="attempted"
        )
    assert original.status == FindingStatus.DISMISSED
    assert original.annotated_by == "analyst:x"
    assert original.note == "first"


def test_with_annotation_preserves_every_anchor_field() -> None:
    original = _tracked_from(_finding())
    updated = original.with_annotation(
        status=FindingStatus.DISMISSED, annotated_by="analyst:x", annotated_at=NOW, note="n"
    )
    assert updated.id == original.id
    assert updated.absent_source == original.absent_source
    assert updated.present_source == original.present_source
    assert updated.absent_source_refinement == original.absent_source_refinement
    assert updated.present_source_refinement == original.present_source_refinement
    assert updated.interval_start == original.interval_start
    assert updated.interval_end == original.interval_end
    assert updated.corroborating_time_assertion_ids == original.corroborating_time_assertion_ids
    assert updated.bounding_absent_assertion_ids == original.bounding_absent_assertion_ids
    assert updated.min_gap_seconds == original.min_gap_seconds
    assert updated.min_corroborating_events == original.min_corroborating_events
    assert updated.refine_source_by_attribute == original.refine_source_by_attribute
    # Only the annotation fields changed.
    assert updated.status == FindingStatus.DISMISSED
    assert updated.annotated_by == "analyst:x"
    assert updated.annotated_at == NOW
    assert updated.note == "n"


def test_with_annotation_has_no_parameter_for_any_anchor_field() -> None:
    """API-shape guard: with_annotation's signature literally cannot accept
    an anchor field -- this is what makes anchor mutation impossible by
    construction, not merely by convention."""
    import inspect

    params = set(inspect.signature(TrackedGapFinding.with_annotation).parameters)
    anchor_fields = {
        "absent_source",
        "present_source",
        "absent_source_refinement",
        "present_source_refinement",
        "interval_start",
        "interval_end",
        "corroborating_time_assertion_ids",
        "bounding_absent_assertion_ids",
        "min_gap_seconds",
        "min_corroborating_events",
        "refine_source_by_attribute",
    }
    assert params.isdisjoint(anchor_fields)


# -- Store: create_tracked_finding (insert-if-absent) -------------------------


def test_create_tracked_finding_inserts_a_fresh_row(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    finding = _tracked_from(_finding())
    stored = case.store.create_tracked_finding(finding)
    assert stored == finding
    assert case.store.get_tracked_finding(finding.id) == finding
    case.close()


def test_create_tracked_finding_never_resets_existing_annotation(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    original = _tracked_from(_finding())
    case.store.create_tracked_finding(original)
    annotated = case.store.annotate_tracked_finding(
        original.id,
        status=FindingStatus.DISMISSED,
        annotated_by="analyst:x",
        annotated_at=NOW,
        note="reviewed and dismissed",
    )

    # Re-discovery: a freshly built, never-annotated candidate with the
    # SAME id is offered again (as gaps --track would do on a re-run).
    rediscovered_candidate = _tracked_from(_finding())
    result = case.store.create_tracked_finding(rediscovered_candidate)

    assert result == annotated  # unchanged: still dismissed, still annotated
    assert case.store.get_tracked_finding(original.id) == annotated
    case.close()


# -- Store: annotate_tracked_finding -------------------------------------------


def test_annotate_tracked_finding_unknown_id_raises(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    with pytest.raises(ValueError):
        case.store.annotate_tracked_finding(
            "nonexistent", status=FindingStatus.REVIEWED, annotated_by="a", annotated_at=NOW,
            note=None,
        )
    case.close()


def test_annotate_tracked_finding_rejects_whitespace_only_annotated_by(tmp_path: Path) -> None:
    """Store-level regression for the adversarial-review blocker: the
    store's annotation-update entry point must reject a whitespace-only
    identity, and the row must remain unchanged (not partially updated)."""
    case = Case.create(tmp_path / "case")
    original = _tracked_from(_finding())
    case.store.create_tracked_finding(original)

    with pytest.raises(ValueError, match="must not be blank"):
        case.store.annotate_tracked_finding(
            original.id, status=FindingStatus.DISMISSED, annotated_by="   ",
            annotated_at=NOW, note="should not persist",
        )

    stored = case.store.get_tracked_finding(original.id)
    assert stored is not None
    assert stored.status == FindingStatus.OPEN  # unchanged
    assert stored.annotated_by is None  # unchanged
    assert stored.note is None  # unchanged
    case.close()


def test_annotate_tracked_finding_changes_only_annotation_fields(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    original = _tracked_from(_finding())
    case.store.create_tracked_finding(original)

    updated = case.store.annotate_tracked_finding(
        original.id, status=FindingStatus.REVIEWED, annotated_by="analyst:y",
        annotated_at=NOW, note="looks fine",
    )

    assert updated.id == original.id
    assert updated.absent_source == original.absent_source
    assert updated.present_source == original.present_source
    assert updated.interval_start == original.interval_start
    assert updated.interval_end == original.interval_end
    assert updated.corroborating_time_assertion_ids == original.corroborating_time_assertion_ids
    assert updated.bounding_absent_assertion_ids == original.bounding_absent_assertion_ids
    assert updated.status == FindingStatus.REVIEWED
    assert updated.annotated_by == "analyst:y"
    assert updated.note == "looks fine"
    case.close()


def test_annotate_tracked_finding_replacement_is_not_archived(tmp_path: Path) -> None:
    """No history: overwriting an annotation discards the previous one --
    there is no API to recover a prior status/attribution/note."""
    case = Case.create(tmp_path / "case")
    original = _tracked_from(_finding())
    case.store.create_tracked_finding(original)
    case.store.annotate_tracked_finding(
        original.id, status=FindingStatus.REVIEWED, annotated_by="analyst:first",
        annotated_at=NOW, note="first note",
    )
    final = case.store.annotate_tracked_finding(
        original.id, status=FindingStatus.DISMISSED, annotated_by="analyst:second",
        annotated_at=NOW, note="second note",
    )
    stored = case.store.get_tracked_finding(original.id)
    assert stored == final
    assert stored is not None
    assert stored.annotated_by == "analyst:second"
    assert stored.note == "second note"
    # The first annotation is nowhere to be found in the stored row.
    case.close()


# -- Store: listing --------------------------------------------------------------


def test_list_tracked_findings_is_ordered_by_id(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    f1 = _tracked_from(_finding(absent_source="host1"))
    f2 = _tracked_from(_finding(absent_source="host9"))
    case.store.create_tracked_finding(f2)
    case.store.create_tracked_finding(f1)
    listed = case.store.list_tracked_findings()
    assert [f.id for f in listed] == sorted(f.id for f in [f1, f2])
    case.close()


def test_list_tracked_findings_empty_on_fresh_case(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    assert case.store.list_tracked_findings() == []
    case.close()


# -- tracked_finding_to_json -----------------------------------------------


def test_tracked_finding_to_json_includes_still_reproduced_field() -> None:
    tracked = _tracked_from(_finding())
    doc = tracked_finding_to_json(tracked, still_reproduced=True)
    assert doc["id"] == tracked.id
    assert doc["still_reproduced"] is True
    assert doc["status"] == "open"


def test_tracked_finding_to_json_still_reproduced_is_caller_supplied() -> None:
    """still_reproduced is never derived from the model itself -- it is
    whatever the caller passes, since it is a live fact the function has
    no store access to recompute on its own."""
    tracked = _tracked_from(_finding())
    assert tracked_finding_to_json(tracked, still_reproduced=True)["still_reproduced"] is True
    assert tracked_finding_to_json(tracked, still_reproduced=False)["still_reproduced"] is False


def test_tracked_finding_to_json_reflects_annotation() -> None:
    tracked = _tracked_from(_finding()).with_annotation(
        status=FindingStatus.DISMISSED, annotated_by="analyst:jane",
        annotated_at=NOW, note="benign",
    )
    doc = tracked_finding_to_json(tracked, still_reproduced=False)
    assert doc["status"] == "dismissed"
    assert doc["annotated_by"] == "analyst:jane"
    assert doc["note"] == "benign"
