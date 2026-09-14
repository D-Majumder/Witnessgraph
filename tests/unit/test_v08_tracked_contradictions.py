"""v0.8: TrackedTimeContradiction identity/model invariants and
SqliteStore persistence semantics for persisted time-contradiction
tracking.

Uses only synthetic fixtures -- no real systems contacted or scanned.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from witnessgraph.core.tracked_finding import FindingStatus
from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction
from witnessgraph.correlate.contradiction_tracking import tracked_contradiction_to_json
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _tracked(**overrides: object) -> TrackedTimeContradiction:
    fields: dict[str, object] = {
        "id": TrackedTimeContradiction.identity_hash(
            subject_event_id="evt-1", assertion_ids=("a1", "a2")
        ),
        "subject_event_id": "evt-1",
        "assertion_ids": ("a1", "a2"),
    }
    fields.update(overrides)
    return TrackedTimeContradiction(**fields)  # type: ignore[arg-type]


# -- Identity: exact, normative payload ----------------------------------------


def test_identity_is_deterministic_across_independent_builds() -> None:
    a = TrackedTimeContradiction.identity_hash(subject_event_id="evt-1", assertion_ids=("a1", "a2"))
    b = TrackedTimeContradiction.identity_hash(subject_event_id="evt-1", assertion_ids=("a1", "a2"))
    assert a == b


def test_identity_is_order_independent() -> None:
    """The two assertions are symmetric peers -- swapping which one a
    caller labels 'first' must produce the SAME id. This is the one
    place identity genuinely differs from GapFinding's asymmetric
    absent_source/present_source, which must never be reordered."""
    a = TrackedTimeContradiction.identity_hash(subject_event_id="evt-1", assertion_ids=("a1", "a2"))
    b = TrackedTimeContradiction.identity_hash(subject_event_id="evt-1", assertion_ids=("a2", "a1"))
    assert a == b


def test_identity_changes_when_subject_event_id_changes() -> None:
    a = TrackedTimeContradiction.identity_hash(subject_event_id="evt-1", assertion_ids=("a1", "a2"))
    b = TrackedTimeContradiction.identity_hash(subject_event_id="evt-2", assertion_ids=("a1", "a2"))
    assert a != b


def test_identity_changes_when_either_assertion_id_changes() -> None:
    base = TrackedTimeContradiction.identity_hash(
        subject_event_id="evt-1", assertion_ids=("a1", "a2")
    )
    changed_first = TrackedTimeContradiction.identity_hash(
        subject_event_id="evt-1", assertion_ids=("a3", "a2")
    )
    changed_second = TrackedTimeContradiction.identity_hash(
        subject_event_id="evt-1", assertion_ids=("a1", "a3")
    )
    assert base != changed_first
    assert base != changed_second
    assert changed_first != changed_second


def test_identity_hash_rejects_duplicate_assertion_ids() -> None:
    with pytest.raises(ValueError, match="DISTINCT"):
        TrackedTimeContradiction.identity_hash(subject_event_id="evt-1", assertion_ids=("a1", "a1"))


def test_identity_excludes_annotation_fields() -> None:
    a = _tracked()
    b = _tracked(
        status=FindingStatus.DISMISSED, annotated_by="analyst:x", annotated_at=NOW, note="n"
    )
    assert a.id == b.id


# -- Model invariants: distinctness, canonical order, annotation pairing -------


def test_fresh_tracked_contradiction_defaults_to_open_with_no_annotation() -> None:
    tracked = _tracked()
    assert tracked.status == FindingStatus.OPEN
    assert tracked.annotated_by is None
    assert tracked.annotated_at is None
    assert tracked.note is None


def test_constructor_rejects_duplicate_assertion_ids() -> None:
    with pytest.raises(ValidationError, match="DISTINCT"):
        TrackedTimeContradiction(
            id="whatever",
            subject_event_id="evt-1",
            assertion_ids=("a1", "a1"),
        )


def test_constructor_rejects_out_of_order_assertion_ids() -> None:
    with pytest.raises(ValidationError, match="canonical sorted order"):
        TrackedTimeContradiction(
            id="whatever",
            subject_event_id="evt-1",
            assertion_ids=("a2", "a1"),
        )


def test_annotated_by_without_annotated_at_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _tracked(annotated_by="analyst:x", annotated_at=None)


def test_annotated_at_without_annotated_by_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _tracked(annotated_by=None, annotated_at=NOW)


def test_blank_annotated_by_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _tracked(annotated_by="   ", annotated_at=NOW)


def test_with_annotation_rejects_whitespace_only_annotated_by() -> None:
    """Regression, applied proactively (not re-discovered): with_annotation
    must explicitly validate before model_copy, exactly as the v0.7
    blocker fix requires -- model_copy(update=...) does not re-run
    Pydantic validators."""
    original = _tracked()
    with pytest.raises(ValueError, match="must not be blank"):
        original.with_annotation(
            status=FindingStatus.REVIEWED, annotated_by="   ", annotated_at=NOW, note=None
        )


def test_with_annotation_preserves_every_anchor_field() -> None:
    original = _tracked()
    updated = original.with_annotation(
        status=FindingStatus.DISMISSED, annotated_by="analyst:x", annotated_at=NOW, note="n"
    )
    assert updated.id == original.id
    assert updated.subject_event_id == original.subject_event_id
    assert updated.assertion_ids == original.assertion_ids
    assert updated.status == FindingStatus.DISMISSED
    assert updated.annotated_by == "analyst:x"
    assert updated.annotated_at == NOW
    assert updated.note == "n"


def test_with_annotation_has_no_parameter_for_any_anchor_field() -> None:
    import inspect

    params = set(inspect.signature(TrackedTimeContradiction.with_annotation).parameters)
    assert params.isdisjoint({"subject_event_id", "assertion_ids"})


def test_status_vocabulary_is_exactly_open_reviewed_dismissed() -> None:
    assert {s.value for s in FindingStatus} == {"open", "reviewed", "dismissed"}


# -- Store: create_tracked_contradiction (insert-if-absent) --------------------


def test_create_tracked_contradiction_inserts_a_fresh_row(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    contradiction = _tracked()
    stored = case.store.create_tracked_contradiction(contradiction)
    assert stored == contradiction
    assert case.store.get_tracked_contradiction(contradiction.id) == contradiction
    case.close()


def test_create_tracked_contradiction_never_resets_existing_annotation(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    original = _tracked()
    case.store.create_tracked_contradiction(original)
    annotated = case.store.annotate_tracked_contradiction(
        original.id, status=FindingStatus.DISMISSED, annotated_by="analyst:x",
        annotated_at=NOW, note="benign timezone artifact",
    )

    rediscovered_candidate = _tracked()
    result = case.store.create_tracked_contradiction(rediscovered_candidate)

    assert result == annotated
    assert case.store.get_tracked_contradiction(original.id) == annotated
    case.close()


# -- Store: annotate_tracked_contradiction --------------------------------------


def test_annotate_tracked_contradiction_unknown_id_raises(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    with pytest.raises(ValueError):
        case.store.annotate_tracked_contradiction(
            "nonexistent", status=FindingStatus.REVIEWED, annotated_by="a", annotated_at=NOW,
            note=None,
        )
    case.close()


def test_annotate_tracked_contradiction_rejects_whitespace_only_annotated_by(
    tmp_path: Path,
) -> None:
    case = Case.create(tmp_path / "case")
    original = _tracked()
    case.store.create_tracked_contradiction(original)

    with pytest.raises(ValueError, match="must not be blank"):
        case.store.annotate_tracked_contradiction(
            original.id, status=FindingStatus.DISMISSED, annotated_by="   ",
            annotated_at=NOW, note="should not persist",
        )

    stored = case.store.get_tracked_contradiction(original.id)
    assert stored is not None
    assert stored.status == FindingStatus.OPEN
    assert stored.annotated_by is None
    case.close()


def test_annotate_tracked_contradiction_changes_only_annotation_fields(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    original = _tracked()
    case.store.create_tracked_contradiction(original)

    updated = case.store.annotate_tracked_contradiction(
        original.id, status=FindingStatus.REVIEWED, annotated_by="analyst:y",
        annotated_at=NOW, note="looks like a timezone mixup",
    )

    assert updated.id == original.id
    assert updated.subject_event_id == original.subject_event_id
    assert updated.assertion_ids == original.assertion_ids
    assert updated.status == FindingStatus.REVIEWED
    assert updated.annotated_by == "analyst:y"
    case.close()


def test_annotate_tracked_contradiction_replacement_is_not_archived(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    original = _tracked()
    case.store.create_tracked_contradiction(original)
    case.store.annotate_tracked_contradiction(
        original.id, status=FindingStatus.REVIEWED, annotated_by="analyst:first",
        annotated_at=NOW, note="first note",
    )
    final = case.store.annotate_tracked_contradiction(
        original.id, status=FindingStatus.DISMISSED, annotated_by="analyst:second",
        annotated_at=NOW, note="second note",
    )
    stored = case.store.get_tracked_contradiction(original.id)
    assert stored == final
    assert stored is not None
    assert stored.annotated_by == "analyst:second"
    assert stored.note == "second note"
    case.close()


# -- Store: listing / invalid ids -----------------------------------------------


def test_list_tracked_contradictions_is_ordered_by_id(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    c1 = _tracked(
        id=TrackedTimeContradiction.identity_hash(
            subject_event_id="evt-1", assertion_ids=("a1", "a2")
        ),
        subject_event_id="evt-1", assertion_ids=("a1", "a2"),
    )
    c2 = _tracked(
        id=TrackedTimeContradiction.identity_hash(
            subject_event_id="evt-9", assertion_ids=("b1", "b2")
        ),
        subject_event_id="evt-9", assertion_ids=("b1", "b2"),
    )
    case.store.create_tracked_contradiction(c2)
    case.store.create_tracked_contradiction(c1)
    listed = case.store.list_tracked_contradictions()
    assert [c.id for c in listed] == sorted(c.id for c in [c1, c2])
    case.close()


def test_list_tracked_contradictions_empty_on_fresh_case(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    assert case.store.list_tracked_contradictions() == []
    case.close()


def test_get_tracked_contradiction_unknown_id_returns_none(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    assert case.store.get_tracked_contradiction("nonexistent") is None
    case.close()


# -- Isolation from v0.7 GapFinding tracking -------------------------------------


def test_tracked_contradictions_and_tracked_findings_tables_are_independent(
    tmp_path: Path,
) -> None:
    """Tracking a contradiction must never touch the gap-findings table,
    and vice versa (docs/phase4-v0.4-gap-analysis-design.md §9)."""
    case = Case.create(tmp_path / "case")
    case.store.create_tracked_contradiction(_tracked())
    assert case.store.list_tracked_findings() == []
    assert len(case.store.list_tracked_contradictions()) == 1
    case.close()


# -- tracked_contradiction_to_json ----------------------------------------------


def test_tracked_contradiction_to_json_shape() -> None:
    tracked = _tracked()
    doc = tracked_contradiction_to_json(tracked)
    assert doc == {
        "id": tracked.id,
        "subject_event_id": "evt-1",
        "assertion_ids": ["a1", "a2"],
        "status": "open",
        "annotated_by": None,
        "annotated_at": None,
        "note": None,
    }


def test_tracked_contradiction_to_json_has_no_still_reproduced_field() -> None:
    """Deliberately absent -- see TrackedTimeContradiction's own module
    docstring: it would always read true and convey no information."""
    doc = tracked_contradiction_to_json(_tracked())
    assert "still_reproduced" not in doc


def test_tracked_contradiction_to_json_reflects_annotation() -> None:
    tracked = _tracked().with_annotation(
        status=FindingStatus.REVIEWED, annotated_by="analyst:jane",
        annotated_at=NOW, note="looked into it",
    )
    doc = tracked_contradiction_to_json(tracked)
    assert doc["status"] == "reviewed"
    assert doc["annotated_by"] == "analyst:jane"
    assert doc["note"] == "looked into it"
