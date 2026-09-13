"""Relationship: DESIGN.md principles 1-3 applied to a graph edge.

Mirrors tests/unit/test_time_assertions.py's and the NormalizedEvent
identity tests' style: content-derived id determinism, and the
evidence-backed/lineage validation every derived object type enforces.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from witnessgraph.core.relationships import Relationship

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _create(
    *,
    relationship_type: str = "connected_to",
    source: str = "entity-a",
    target: str = "entity-b",
    derived_from: tuple[str, ...] = ("ev-1",),
    attributes: dict[str, str] | None = None,
    created_at: datetime = NOW,
) -> Relationship:
    return Relationship.create(
        relationship_type=relationship_type,
        source_entity_id=source,
        target_entity_id=target,
        derived_from=derived_from,
        created_at=created_at,
        attributes=attributes,
    )


def test_create_is_deterministic_regardless_of_created_at() -> None:
    a = _create(created_at=NOW)
    b = _create(created_at=NOW.replace(year=2030))
    assert a.id == b.id


def test_create_ids_differ_by_relationship_type() -> None:
    a = _create(relationship_type="connected_to")
    b = _create(relationship_type="authenticated_as")
    assert a.id != b.id


def test_create_ids_differ_by_source_or_target() -> None:
    base = _create(source="entity-a", target="entity-b")
    different_source = _create(source="entity-c", target="entity-b")
    different_target = _create(source="entity-a", target="entity-c")
    assert base.id != different_source.id
    assert base.id != different_target.id
    # Directed -- swapping source/target is a different edge, not the same one.
    swapped = _create(source="entity-b", target="entity-a")
    assert base.id != swapped.id


def test_create_ids_differ_by_derived_from() -> None:
    a = _create(derived_from=("ev-1",))
    b = _create(derived_from=("ev-2",))
    assert a.id != b.id


def test_create_ids_differ_by_attributes() -> None:
    a = _create(attributes={"protocol": "tcp"})
    b = _create(attributes={"protocol": "udp"})
    c = _create(attributes=None)
    assert a.id != b.id
    assert a.id != c.id


def test_identity_hash_matches_create() -> None:
    rel = _create(attributes={"k": "v"})
    expected = Relationship.identity_hash(
        relationship_type="connected_to",
        source_entity_id="entity-a",
        target_entity_id="entity-b",
        attributes={"k": "v"},
        derived_from=("ev-1",),
    )
    assert rel.id == expected


def test_rejects_blank_relationship_type() -> None:
    with pytest.raises(ValidationError):
        _create(relationship_type="   ")


def test_rejects_self_loop() -> None:
    with pytest.raises(ValidationError, match="differ"):
        _create(source="same-entity", target="same-entity")


def test_rejects_empty_derived_from() -> None:
    with pytest.raises(ValidationError):
        _create(derived_from=())


def test_default_attributes_is_empty_dict() -> None:
    rel = _create(attributes=None)
    assert rel.attributes == {}


def test_relationship_is_frozen() -> None:
    rel = _create()
    with pytest.raises(ValidationError):
        rel.relationship_type = "something_else"  # type: ignore[misc]
