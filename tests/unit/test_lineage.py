"""DESIGN.md principle 2: every derived object has explicit, validated lineage."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def test_normalized_event_requires_lineage() -> None:
    with pytest.raises(ValidationError):
        NormalizedEvent(event_type="logon", derived_from=(), created_at=NOW)


def test_normalized_event_with_lineage_is_valid() -> None:
    event = NormalizedEvent(event_type="logon", derived_from=("abc123",), created_at=NOW)
    assert event.derived_from == ("abc123",)


def test_normalized_event_rejects_blank_event_type() -> None:
    with pytest.raises(ValidationError):
        NormalizedEvent(event_type="   ", derived_from=("abc123",), created_at=NOW)


def test_entity_requires_lineage() -> None:
    with pytest.raises(ValidationError):
        Entity(entity_type="host", derived_from=())


def test_entity_with_lineage_is_valid() -> None:
    entity = Entity(entity_type="host", derived_from=("evt-1", "evt-2"))
    assert entity.derived_from == ("evt-1", "evt-2")
