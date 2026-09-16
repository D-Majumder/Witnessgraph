"""Resolve a ``CasePackage`` into real Witnessgraph domain objects.

This is the one place package-local reference resolution happens, shared
by ``validate.py`` (which builds and discards the result, reporting only
errors) and ``importer.py`` (which builds and then persists the result
into a real ``Case``) -- so "does this package validate" and "what would
importing it actually produce" can never silently disagree.

No object constructed here is ever written to a ``Case``/``Store`` by
this module -- see ``importer.py`` for the only code path that persists
anything. This module also never invents a missing reference: every
``derived_from``/``source_entity``/``target_entity``/``subject_event``/
``source_evidence``/evidence-ref field must resolve to an
already-declared, earlier local_id in the package, or the corresponding
object is rejected with an explicit error naming the missing local_id --
mirroring exactly what the CLI's own ``entities create``/
``relationships create`` referential-existence checks already do one
layer up from ``core/`` (see DESIGN.md principle 3's note on
``EvidenceRef``).
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field

from pydantic import ValidationError

from witnessgraph.casepkg.schema import (
    PACKAGE_EVIDENCE_ADAPTER_ID,
    PACKAGE_EVIDENCE_ADAPTER_VERSION,
    CasePackage,
    DeclaredEvidenceRef,
)
from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis
from witnessgraph.core.relationships import Relationship
from witnessgraph.core.time_model import TimeAssertion

#: A generous but finite ceiling on one declared evidence item's raw
#: content, applied before any hashing/storage work -- guards against a
#: hostile or malformed package trying to exhaust memory/disk via a
#: single oversized ``content``/``content_base64`` field. Not claimed to
#: be the "correct" limit for every deployment, only a safe default; see
#: docs/research/witnessgraph-case-format.md's security section.
MAX_EVIDENCE_CONTENT_BYTES = 50 * 1024 * 1024

#: A ceiling on the total number of declared objects a single package
#: may contain (summed across all six collections) -- guards against a
#: package with an absurd object count that would be individually
#: small but collectively exhaust memory/time during resolution.
MAX_TOTAL_DECLARED_OBJECTS = 200_000


@dataclass(frozen=True)
class BuildError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@dataclass(frozen=True)
class BuiltCaseContents:
    evidence: tuple[tuple[EvidenceItem, bytes], ...]
    normalized_events: tuple[NormalizedEvent, ...]
    entities: tuple[Entity, ...]
    relationships: tuple[Relationship, ...]
    time_assertions: tuple[TimeAssertion, ...]
    hypotheses: tuple[Hypothesis, ...]


@dataclass(frozen=True)
class BuildResult:
    contents: BuiltCaseContents | None
    errors: tuple[BuildError, ...] = field(default_factory=tuple)

    @property
    def is_valid(self) -> bool:
        return not self.errors and self.contents is not None


def build_case_contents(package: CasePackage) -> BuildResult:
    """Resolve every declared object in ``package``, collecting every error found.

    Returns a ``BuildResult`` with ``contents=None`` if any error was
    found (partial/inconsistent output is never returned as if it were
    usable) -- callers check ``is_valid`` before touching ``contents``.
    """
    errors: list[BuildError] = []
    seen_local_ids: set[str] = set()
    evidence_ids: dict[str, str] = {}
    event_ids: dict[str, str] = {}
    entity_ids: dict[str, str] = {}

    total_declared = (
        len(package.evidence_items)
        + len(package.normalized_events)
        + len(package.entities)
        + len(package.relationships)
        + len(package.time_assertions)
        + len(package.hypotheses)
    )
    if total_declared > MAX_TOTAL_DECLARED_OBJECTS:
        errors.append(
            BuildError(
                "<package>",
                f"declares {total_declared} objects, exceeding the maximum of "
                f"{MAX_TOTAL_DECLARED_OBJECTS} this installation accepts",
            )
        )
        return BuildResult(contents=None, errors=tuple(errors))

    def _claim_local_id(local_id: str | None, path: str) -> bool:
        if local_id is None:
            return True
        if not local_id.strip():
            errors.append(BuildError(path, "local_id must not be blank"))
            return False
        if local_id in seen_local_ids:
            errors.append(BuildError(path, f"duplicate local_id {local_id!r}"))
            return False
        seen_local_ids.add(local_id)
        return True

    evidence_built: list[tuple[EvidenceItem, bytes]] = []
    for i, dec in enumerate(package.evidence_items):
        path = f"evidence_items[{i}] ({dec.local_id!r})"
        if not _claim_local_id(dec.local_id, path):
            continue
        try:
            if dec.content is not None:
                raw_bytes = dec.content.encode("utf-8")
            else:
                assert dec.content_base64 is not None
                raw_bytes = base64.b64decode(dec.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            errors.append(BuildError(path, f"invalid content_base64: {exc}"))
            continue
        if len(raw_bytes) > MAX_EVIDENCE_CONTENT_BYTES:
            errors.append(
                BuildError(
                    path,
                    f"content is {len(raw_bytes)} bytes, exceeding the maximum of "
                    f"{MAX_EVIDENCE_CONTENT_BYTES} bytes per declared evidence item",
                )
            )
            continue
        try:
            item = EvidenceItem.create(
                raw_bytes=raw_bytes,
                source_adapter=PACKAGE_EVIDENCE_ADAPTER_ID,
                adapter_version=PACKAGE_EVIDENCE_ADAPTER_VERSION,
                source_locator=dec.source_locator,
                collected_at=dec.collected_at,
                observed_at=dec.observed_at,
                ingest_parameters=dict(dec.ingest_parameters),
                source_id=dec.source_id,
            )
        except (ValueError, ValidationError) as exc:
            errors.append(BuildError(path, str(exc)))
            continue
        evidence_ids[dec.local_id] = item.id
        evidence_built.append((item, raw_bytes))

    normalized_built: list[NormalizedEvent] = []
    for i, ne_dec in enumerate(package.normalized_events):
        path = f"normalized_events[{i}] ({ne_dec.local_id!r})"
        if not _claim_local_id(ne_dec.local_id, path):
            continue
        derived_ids, ok = _resolve_many(
            ne_dec.derived_from, {**evidence_ids, **event_ids}, path, "derived_from", errors
        )
        if not ok:
            continue
        try:
            event = NormalizedEvent.create(
                event_type=ne_dec.event_type,
                derived_from=tuple(derived_ids),
                created_at=ne_dec.created_at,
                attributes=dict(ne_dec.attributes),
            )
        except (ValueError, ValidationError) as exc:
            errors.append(BuildError(path, str(exc)))
            continue
        event_ids[ne_dec.local_id] = event.id
        normalized_built.append(event)

    entities_built: list[Entity] = []
    for i, ent_dec in enumerate(package.entities):
        path = f"entities[{i}] ({ent_dec.local_id!r})"
        if not _claim_local_id(ent_dec.local_id, path):
            continue
        derived_ids, ok = _resolve_many(
            ent_dec.derived_from, {**evidence_ids, **event_ids}, path, "derived_from", errors
        )
        if not ok:
            continue
        try:
            entity = Entity(
                id=ent_dec.local_id,
                entity_type=ent_dec.entity_type,
                identifiers=dict(ent_dec.identifiers),
                first_seen=ent_dec.first_seen,
                last_seen=ent_dec.last_seen,
                derived_from=tuple(derived_ids),
            )
        except (ValueError, ValidationError) as exc:
            errors.append(BuildError(path, str(exc)))
            continue
        entity_ids[ent_dec.local_id] = entity.id
        entities_built.append(entity)

    relationships_built: list[Relationship] = []
    for i, rel_dec in enumerate(package.relationships):
        path = f"relationships[{i}]" + (f" ({rel_dec.local_id!r})" if rel_dec.local_id else "")
        if not _claim_local_id(rel_dec.local_id, path):
            continue
        ok = True
        if rel_dec.source_entity not in entity_ids:
            errors.append(
                BuildError(
                    path,
                    f"source_entity references unknown entity local_id {rel_dec.source_entity!r}",
                )
            )
            ok = False
        if rel_dec.target_entity not in entity_ids:
            errors.append(
                BuildError(
                    path,
                    f"target_entity references unknown entity local_id {rel_dec.target_entity!r}",
                )
            )
            ok = False
        derived_ids, ref_ok = _resolve_many(
            rel_dec.derived_from, {**evidence_ids, **event_ids}, path, "derived_from", errors
        )
        ok = ok and ref_ok
        if not ok:
            continue
        try:
            rel = Relationship.create(
                relationship_type=rel_dec.relationship_type,
                source_entity_id=entity_ids[rel_dec.source_entity],
                target_entity_id=entity_ids[rel_dec.target_entity],
                derived_from=tuple(derived_ids),
                created_at=rel_dec.created_at,
                attributes=dict(rel_dec.attributes),
            )
        except (ValueError, ValidationError) as exc:
            errors.append(BuildError(path, str(exc)))
            continue
        relationships_built.append(rel)

    time_assertions_built: list[TimeAssertion] = []
    for i, ta_dec in enumerate(package.time_assertions):
        path = f"time_assertions[{i}]" + (f" ({ta_dec.local_id!r})" if ta_dec.local_id else "")
        if not _claim_local_id(ta_dec.local_id, path):
            continue
        ok = True
        if ta_dec.subject_event not in event_ids:
            errors.append(
                BuildError(
                    path,
                    f"subject_event references unknown normalized_event local_id "
                    f"{ta_dec.subject_event!r}",
                )
            )
            ok = False
        if ta_dec.source_evidence not in evidence_ids:
            errors.append(
                BuildError(
                    path,
                    f"source_evidence references unknown evidence_item local_id "
                    f"{ta_dec.source_evidence!r}",
                )
            )
            ok = False
        if not ok:
            continue
        try:
            assertion = TimeAssertion.create(
                subject_event_id=event_ids[ta_dec.subject_event],
                value=ta_dec.value,
                precision=ta_dec.precision,
                source_evidence_id=evidence_ids[ta_dec.source_evidence],
                asserted_by=ta_dec.asserted_by,
                created_at=ta_dec.created_at,
            )
        except (ValueError, ValidationError) as exc:
            errors.append(BuildError(path, str(exc)))
            continue
        time_assertions_built.append(assertion)

    hypotheses_built: list[Hypothesis] = []
    for i, hyp_dec in enumerate(package.hypotheses):
        path = f"hypotheses[{i}]" + (f" ({hyp_dec.local_id!r})" if hyp_dec.local_id else "")
        if not _claim_local_id(hyp_dec.local_id, path):
            continue
        ok = True
        supporting: list[EvidenceRef] = []
        for ref in hyp_dec.supporting_evidence:
            resolved = _resolve_evidence_ref(
                ref, evidence_ids, event_ids, path, "supporting_evidence", errors
            )
            if resolved is None:
                ok = False
            else:
                supporting.append(resolved)
        contradicting: list[EvidenceRef] = []
        for ref in hyp_dec.contradicting_evidence:
            resolved = _resolve_evidence_ref(
                ref, evidence_ids, event_ids, path, "contradicting_evidence", errors
            )
            if resolved is None:
                ok = False
            else:
                contradicting.append(resolved)
        if not ok:
            continue
        try:
            hyp = (
                Hypothesis(
                    id=hyp_dec.local_id,
                    statement=hyp_dec.statement,
                    status=hyp_dec.status,
                    supporting_evidence=tuple(supporting),
                    contradicting_evidence=tuple(contradicting),
                    inferred_by=hyp_dec.inferred_by,
                    created_at=hyp_dec.created_at,
                )
                if hyp_dec.local_id is not None
                else Hypothesis(
                    statement=hyp_dec.statement,
                    status=hyp_dec.status,
                    supporting_evidence=tuple(supporting),
                    contradicting_evidence=tuple(contradicting),
                    inferred_by=hyp_dec.inferred_by,
                    created_at=hyp_dec.created_at,
                )
            )
        except (ValueError, ValidationError) as exc:
            errors.append(BuildError(path, str(exc)))
            continue
        hypotheses_built.append(hyp)

    if errors:
        return BuildResult(contents=None, errors=tuple(errors))

    return BuildResult(
        contents=BuiltCaseContents(
            evidence=tuple(evidence_built),
            normalized_events=tuple(normalized_built),
            entities=tuple(entities_built),
            relationships=tuple(relationships_built),
            time_assertions=tuple(time_assertions_built),
            hypotheses=tuple(hypotheses_built),
        ),
        errors=(),
    )


def _resolve_many(
    refs: tuple[str, ...],
    known: dict[str, str],
    path: str,
    field_name: str,
    errors: list[BuildError],
) -> tuple[list[str], bool]:
    resolved: list[str] = []
    ok = True
    for ref in refs:
        if ref not in known:
            errors.append(
                BuildError(
                    path,
                    f"{field_name} references unknown local_id {ref!r} "
                    "(must be an earlier evidence_items/normalized_events entry)",
                )
            )
            ok = False
        else:
            resolved.append(known[ref])
    return resolved, ok


def _resolve_evidence_ref(
    ref: DeclaredEvidenceRef,
    evidence_ids: dict[str, str],
    event_ids: dict[str, str],
    path: str,
    field_name: str,
    errors: list[BuildError],
) -> EvidenceRef | None:
    if ref.kind == "evidence_item":
        if ref.local_id not in evidence_ids:
            errors.append(
                BuildError(
                    path,
                    f"{field_name} references unknown evidence_item local_id {ref.local_id!r}",
                )
            )
            return None
        return EvidenceRef(kind="evidence_item", id=evidence_ids[ref.local_id])
    if ref.local_id not in event_ids:
        errors.append(
            BuildError(
                path, f"{field_name} references unknown normalized_event local_id {ref.local_id!r}"
            )
        )
        return None
    return EvidenceRef(kind="normalized_event", id=event_ids[ref.local_id])
