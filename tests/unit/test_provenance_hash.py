"""DESIGN.md principle 5: the manifest hash changes iff case content changes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from witnessgraph.core.evidence import EvidenceItem, ProvenanceRecord
from witnessgraph.core.provenance import compute_manifest
from witnessgraph.store.case import Case

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _make_evidence(raw: bytes) -> EvidenceItem:
    return EvidenceItem.create(
        raw_bytes=raw,
        source_adapter="test",
        adapter_version="0.0.0",
        source_locator="memory://test",
        collected_at=NOW,
    )


def test_manifest_hash_unchanged_for_empty_case(tmp_path: Path) -> None:
    case_a = Case.create(tmp_path / "a")
    case_b = Case.create(tmp_path / "b")
    hash_a = compute_manifest(case_a.store).manifest_hash
    hash_b = compute_manifest(case_b.store).manifest_hash
    assert hash_a == hash_b
    case_a.close()
    case_b.close()


def test_manifest_hash_changes_when_evidence_added(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    before = compute_manifest(case.store).manifest_hash
    case.store.put_evidence(_make_evidence(b"new evidence"))
    after = compute_manifest(case.store).manifest_hash
    assert before != after
    case.close()


def test_manifest_hash_stable_across_recomputation(tmp_path: Path) -> None:
    case = Case.create(tmp_path / "case")
    case.store.put_evidence(_make_evidence(b"some evidence"))
    h1 = compute_manifest(case.store).manifest_hash
    h2 = compute_manifest(case.store).manifest_hash
    assert h1 == h2
    case.close()


def test_manifest_hash_unaffected_by_custody_record_growth(tmp_path: Path) -> None:
    """Appending a custody record must never change the manifest hash.

    This is the property that makes export/import reproducibility
    possible even if custody metadata grows -- see EvidenceItem's
    docstring and DESIGN.md principle 4.
    """
    case = Case.create(tmp_path / "case")
    item = _make_evidence(b"tracked evidence")
    case.store.put_evidence(item)
    before = compute_manifest(case.store).manifest_hash

    with_custody = item.with_custody_record(
        ProvenanceRecord(actor="system", action="exported", timestamp=NOW)
    )
    case.store.put_evidence(with_custody)
    after = compute_manifest(case.store).manifest_hash

    assert before == after


def test_manifest_hash_independent_of_insertion_order(tmp_path: Path) -> None:
    case_a = Case.create(tmp_path / "a")
    case_b = Case.create(tmp_path / "b")
    e1, e2 = _make_evidence(b"first"), _make_evidence(b"second")

    case_a.store.put_evidence(e1)
    case_a.store.put_evidence(e2)

    case_b.store.put_evidence(e2)
    case_b.store.put_evidence(e1)

    hash_a = compute_manifest(case_a.store).manifest_hash
    hash_b = compute_manifest(case_b.store).manifest_hash
    assert hash_a == hash_b
    case_a.close()
    case_b.close()
