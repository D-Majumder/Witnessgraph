"""EvidenceItem: a single piece of raw evidence, exactly as collected.

See DESIGN.md principle 1: EvidenceItem is immutable once created. Its
``id`` *is* the SHA-256 content hash of the raw bytes it represents, so
two independently ingested copies of the same bytes always collapse to
the same EvidenceItem, and any modification to the underlying bytes
produces a *different* EvidenceItem rather than a mutation of this one.

See docs/phase4-v0.4-source-identity-design.md for the explicit,
analyst-declared source-identity design implemented by
``ProvenanceRecord.source_id`` below: deliberately placed on the
per-custody-record type, not as a top-level ``EvidenceItem`` field,
specifically so it cannot conflict with the already-existing
byte-identical-content-from-different-sources merge behavior (see
``SqliteStore.put_evidence`` and
``test_duplicate_content_from_different_sources_preserves_both_provenance``).
It is never derived from ``source_locator``, ``source_adapter``, or
``collected_at`` -- always explicitly supplied by a human -- and
structurally cannot affect ``EvidenceItem.id``/``raw_content_hash`` or
the provenance manifest, since ``chain_of_custody`` (where it lives) is
already excluded from both (see this class's own docstring below and
``core.provenance.compute_manifest``).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from witnessgraph.core.ids import sha256_hex

#: Maximum length for an analyst-declared ``source_id``. A policy choice,
#: not derived from any existing constraint -- generous for a
#: human-readable label, not claimed to be an objectively correct number.
MAX_SOURCE_ID_LENGTH = 256

#: Code points rejected outright in a ``source_id`` (not merely
#: neutralized at render time, unlike other free-text fields -- see
#: docs/phase4-v0.4-source-identity-design.md §8/§9). Deliberately the
#: same fixed set ``report.render._NEUTRALIZE`` uses, duplicated here
#: rather than imported: ``core`` has no dependency on ``report``
#: (DESIGN.md principle 6), and ``source_id`` is used for exact-equality
#: grouping, not just display, so a zero-width/bidi character embedded in
#: it is a correctness risk (two visually-identical but unequal source
#: ids) that render-time neutralization alone would not catch.
_SOURCE_ID_FORBIDDEN_CODEPOINTS: frozenset[int] = (
    frozenset(
        {
            0x061C,
            0x200E,
            0x200F,
            0x202A,
            0x202B,
            0x202C,
            0x202D,
            0x202E,
            0x2066,
            0x2067,
            0x2068,
            0x2069,
            0x200B,
            0x200C,
            0x200D,
            0x2060,
            0xFEFF,
        }
    )
    | frozenset(range(0x00, 0x09))
    | frozenset(range(0x0B, 0x20))
    | frozenset({0x7F})
)


def validate_source_id(source_id: str) -> None:
    """Raise ``ValueError`` if ``source_id`` violates its validation rules.

    No rule here silently mutates the input (docs/phase4-v0.4-source-identity-design.md
    §8): every violation is a hard rejection, never a silent trim/fold/
    normalization. Called both by ``ProvenanceRecord``'s own field
    validator (so no construction path can bypass it) and, for a cleaner
    CLI error, directly by ``cli.main``'s ``ingest`` command before any
    ingestion work begins.
    """
    if source_id == "":
        raise ValueError(
            "source_id must not be an empty string -- omit it entirely to declare no source"
        )
    if source_id != source_id.strip():
        raise ValueError("source_id must not have leading/trailing whitespace")
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"source_id must be at most {MAX_SOURCE_ID_LENGTH} characters")
    if any(ord(ch) in _SOURCE_ID_FORBIDDEN_CODEPOINTS for ch in source_id):
        raise ValueError(
            "source_id must not contain control, bidi, or zero-width characters"
        )


class ProvenanceRecord(BaseModel):
    """One entry in an EvidenceItem's chain of custody.

    ``actor`` identifies who or what performed the action, e.g.
    ``"adapter:jsonl@0.1.0"`` or ``"analyst:<free-text-id>"``.

    ``source_locator`` records *where this specific record's action*
    read the evidence from (e.g. ``"case1/incident.jsonl:12"``), if
    applicable. It is what lets two ingestions of byte-identical content
    from two different sources remain distinguishable in the custody
    history rather than colliding (see ``SqliteStore.put_evidence``).

    ``source_id`` is an explicit, analyst-declared assertion of common
    provenance (e.g. ``"host1"``) -- see the module docstring. Unlike
    ``source_locator``, Witnessgraph never populates it automatically;
    it is ``None`` unless a human supplied one at ingestion time, and
    ``None`` is a permanent, valid state, never inferred after the fact.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str
    action: str
    timestamp: datetime
    source_locator: str | None = None
    source_id: str | None = None

    @field_validator("source_id")
    @classmethod
    def _source_id_is_well_formed(cls, v: str | None) -> str | None:
        if v is not None:
            validate_source_id(v)
        return v


