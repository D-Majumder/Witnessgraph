"""Pydantic schema for a researcher-authored case package (``case.json``).

See ``docs/research/witnessgraph-case-format.md`` for the full field
reference. Every model here uses ``extra="forbid"`` so an unrecognized
top-level key (e.g. a ``findings``/``contradictions``/``gaps`` block --
system-derived analysis, never importable, see this package's
``__init__.py`` docstring) is rejected at parse time rather than silently
ignored.

``local_id`` is a researcher-chosen string, unique within one package,
used only to express cross-references *within this file*
(``derived_from``, ``source_entity``/``target_entity``,
``subject_event``/``source_evidence``, hypothesis evidence refs). For
content-addressed types (evidence, normalized events, relationships,
time assertions) it is never the final stored id -- that id is always
content-derived, exactly as every other ingestion path in this codebase
already computes it (see ``witnessgraph.casepkg.build``). For
non-content-addressed types (entities, hypotheses) ``local_id`` *is*
used as the final stored id directly -- this is what makes
export-then-reimport reproduce the exact same entity/hypothesis ids
(see ``exporter.py``), and lets a researcher authoring a brand-new
package simply pick a memorable id (e.g. ``"host-a"``) once and reuse it
everywhere in the file.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from witnessgraph.core.hypothesis import HypothesisStatus
from witnessgraph.core.time_model import TimePrecision

#: Bump only on a breaking shape change to this schema (a field renamed,
#: removed, or made to mean something different) -- additive, optional
#: fields do not require a bump. Mirrors the precedent in
#: ``report.render_json``'s own ``JSON_SCHEMA_VERSION`` and
#: ``core.provenance.CURRENT_MANIFEST_VERSION``.
CASE_PACKAGE_SCHEMA_VERSION = 1

#: Recorded on every EvidenceItem a case package constructs, so it is
#: always possible to tell "researcher declared this directly in a case
#: package" apart from "an ingestion adapter produced this from a raw
#: source file" by looking at ``EvidenceItem.source_adapter`` alone.
PACKAGE_EVIDENCE_ADAPTER_ID = "researcher-case-package"
PACKAGE_EVIDENCE_ADAPTER_VERSION = str(CASE_PACKAGE_SCHEMA_VERSION)


class DeclaredEvidenceItem(BaseModel):
    """One researcher-declared piece of raw evidence.

    Exactly one of ``content``/``content_base64`` must be given -- this
    is where the package's evidence bytes actually live; the resulting
    ``EvidenceItem.id`` is always the SHA-256 of those exact bytes
    (DESIGN.md principle 1), never a value this schema lets a researcher
    set directly.
    """

    model_config = ConfigDict(extra="forbid")

    local_id: str
    content: str | None = None
    content_base64: str | None = None
    source_locator: str
    collected_at: datetime
    observed_at: datetime | None = None
    source_id: str | None = None
    ingest_parameters: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _exactly_one_content_field(self) -> DeclaredEvidenceItem:
        if (self.content is None) == (self.content_base64 is None):
            raise ValueError(
                f"evidence_items[{self.local_id!r}] must set exactly one of "
                "content/content_base64, not both or neither"
            )
        return self


class DeclaredNormalizedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_id: str
    event_type: str
    derived_from: tuple[str, ...]
    attributes: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class DeclaredEntity(BaseModel):
    """Becomes ``Entity(id=local_id, ...)`` directly -- see this module's docstring."""

    model_config = ConfigDict(extra="forbid")

    local_id: str
    entity_type: str
    identifiers: dict[str, str] = Field(default_factory=dict)
    derived_from: tuple[str, ...]
    first_seen: datetime | None = None
    last_seen: datetime | None = None


class DeclaredRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_id: str | None = None
    relationship_type: str
    source_entity: str
    target_entity: str
    derived_from: tuple[str, ...]
    attributes: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class DeclaredTimeAssertion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    local_id: str | None = None
    subject_event: str
    value: datetime
    precision: TimePrecision
    source_evidence: str
    asserted_by: str
    created_at: datetime


class DeclaredEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["evidence_item", "normalized_event"]
    local_id: str


class DeclaredHypothesis(BaseModel):
    """A researcher hypothesis -- can only ever reference evidence, never assert a bare fact.

    See DESIGN.md principle 3 and ``core.hypothesis.Hypothesis``, which
    this model mirrors field-for-field. If ``local_id`` is given, it
    becomes the final ``Hypothesis.id`` directly (for export/reimport
    fidelity); if omitted, a fresh random id is assigned on import.
    """

    model_config = ConfigDict(extra="forbid")

    local_id: str | None = None
    statement: str
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    supporting_evidence: tuple[DeclaredEvidenceRef, ...] = Field(default_factory=tuple)
    contradicting_evidence: tuple[DeclaredEvidenceRef, ...] = Field(default_factory=tuple)
    inferred_by: str
    created_at: datetime


class CaseMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str = ""
    created_by: str
    created_at: datetime


class CasePackage(BaseModel):
    """The full contents of one researcher-authored ``case.json``.

    Processing order is fixed and matches the dependency order every
    field above assumes: evidence_items, then normalized_events, then
    entities, then relationships/time_assertions/hypotheses (which may
    freely interleave with each other, but never with anything earlier
    in this list) -- see ``build.py``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int
    package_version: str
    case_metadata: CaseMetadata
    evidence_items: tuple[DeclaredEvidenceItem, ...] = Field(default_factory=tuple)
    normalized_events: tuple[DeclaredNormalizedEvent, ...] = Field(default_factory=tuple)
    entities: tuple[DeclaredEntity, ...] = Field(default_factory=tuple)
    relationships: tuple[DeclaredRelationship, ...] = Field(default_factory=tuple)
    time_assertions: tuple[DeclaredTimeAssertion, ...] = Field(default_factory=tuple)
    hypotheses: tuple[DeclaredHypothesis, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _schema_version_is_supported(self) -> CasePackage:
        if self.schema_version != CASE_PACKAGE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported case package schema_version {self.schema_version!r}; "
                f"this installation supports schema_version {CASE_PACKAGE_SCHEMA_VERSION} only"
            )
        return self
