"""docs/phase4-v0.4-source-identity-design.md: explicit, analyst-declared
source identity (ProvenanceRecord.source_id).

Covers: default/explicit storage, declared_source_ids() resolution
(including the ambiguous multi-source case), repeated-ingestion
idempotence, legacy compatibility, validation rules (empty/whitespace/
length/control-bidi-zero-width rejection, Unicode/path-like acceptance,
case sensitivity), and non-interference with EvidenceItem/NormalizedEvent/
TimeAssertion identity and manifest hashing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import (
    MAX_SOURCE_ID_LENGTH,
    EvidenceItem,
    ProvenanceRecord,
    validate_source_id,
)
from witnessgraph.core.provenance import compute_manifest
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _evidence(raw: bytes, locator: str, source_id: str | None = None) -> EvidenceItem:
    return EvidenceItem.create(
        raw_bytes=raw,
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator=locator,
        collected_at=NOW,
        source_id=source_id,
    )


# -- Default / explicit storage -------------------------------------------


def test_source_id_defaults_to_none() -> None:
    item = _evidence(b"payload", "file.jsonl:1")
    assert item.chain_of_custody[0].source_id is None
    assert item.declared_source_ids() == frozenset()


def test_source_id_explicit_stored_verbatim() -> None:
    item = _evidence(b"payload", "file.jsonl:1", source_id="host1")
    assert item.chain_of_custody[0].source_id == "host1"
    assert item.declared_source_ids() == frozenset({"host1"})


def test_declared_source_ids_ambiguous_when_two_sources_share_bytes(tmp_path: Path) -> None:
    """The exact scenario docs/phase4-v0.4-source-identity-design.md §2 identifies:
    byte-identical content declared under two different source_ids merges
    into one EvidenceItem whose declared_source_ids() is ambiguous (both
    values present), never silently one or the other."""
    case = Case.create(tmp_path / "case")
    first = _evidence(b"identical payload", "file1.jsonl:1", source_id="host1")
    second = _evidence(b"identical payload", "file2.jsonl:1", source_id="host2")
    case.store.put_evidence(first)
    case.store.put_evidence(second)

    stored = case.store.get_evidence(first.id)
    assert stored is not None
    assert stored.id == first.id == second.id  # content-addressed identity unchanged
    assert stored.declared_source_ids() == frozenset({"host1", "host2"})
    case.close()


# -- Repeated ingestion / idempotence ---------------------------------------


def test_same_source_id_repeated_ingestion_is_idempotent(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")

    def make() -> EvidenceItem:
        return _evidence(b"same content, same source", "file1.jsonl:1", source_id="host1")

    case.store.put_evidence(make())
    case.store.put_evidence(make())
    case.store.put_evidence(make())

    stored = case.store.get_evidence(make().id)
    assert stored is not None
    assert len(stored.chain_of_custody) == 1  # identical custody record, no growth
    assert stored.declared_source_ids() == frozenset({"host1"})
    case.close()


def test_different_hosts_same_adapter_remain_distinguishable(tmp_path: Path) -> None:
    """The exact adversarial example docs/phase4-v0.4-gap-analysis-design.md
    §6.4 showed was structurally impossible before this milestone."""
    case = Case.create(tmp_path / "case")
    host1_evidence = _evidence(b"host1 line", "host1.jsonl:1", source_id="host1")
    host2_evidence = _evidence(b"host2 line", "host2.jsonl:1", source_id="host2")
    case.store.put_evidence(host1_evidence)
    case.store.put_evidence(host2_evidence)

    items = {e.id: e for e in case.store.list_evidence()}
    assert items[host1_evidence.id].declared_source_ids() == frozenset({"host1"})
    assert items[host2_evidence.id].declared_source_ids() == frozenset({"host2"})
    case.close()


# -- Legacy compatibility ---------------------------------------------------


def test_legacy_json_without_source_id_key_loads_as_none() -> None:
    """A ProvenanceRecord JSON blob genuinely predating this field (no
    source_id key at all, not source_id: null) must parse via the
    Pydantic default -- mirrors ProvenanceManifest.manifest_version's
    proven v0.3 precedent."""
    legacy_json = json.dumps(
        {
            "actor": "adapter:jsonl@0.1.0",
            "action": "ingested",
            "timestamp": "2026-01-01T00:00:00Z",
            "source_locator": "legacy.jsonl:1",
        }
    )
    record = ProvenanceRecord.model_validate_json(legacy_json)
    assert record.source_id is None


def test_legacy_evidence_item_declared_source_ids_is_empty() -> None:
    legacy_json = json.dumps(
        {
            "id": "a" * 64,
            "source_adapter": "jsonl",
            "adapter_version": "0.1.0",
            "source_locator": "legacy.jsonl:1",
            "raw_content_hash": "a" * 64,
            "raw_size_bytes": 7,
            "collected_at": "2026-01-01T00:00:00Z",
            "chain_of_custody": [
                {
                    "actor": "adapter:jsonl@0.1.0",
                    "action": "ingested",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "source_locator": "legacy.jsonl:1",
                }
            ],
        }
    )
    item = EvidenceItem.model_validate_json(legacy_json)
    assert item.declared_source_ids() == frozenset()


# -- Validation --------------------------------------------------------------


def test_validate_source_id_accepts_plain_string() -> None:
    validate_source_id("host1")  # must not raise


def test_validate_source_id_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="empty string"):
        validate_source_id("")


@pytest.mark.parametrize("bad", [" host1", "host1 ", " host1 ", "   "])
def test_validate_source_id_rejects_whitespace(bad: str) -> None:
    with pytest.raises(ValueError, match="whitespace"):
        validate_source_id(bad)


def test_validate_source_id_rejects_too_long() -> None:
    with pytest.raises(ValueError, match="at most"):
        validate_source_id("x" * (MAX_SOURCE_ID_LENGTH + 1))


def test_validate_source_id_accepts_max_length() -> None:
    validate_source_id("x" * MAX_SOURCE_ID_LENGTH)  # must not raise


@pytest.mark.parametrize(
    "bad_char",
    [
        "\u200b",  # zero-width space
        "\u202e",  # RLO bidi control
        "\x01",  # C0 control
        "\x7f",  # DEL
    ],
)
def test_validate_source_id_rejects_control_bidi_zero_width(bad_char: str) -> None:
    with pytest.raises(ValueError, match="control, bidi, or zero-width"):
        validate_source_id(f"host{bad_char}1")


def test_validate_source_id_accepts_ordinary_unicode() -> None:
    validate_source_id("hôte-1")  # accented Unicode, not in the forbidden set


def test_validate_source_id_accepts_path_like_string() -> None:
    validate_source_id("logs/host1")  # never interpreted as a filesystem path


def test_provenance_record_construction_enforces_validation() -> None:
    """The field validator on ProvenanceRecord itself, not just the
    standalone helper -- no construction path can bypass it."""
    with pytest.raises(ValidationError):
        ProvenanceRecord(
            actor="x", action="ingested", timestamp=NOW, source_id=""
        )


def test_case_sensitivity_produces_distinct_source_ids(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    upper = _evidence(b"one", "a.jsonl:1", source_id="Host1")
    lower = _evidence(b"two", "b.jsonl:1", source_id="host1")
    case.store.put_evidence(upper)
    case.store.put_evidence(lower)
    assert case.store.get_evidence(upper.id).declared_source_ids() == frozenset({"Host1"})  # type: ignore[union-attr]
    assert case.store.get_evidence(lower.id).declared_source_ids() == frozenset({"host1"})  # type: ignore[union-attr]
    case.close()


def test_duplicate_source_id_across_many_records_is_not_an_error(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    for i in range(5):
        case.store.put_evidence(_evidence(f"line {i}".encode(), f"f.jsonl:{i}", source_id="host1"))
    assert len(case.store.list_evidence()) == 5
    for item in case.store.list_evidence():
        assert item.declared_source_ids() == frozenset({"host1"})
    case.close()


# -- Non-interference with existing identity/manifest -----------------------


def test_source_id_does_not_affect_evidence_item_id() -> None:
    a = _evidence(b"same bytes", "loc-a", source_id="host1")
    b = _evidence(b"same bytes", "loc-b", source_id="host2")
    assert a.id == b.id  # content-addressed identity is bytes-only, unaffected


def test_source_id_does_not_affect_normalized_event_identity() -> None:
    id_without = NormalizedEvent.identity_hash(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",)
    )
    # NormalizedEvent.identity_hash has no source_id parameter at all --
    # confirm the hash is identical regardless of what EvidenceItem it's
    # nominally about declared as its source (source_id is not an input).
    id_again = NormalizedEvent.identity_hash(
        event_type="logon", attributes={"user": "alice"}, derived_from=("ev-1",)
    )
    assert id_without == id_again


def test_source_id_does_not_affect_time_assertion_identity() -> None:
    id_a = TimeAssertion.identity_hash(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
    )
    id_b = TimeAssertion.identity_hash(
        subject_event_id="evt-1",
        value=NOW,
        precision=TimePrecision.SECOND,
        source_evidence_id="ev-1",
        asserted_by="adapter:jsonl",
    )
    assert id_a == id_b  # no source_id parameter exists to vary


def test_manifest_hash_unaffected_by_declared_source_id(tmp_path: Path) -> None:
    """The central determinism claim of the design doc's §7/§11: declaring
    (or not declaring) a source_id must not change the manifest hash."""
    case_a = Case.create(tmp_path / "a")
    case_a.store.put_evidence(_evidence(b"tracked evidence", "loc", source_id=None))
    hash_a = compute_manifest(case_a.store).manifest_hash

    case_b = Case.create(tmp_path / "b")
    case_b.store.put_evidence(_evidence(b"tracked evidence", "loc", source_id="host1"))
    hash_b = compute_manifest(case_b.store).manifest_hash

    assert hash_a == hash_b
    case_a.close()
    case_b.close()