class EvidenceItem(BaseModel):
    """A single piece of raw evidence, immutable once created.

    Construct instances via :meth:`create`, not the constructor directly,
    so ``id``/``raw_content_hash`` are always derived correctly from the
    actual bytes. The raw bytes themselves live in the case's content-
    addressed blob store (``witnessgraph.store``), keyed by
    ``raw_content_hash``; this object is metadata plus a pointer.

    Note on the provenance manifest: the case's manifest hash (see
    ``witnessgraph.core.provenance``) is computed from ``id`` /
    ``raw_content_hash`` only, not from ``chain_of_custody`` -- appending
    a custody record (e.g. "exported", "imported") is a legitimate,
    non-mutating operation (see :meth:`with_custody_record`) that must
    never change a case's reproducibility hash.

    Note on duplicate content: if byte-identical content is ingested more
    than once (e.g. the same log line present in two different source
    files), both ingestions collapse to the same ``id``/``raw_content_hash``
    -- but the *store* (see ``SqliteStore.put_evidence``) merges rather
    than overwrites: the first-known ``source_locator``/``collected_at``
    are preserved, and every genuinely distinct custody record (tracked
    via each record's own ``source_locator``) is retained, so re-ingesting
    the same content from a different source is never silently lossy of
    the earlier source's provenance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    source_adapter: str
    adapter_version: str
    source_locator: str
    raw_content_hash: str
    raw_size_bytes: int
    collected_at: datetime
    observed_at: datetime | None = None
    ingest_parameters: dict[str, str] = Field(default_factory=dict)
    chain_of_custody: tuple[ProvenanceRecord, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _id_matches_content_hash(self) -> EvidenceItem:
        if self.id != self.raw_content_hash:
            raise ValueError("EvidenceItem.id must equal raw_content_hash")
        if self.raw_size_bytes < 0:
            raise ValueError("EvidenceItem.raw_size_bytes must be non-negative")
        return self

    @classmethod
    def create(
        cls,
        *,
        raw_bytes: bytes,
        source_adapter: str,
        adapter_version: str,
        source_locator: str,
        collected_at: datetime,
        observed_at: datetime | None = None,
        ingest_parameters: dict[str, str] | None = None,
        source_id: str | None = None,
    ) -> EvidenceItem:
        """Build an EvidenceItem from raw bytes, deriving id/raw_content_hash correctly.

        ``source_id``, if given, is an explicit, analyst-declared source
        identity (see ``ProvenanceRecord.source_id``) -- never inferred
        from ``source_adapter``/``source_locator``/``collected_at``.
        """
        raw_hash = sha256_hex(raw_bytes)
        record = ProvenanceRecord(
            actor=f"adapter:{source_adapter}@{adapter_version}",
            action="ingested",
            timestamp=collected_at,
            source_locator=source_locator,
            source_id=source_id,
        )
        return cls(
            id=raw_hash,
            source_adapter=source_adapter,
            adapter_version=adapter_version,
            source_locator=source_locator,
            raw_content_hash=raw_hash,
            raw_size_bytes=len(raw_bytes),
            collected_at=collected_at,
            observed_at=observed_at,
            ingest_parameters=ingest_parameters or {},
            chain_of_custody=(record,),
        )

    def with_custody_record(self, record: ProvenanceRecord) -> EvidenceItem:
        """Return a *new* EvidenceItem with an appended custody record.

        Never mutates ``self``. Content (id/raw_content_hash/raw bytes)
        is unaffected -- see the class docstring's note on the manifest.
        """
        return self.model_copy(update={"chain_of_custody": (*self.chain_of_custody, record)})

    def declared_source_ids(self) -> frozenset[str]:
        """Distinct, non-``None`` ``source_id`` values across this item's custody history.

        Ordinarily has zero or one element. More than one means this
        evidence's bytes were declared under two different source
        identities by two different ingestions that happened to produce
        byte-identical content -- a real, if rare, ambiguity a consumer
        (e.g. a future cross-source analysis) must treat as excluded, not
        guess between (docs/phase4-v0.4-source-identity-design.md §2).
        """
        return frozenset(
            record.source_id for record in self.chain_of_custody if record.source_id is not None
        )
