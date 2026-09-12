"""docs/phase3-v0.3-design.md §7/§21.6 + the post-implementation adversarial
review: NormalizedEvent id-collision safety.

Content-addressing guarantees event_type/attributes/derived_from already
match on an id collision -- but entity_ids is deliberately excluded from
identity, so a real conflict on that field (or, in principle, a
constructed id collision with otherwise-different content) must never be
silently discarded or silently merged. put_normalized_event() must raise
NormalizedEventConflictError in that case, and do so safely inside an
active SqliteStore.transaction() block (triggering a full rollback, not
a partial write).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.store.case import Case
from witnessgraph.store.sqlite_store import NormalizedEventConflictError

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 6, 1, tzinfo=UTC)


def _evidence(tmp_path: Path) -> EvidenceItem:
    return EvidenceItem.create(
        raw_bytes=b"payload",
        source_adapter="test",
        adapter_version="0.0.0",
        source_locator=str(tmp_path),
        collected_at=NOW,
    )


def test_identical_retry_remains_a_no_op(tmp_path: Path) -> None:
    """The ordinary, expected case: re-deriving the exact same logical event
    (even at a different wall-clock time) is a safe no-op, not a conflict."""
    case = Case.create(tmp_path / "case")
    ev = _evidence(tmp_path)
    case.store.put_evidence(ev)

    a = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=(ev.id,), created_at=NOW
    )
    b = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=(ev.id,), created_at=LATER
    )
    assert a.id == b.id

    case.store.put_normalized_event(a)
    case.store.put_normalized_event(b)  # must not raise

    assert len(case.store.list_normalized_events()) == 1
    stored = case.store.get_normalized_event(a.id)
    assert stored is not None
    assert stored.created_at == NOW  # first-write-wins, unchanged from before this fix
    case.close()


def test_same_id_different_entity_ids_raises(tmp_path: Path) -> None:
    """entity_ids is excluded from identity, so two events with the same id
    but different entity_ids are a genuine conflict, not a mergeable pair."""
    case = Case.create(tmp_path / "case")
    ev = _evidence(tmp_path)
    case.store.put_evidence(ev)

    a = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=(ev.id,), created_at=NOW
    )
    case.store.put_normalized_event(a)

    # Same id (bare constructor, bypassing .create() to force the collision
    # deliberately -- entity_ids alone differs).
    conflicting = NormalizedEvent(
        id=a.id,
        event_type=a.event_type,
        attributes=a.attributes,
        derived_from=a.derived_from,
        entity_ids=("some-entity",),
        created_at=NOW,
    )
    with pytest.raises(NormalizedEventConflictError) as excinfo:
        case.store.put_normalized_event(conflicting)
    assert excinfo.value.event_id == a.id

    # The conflicting write must not have landed.
    stored = case.store.get_normalized_event(a.id)
    assert stored is not None
    assert stored.entity_ids == ()
    assert len(case.store.list_normalized_events()) == 1
    case.close()


def test_same_id_different_attributes_raises(tmp_path: Path) -> None:
    """A constructed id collision (bare constructor, simulating either a
    hash collision or a corrupted/adversarial input) where event_type,
    attributes, and derived_from all differ from the stored record must
    also raise -- not just the entity_ids case."""
    case = Case.create(tmp_path / "case")
    ev = _evidence(tmp_path)
    case.store.put_evidence(ev)

    fixed_id = "f" * 64
    a = NormalizedEvent(
        id=fixed_id,
        event_type="logon",
        attributes={"user": "alice"},
        derived_from=(ev.id,),
        created_at=NOW,
    )
    case.store.put_normalized_event(a)

    b = NormalizedEvent(
        id=fixed_id,  # same id
        event_type="logoff",  # materially different content
        attributes={"user": "bob"},
        derived_from=(ev.id,),
        created_at=NOW,
    )
    with pytest.raises(NormalizedEventConflictError):
        case.store.put_normalized_event(b)

    stored = case.store.get_normalized_event(fixed_id)
    assert stored is not None
    assert stored.event_type == "logon"  # untouched
    case.close()


def test_conflict_rolls_back_the_whole_transaction(tmp_path: Path) -> None:
    """A conflict raised inside an active transaction() block must trigger a
    full rollback of everything else written in that same block -- not just
    abort the one conflicting write."""
    case = Case.create(tmp_path / "case")
    ev = _evidence(tmp_path)
    case.store.put_evidence(ev)

    a = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=(ev.id,), created_at=NOW
    )
    case.store.put_normalized_event(a)

    other_evidence = EvidenceItem.create(
        raw_bytes=b"other payload",
        source_adapter="test",
        adapter_version="0.0.0",
        source_locator="other",
        collected_at=NOW,
    )
    conflicting = NormalizedEvent(
        id=a.id,
        event_type=a.event_type,
        attributes=a.attributes,
        derived_from=a.derived_from,
        entity_ids=("conflict-entity",),
        created_at=NOW,
    )

    with pytest.raises(NormalizedEventConflictError):
        with case.transaction():
            case.store.put_evidence(other_evidence)  # would-be new write in the same batch
            case.store.put_normalized_event(conflicting)  # raises

    # The evidence write from the same failed transaction did not survive.
    assert case.store.get_evidence(other_evidence.id) is None
    # The original, pre-conflict normalized event is untouched.
    stored = case.store.get_normalized_event(a.id)
    assert stored is not None
    assert stored.entity_ids == ()
    case.close()


def test_existing_valid_reingest_behavior_is_unchanged(tmp_path: Path) -> None:
    """Regression guard: ordinary re-ingestion of unmodified content across
    multiple calls remains exactly as idempotent as before this fix."""
    case = Case.create(tmp_path / "case")
    ev = _evidence(tmp_path)
    case.store.put_evidence(ev)

    event = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=(ev.id,), created_at=NOW
    )
    for _ in range(3):
        case.store.put_normalized_event(event)

    assert len(case.store.list_normalized_events()) == 1
    case.close()
