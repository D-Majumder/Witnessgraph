"""DESIGN.md principle 5: canonical serialization must be deterministic."""

from __future__ import annotations

import string
from datetime import UTC, datetime, timedelta, timezone

from hypothesis import given
from hypothesis import strategies as st

from witnessgraph.core.ids import canonical_json_bytes, content_hash


def test_key_order_does_not_affect_output() -> None:
    a = {"b": 1, "a": 2, "c": 3}
    b = {"c": 3, "a": 2, "b": 1}
    assert canonical_json_bytes(a) == canonical_json_bytes(b)


def test_output_is_deterministic_across_calls() -> None:
    value = {"x": [1, 2, 3], "y": {"nested": True}}
    assert canonical_json_bytes(value) == canonical_json_bytes(value)


def test_datetime_is_normalized_to_utc() -> None:
    """Two datetimes naming the same instant, in different (but both aware)
    timezones, must serialize identically -- see canonical_json_bytes'
    docstring. (Python's own datetime equality already treats these as
    equal instants; what we're actually verifying here is that the
    *serialized bytes* -- not just Python equality -- agree too.)
    """
    utc_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    other_tz = utc_time.astimezone(timezone(timedelta(hours=5)))
    assert canonical_json_bytes({"t": utc_time}) == canonical_json_bytes({"t": other_tz})


def test_naive_datetime_is_rejected() -> None:
    import pytest

    naive = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError):
        canonical_json_bytes({"t": naive})


def test_content_hash_changes_with_content() -> None:
    h1 = content_hash({"a": 1})
    h2 = content_hash({"a": 2})
    assert h1 != h2


def test_content_hash_stable_for_identical_content() -> None:
    assert content_hash({"a": 1, "b": [1, 2]}) == content_hash({"b": [1, 2], "a": 1})


@given(
    st.dictionaries(
        keys=st.text(min_size=1, max_size=10, alphabet=string.ascii_lowercase),
        values=st.one_of(st.integers(), st.text(max_size=20), st.booleans(), st.none()),
        max_size=8,
    )
)
def test_canonical_json_is_order_independent_property(d: dict[str, object]) -> None:
    items = list(d.items())
    shuffled = dict(reversed(items))
    assert canonical_json_bytes(d) == canonical_json_bytes(shuffled)
