"""Unit tests for witnessgraph.casepkg: schema parsing, package resolution
(build.py), and validation, all in-memory -- no filesystem, no Case."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from witnessgraph.casepkg.build import build_case_contents
from witnessgraph.casepkg.demo import build_demo_case_package
from witnessgraph.casepkg.schema import (
    CASE_PACKAGE_SCHEMA_VERSION,
    CaseMetadata,
    CasePackage,
    DeclaredEntity,
    DeclaredEvidenceItem,
    DeclaredEvidenceRef,
    DeclaredHypothesis,
    DeclaredNormalizedEvent,
    DeclaredRelationship,
    DeclaredTimeAssertion,
)
from witnessgraph.casepkg.validate import validate_package_bytes
from witnessgraph.core.hypothesis import HypothesisStatus
from witnessgraph.core.time_model import TimePrecision

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _minimal_metadata() -> CaseMetadata:
    return CaseMetadata(title="t", created_by="tester", created_at=NOW)


def test_demo_package_is_valid() -> None:
    result = build_case_contents(build_demo_case_package())
    assert result.is_valid
    assert result.contents is not None
    assert len(result.contents.evidence) == 1
    assert len(result.contents.entities) == 2
    assert len(result.contents.relationships) == 1


def test_evidence_id_is_content_derived_not_researcher_supplied() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="hello world", source_locator="x:1", collected_at=NOW
            ),
        ),
    )
    result = build_case_contents(package)
    assert result.is_valid and result.contents is not None
    item, raw = result.contents.evidence[0]
    assert raw == b"hello world"
    assert item.id == item.raw_content_hash
    # Never equal to the researcher's own local_id -- it is a content hash.
    assert item.id != "ev-1"


def test_two_evidence_items_with_identical_content_converge_to_same_id() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="same bytes", source_locator="a:1", collected_at=NOW
            ),
            DeclaredEvidenceItem(
                local_id="ev-2", content="same bytes", source_locator="b:1", collected_at=NOW
            ),
        ),
    )
    result = build_case_contents(package)
    assert result.is_valid and result.contents is not None
    (item1, _), (item2, _) = result.contents.evidence
    assert item1.id == item2.id


def test_entity_local_id_becomes_the_real_entity_id() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="x", source_locator="a:1", collected_at=NOW
            ),
        ),
        entities=(
            DeclaredEntity(local_id="my-entity", entity_type="host", derived_from=("ev-1",)),
        ),
    )
    result = build_case_contents(package)
    assert result.is_valid and result.contents is not None
    assert result.contents.entities[0].id == "my-entity"


def test_dangling_derived_from_is_rejected_not_repaired() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        entities=(
            DeclaredEntity(local_id="e1", entity_type="host", derived_from=("nonexistent",)),
        ),
    )
    result = build_case_contents(package)
    assert not result.is_valid
    assert result.contents is None
    assert any("nonexistent" in str(e) for e in result.errors)


def test_dangling_relationship_entity_reference_is_rejected() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="x", source_locator="a:1", collected_at=NOW
            ),
        ),
        entities=(
            DeclaredEntity(local_id="e1", entity_type="host", derived_from=("ev-1",)),
        ),
        relationships=(
            DeclaredRelationship(
                relationship_type="connected_to",
                source_entity="e1",
                target_entity="does-not-exist",
                derived_from=("ev-1",),
                created_at=NOW,
            ),
        ),
    )
    result = build_case_contents(package)
    assert not result.is_valid
    assert any("does-not-exist" in str(e) for e in result.errors)


def test_duplicate_local_id_across_kinds_is_rejected() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="dup", content="x", source_locator="a:1", collected_at=NOW
            ),
        ),
        entities=(
            DeclaredEntity(local_id="dup", entity_type="host", derived_from=("dup",)),
        ),
    )
    result = build_case_contents(package)
    assert not result.is_valid
    assert any("duplicate local_id" in str(e) for e in result.errors)


def test_relationship_self_loop_is_rejected_by_core_validation() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="x", source_locator="a:1", collected_at=NOW
            ),
        ),
        entities=(
            DeclaredEntity(local_id="e1", entity_type="host", derived_from=("ev-1",)),
        ),
        relationships=(
            DeclaredRelationship(
                relationship_type="connected_to",
                source_entity="e1",
                target_entity="e1",
                derived_from=("ev-1",),
                created_at=NOW,
            ),
        ),
    )
    result = build_case_contents(package)
    assert not result.is_valid


def test_hypothesis_requires_at_least_one_evidence_ref() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        hypotheses=(
            DeclaredHypothesis(statement="a claim", inferred_by="researcher:x", created_at=NOW),
        ),
    )
    result = build_case_contents(package)
    assert not result.is_valid


def test_hypothesis_evidence_ref_resolves_to_real_evidence_id() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="x", source_locator="a:1", collected_at=NOW
            ),
        ),
        hypotheses=(
            DeclaredHypothesis(
                statement="a claim",
                inferred_by="researcher:x",
                created_at=NOW,
                supporting_evidence=(DeclaredEvidenceRef(kind="evidence_item", local_id="ev-1"),),
            ),
        ),
    )
    result = build_case_contents(package)
    assert result.is_valid and result.contents is not None
    hyp = result.contents.hypotheses[0]
    real_evidence_id = result.contents.evidence[0][0].id
    assert hyp.supporting_evidence[0].id == real_evidence_id


def test_time_assertion_resolves_subject_event_and_source_evidence() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="x", source_locator="a:1", collected_at=NOW
            ),
        ),
        normalized_events=(
            DeclaredNormalizedEvent(
                local_id="ne-1", event_type="login", derived_from=("ev-1",), created_at=NOW
            ),
        ),
        time_assertions=(
            DeclaredTimeAssertion(
                subject_event="ne-1",
                value=NOW,
                precision=TimePrecision.SECOND,
                source_evidence="ev-1",
                asserted_by="researcher:x",
                created_at=NOW,
            ),
        ),
    )
    result = build_case_contents(package)
    assert result.is_valid and result.contents is not None


def test_evidence_item_requires_exactly_one_content_field() -> None:
    with pytest.raises(ValidationError):
        DeclaredEvidenceItem(local_id="e1", source_locator="a:1", collected_at=NOW)
    with pytest.raises(ValidationError):
        DeclaredEvidenceItem(
            local_id="e1",
            content="x",
            content_base64="eA==",
            source_locator="a:1",
            collected_at=NOW,
        )


def test_evidence_item_accepts_base64_content() -> None:
    import base64

    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1",
                content_base64=base64.b64encode(b"\x00\x01binary").decode("ascii"),
                source_locator="a:1",
                collected_at=NOW,
            ),
        ),
    )
    result = build_case_contents(package)
    assert result.is_valid and result.contents is not None
    _item, raw = result.contents.evidence[0]
    assert raw == b"\x00\x01binary"


def test_invalid_base64_is_rejected() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1",
                content_base64="not-valid-base64!!!",
                source_locator="a:1",
                collected_at=NOW,
            ),
        ),
    )
    result = build_case_contents(package)
    assert not result.is_valid


def test_unsupported_schema_version_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CasePackage(
            schema_version=CASE_PACKAGE_SCHEMA_VERSION + 999,
            package_version="1.0",
            case_metadata=_minimal_metadata(),
        )


def test_unknown_top_level_field_is_rejected() -> None:
    """findings/contradictions/gaps are system-derived, never importable -- see
    casepkg/__init__.py's module docstring."""
    raw = (
        b'{"schema_version": 1, "package_version": "1.0", '
        b'"case_metadata": {"title": "t", "created_by": "x", '
        b'"created_at": "2026-01-01T00:00:00Z"}, "findings": []}'
    )
    report = validate_package_bytes(raw)
    assert not report.is_valid
    assert any("findings" in msg for msg in report.all_messages())


def test_validate_package_bytes_never_raises_on_malformed_json() -> None:
    report = validate_package_bytes(b"not json at all")
    assert not report.is_valid
    assert report.package is None


def test_hypothesis_status_round_trips() -> None:
    package = CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version="1.0",
        case_metadata=_minimal_metadata(),
        evidence_items=(
            DeclaredEvidenceItem(
                local_id="ev-1", content="x", source_locator="a:1", collected_at=NOW
            ),
        ),
        hypotheses=(
            DeclaredHypothesis(
                statement="a claim",
                status=HypothesisStatus.SUPPORTED,
                inferred_by="researcher:x",
                created_at=NOW,
                supporting_evidence=(DeclaredEvidenceRef(kind="evidence_item", local_id="ev-1"),),
            ),
        ),
    )
    result = build_case_contents(package)
    assert result.is_valid and result.contents is not None
    assert result.contents.hypotheses[0].status == HypothesisStatus.SUPPORTED
