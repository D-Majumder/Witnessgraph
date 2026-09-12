"""docs/phase3-v0.3-design.md §7/§15: deterministic, content-addressed identity
for NormalizedEvent and TimeAssertion.

Covers: same logical object -> same id, across repeated calls and across
independently-constructed objects (including a simulated separate-process
call, since these are pure functions of their inputs with no shared
in-process state); dictionary-insertion-order independence; created_at
exclusion; domain separation between the two types; lineage-anchored
distinctness (two events/assertions derived from different evidence stay
distinct even with identical other fields); and a property-based version
of the same determinism claim.
"""

from __future__ import annotations

import string
import subprocess
import sys
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.time_model import TimeAssertion, TimePrecision

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 6, 1, tzinfo=UTC)


# -- NormalizedEvent ---------------------------------------------------


def test_same_logical_event_same_id() -> None:
    a = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",), created_at=NOW
    )
    b = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",), created_at=NOW
    )
    assert a.id == b.id


def test_normalized_event_id_ignores_created_at() -> None:
    a = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",), created_at=NOW
    )
    b = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",), created_at=LATER
    )
    assert a.id == b.id


def test_normalized_event_id_ignores_attribute_dict_insertion_order() -> None:
    a = NormalizedEvent.create(
        event_type="logon",
        attributes={"user": "alice", "host": "ws1"},
        derived_from=("ev-1",),
        created_at=NOW,
    )
    b = NormalizedEvent.create(
        event_type="logon",
        attributes={"host": "ws1", "user": "alice"},
        derived_from=("ev-1",),
        created_at=NOW,
    )
    assert a.id == b.id


def test_normalized_event_id_changes_with_event_type() -> None:
    a = NormalizedEvent.create(event_type="logon", derived_from=("ev-1",), created_at=NOW)
    b = NormalizedEvent.create(event_type="logoff", derived_from=("ev-1",), created_at=NOW)
    assert a.id != b.id


def test_normalized_event_id_changes_with_attributes() -> None:
    a = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",), created_at=NOW
    )
    b = NormalizedEvent.create(
        event_type="logon", attributes={"user": "bob"}, derived_from=("ev-1",), created_at=NOW
    )
    assert a.id != b.id


def test_normalized_event_id_changes_with_derived_from_lineage() -> None:
    """Two events with identical event_type/attributes but different evidentiary
    lineage remain distinct -- identity is anchored to lineage, not just
    superficial content (docs/phase3-v0.3-design.md §7/§21.4)."""
    a = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",), created_at=NOW
    )
    b = NormalizedEvent.create(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-2",), created_at=NOW
    )
    assert a.id != b.id


def test_normalized_event_id_is_a_pure_function_across_subprocess() -> None:
    """Separate-process determinism: an id computed by this process must equal
    one computed by a freshly started Python process with no shared state
    (rules out any accidental dependence on PYTHONHASHSEED, process-local
    caches, or object identity)."""
    in_process = NormalizedEvent.identity_hash(
        event_type="logon", attributes={"user": "alice", "host": "ws1"}, derived_from=("ev-1",)
    )
    script = (
        "from witnessgraph.core.events import NormalizedEvent; "
        "print(NormalizedEvent.identity_hash("
        "event_type='logon', attributes={'host': 'ws1', 'user': 'alice'}, "
        "derived_from=('ev-1',)))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == in_process


# -- TimeAssertion -------------------------------------------------------


def test_same_logical_assertion_same_id() -> None:
    a = TimeAssertion.create(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    b = TimeAssertion.create(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    assert a.id == b.id


def test_time_assertion_id_ignores_created_at() -> None:
    a = TimeAssertion.create(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    b = TimeAssertion.create(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=LATER,
    )
    assert a.id == b.id


def test_time_assertion_id_changes_with_value() -> None:
    a = TimeAssertion.create(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    b = TimeAssertion.create(
        subject_event_id="evt-1",
        value=LATER,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    assert a.id != b.id


def test_time_assertion_id_changes_with_subject_event() -> None:
    a = TimeAssertion.create(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    b = TimeAssertion.create(
        subject_event_id="evt-2",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    assert a.id != b.id


# -- Domain separation ---------------------------------------------------


def test_normalized_event_and_time_assertion_never_collide_even_with_similar_fields() -> None:
    """A deliberately adversarial case: construct field sets for each type
    that would canonicalize near-identically but for the _type tag."""
    event_id = NormalizedEvent.identity_hash(
        event_type="x", attributes={"a": "1"}, derived_from=("shared-id",)
    )
    assertion_id = TimeAssertion.identity_hash(
        subject_event_id="shared-id",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="shared-id",
        asserted_by="x",
    )
    assert event_id != assertion_id


# -- Compatibility: bare constructor still yields random ids -------------


def test_bare_constructor_still_generates_random_id_for_legacy_objects() -> None:
    """The plain constructor (as used by v0.1/v0.2-era code and by every
    existing hand-built test fixture) keeps generating a fresh random id,
    so existing UUID-based objects/fixtures remain constructible and
    readable exactly as before -- v0.3 does not force every call site to
    switch to .create()."""
    a = NormalizedEvent(event_type="logon", derived_from=("ev-1",), created_at=NOW)
    b = NormalizedEvent(event_type="logon", derived_from=("ev-1",), created_at=NOW)
    assert a.id != b.id  # random, not content-derived

    ta = TimeAssertion(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="x",
        created_at=NOW,
    )
    tb = TimeAssertion(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="x",
        created_at=NOW,
    )
    assert ta.id != tb.id


# -- Property-based determinism -------------------------------------------


_attr_strategy = st.dictionaries(
    keys=st.text(min_size=1, max_size=8, alphabet=string.ascii_lowercase),
    values=st.text(max_size=16, alphabet=string.ascii_lowercase),
    max_size=5,
)


@given(
    event_type=st.text(min_size=1, max_size=10, alphabet=string.ascii_lowercase),
    attrs=_attr_strategy,
)
def test_normalized_event_identity_is_deterministic_property(
    event_type: str, attrs: dict[str, str]
) -> None:
    a = NormalizedEvent.create(
        event_type=event_type, attributes=attrs, derived_from=("ev-1",), created_at=NOW
    )
    b = NormalizedEvent.create(
        event_type=event_type, attributes=dict(reversed(list(attrs.items()))),
        derived_from=("ev-1",), created_at=LATER,
    )
    assert a.id == b.id


@given(event_type=st.text(min_size=1, max_size=10, alphabet=string.ascii_lowercase))
def test_normalized_event_identity_changes_with_event_type_property(event_type: str) -> None:
    other_type = event_type + "_x"
    a = NormalizedEvent.create(event_type=event_type, derived_from=("ev-1",), created_at=NOW)
    b = NormalizedEvent.create(event_type=other_type, derived_from=("ev-1",), created_at=NOW)
    assert a.id != b.id
