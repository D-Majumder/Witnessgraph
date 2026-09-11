"""DESIGN.md principle 1: Evidence is immutable."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from witnessgraph.core.evidence import EvidenceItem, ProvenanceRecord

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make(raw: bytes = b"hello world") -> EvidenceItem:
    return EvidenceItem.create(
        raw_bytes=raw,
        source_adapter="test",
        adapter_version="0.0.0",
        source_locator="memory://test",
        collected_at=NOW,
    )


def test_id_equals_content_hash() -> None:
    import hashlib

    item = _make(b"hello world")
    assert item.id == hashlib.sha256(b"hello world").hexdigest()
    assert item.raw_content_hash == item.id


def test_same_bytes_produce_same_id() -> None:
    a = _make(b"identical bytes")
    b = _make(b"identical bytes")
    assert a.id == b.id


def test_different_bytes_produce_different_id() -> None:
    a = _make(b"one")
    b = _make(b"two")
    assert a.id != b.id


def test_model_is_frozen() -> None:
    item = _make()
    with pytest.raises(ValidationError):
        item.source_locator = "somewhere else"


def test_id_must_match_raw_content_hash() -> None:
    with pytest.raises(ValidationError):
        EvidenceItem(
            id="0" * 64,
            source_adapter="test",
            adapter_version="0.0.0",
            source_locator="x",
            raw_content_hash="1" * 64,
            raw_size_bytes=0,
            collected_at=NOW,
        )


def test_with_custody_record_does_not_mutate_original() -> None:
    original = _make()
    record = ProvenanceRecord(actor="analyst:bob", action="exported", timestamp=NOW)
    updated = original.with_custody_record(record)

    assert original.chain_of_custody != updated.chain_of_custody
    assert len(original.chain_of_custody) == 1
    assert len(updated.chain_of_custody) == 2
    # content identity is unaffected by a custody record
    assert original.id == updated.id
    assert original.raw_content_hash == updated.raw_content_hash
