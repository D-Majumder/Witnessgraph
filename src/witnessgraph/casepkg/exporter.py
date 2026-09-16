"""Export an existing ``Case``'s declared contents as a ``CasePackage``.

The inverse of ``importer.py``, for the same purpose DESIGN.md principle
4 already requires of ``.wgcase`` (see ``witnessgraph.portable``): a
researcher should be able to export a case, hand the package to another
researcher, have them import it, and get back the exact same logical
case. Every object here uses its own real, already-assigned id as its
``local_id`` -- so entity/hypothesis ids (which are not content-derived)
survive an export/reimport round trip exactly, and evidence/event/
relationship/time-assertion ids (which are content-derived) simply
re-derive to themselves on reimport regardless.

Unlike ``.wgcase`` (a byte-for-byte archive of the case's SQLite
database and blob store), this is a *declarative*, human-readable JSON
projection -- useful for review, diffing, and hand-editing in a way a
binary SQLite file is not. Both formats remain supported; see
docs/research/witnessgraph-case-format.md for when to use which.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Literal

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
from witnessgraph.store.case import Case


def export_case_package(
    case: Case,
    *,
    package_version: str = "1.0.0",
    title: str = "Exported Witnessgraph case",
    description: str = "",
    created_by: str = "witnessgraph-export",
) -> CasePackage:
    """Build a ``CasePackage`` from everything currently stored in ``case``.

    ``title``/``description``/``created_by`` are not derived from
    anything stored in the case (Witnessgraph's ``Case`` records no such
    metadata today) -- they are caller-supplied labels for the exported
    package, defaulted to clearly generic values when not given.
    """
    store = case.store

    evidence_items = tuple(
        DeclaredEvidenceItem(
            local_id=item.id,
            **_content_field(case.blobs.get(item.raw_content_hash)),
            source_locator=item.source_locator,
            collected_at=item.collected_at,
            observed_at=item.observed_at,
            source_id=next(iter(item.declared_source_ids()), None),
            ingest_parameters=dict(item.ingest_parameters),
        )
        for item in sorted(store.list_evidence(), key=lambda e: e.id)
    )

    normalized_events = tuple(
        DeclaredNormalizedEvent(
            local_id=event.id,
            event_type=event.event_type,
            derived_from=event.derived_from,
            attributes=dict(event.attributes),
            created_at=event.created_at,
        )
        for event in sorted(store.list_normalized_events(), key=lambda e: e.id)
    )

    entities = tuple(
        DeclaredEntity(
            local_id=entity.id,
            entity_type=entity.entity_type,
            identifiers=dict(entity.identifiers),
            derived_from=entity.derived_from,
            first_seen=entity.first_seen,
            last_seen=entity.last_seen,
        )
        for entity in sorted(store.list_entities(), key=lambda e: e.id)
    )

    relationships = tuple(
        DeclaredRelationship(
            local_id=rel.id,
            relationship_type=rel.relationship_type,
            source_entity=rel.source_entity_id,
            target_entity=rel.target_entity_id,
            derived_from=rel.derived_from,
            attributes=dict(rel.attributes),
            created_at=rel.created_at,
        )
        for rel in sorted(store.list_relationships(), key=lambda r: r.id)
    )

    time_assertions = tuple(
        DeclaredTimeAssertion(
            local_id=ta.id,
            subject_event=ta.subject_event_id,
            value=ta.value,
            precision=ta.precision,
            source_evidence=ta.source_evidence_id,
            asserted_by=ta.asserted_by,
            created_at=ta.created_at,
        )
        for ta in sorted(store.list_time_assertions(), key=lambda t: t.id)
    )

    hypotheses = tuple(
        DeclaredHypothesis(
            local_id=hyp.id,
            statement=hyp.statement,
            status=hyp.status,
            supporting_evidence=tuple(
                DeclaredEvidenceRef(kind=_ref_kind(ref.kind), local_id=ref.id)
                for ref in hyp.supporting_evidence
            ),
            contradicting_evidence=tuple(
                DeclaredEvidenceRef(kind=_ref_kind(ref.kind), local_id=ref.id)
                for ref in hyp.contradicting_evidence
            ),
            inferred_by=hyp.inferred_by,
            created_at=hyp.created_at,
        )
        for hyp in sorted(store.list_hypotheses(), key=lambda h: h.id)
    )

    return CasePackage(
        schema_version=CASE_PACKAGE_SCHEMA_VERSION,
        package_version=package_version,
        case_metadata=CaseMetadata(
            title=title,
            description=description,
            created_by=created_by,
            created_at=datetime.now(UTC),
        ),
        evidence_items=evidence_items,
        normalized_events=normalized_events,
        entities=entities,
        relationships=relationships,
        time_assertions=time_assertions,
        hypotheses=hypotheses,
    )


def _ref_kind(kind: str) -> Literal["evidence_item", "normalized_event"]:
    """Narrow ``EvidenceRef.kind`` (``str`` -- see core.hypothesis) to the
    Literal ``DeclaredEvidenceRef.kind`` expects. Never actually fails in
    practice: ``EvidenceRef`` itself already restricts ``kind`` to these
    same two values at construction time."""
    if kind not in ("evidence_item", "normalized_event"):
        raise ValueError(f"unexpected EvidenceRef.kind {kind!r}")
    return kind  # type: ignore[return-value]


def _content_field(raw_bytes: bytes) -> dict[str, str]:
    """Prefer plain UTF-8 ``content`` for readability; fall back to base64
    only when the bytes are not valid UTF-8 text."""
    try:
        return {"content": raw_bytes.decode("utf-8")}
    except UnicodeDecodeError:
        return {"content_base64": base64.b64encode(raw_bytes).decode("ascii")}
