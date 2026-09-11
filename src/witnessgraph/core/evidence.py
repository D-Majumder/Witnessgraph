"""EvidenceItem: a single piece of raw evidence, exactly as collected.

See DESIGN.md principle 1: EvidenceItem is immutable once created. Its
``id`` *is* the SHA-256 content hash of the raw bytes it represents, so
two independently ingested copies of the same bytes always collapse to
the same EvidenceItem, and any modification to the underlying bytes
produces a *different* EvidenceItem rather than a mutation of this one.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from witnessgraph.core.ids import sha256_hex


class ProvenanceRecord(BaseModel):
    """One entry in an EvidenceItem's chain of custody.

    ``actor`` identifies who or what performed the action, e.g.
    ``"adapter:jsonl@0.1.0"`` or ``"analyst:<free-text-id>"``.

    ``source_locator`` records *where this specific record's action*
    read the evidence from (e.g. ``"case1/incident.jsonl:12"``), if
    applicable. It is what lets two ingestions of byte-identical content
    from two different sources remain distinguishable in the custody
    history rather than colliding (see ``SqliteStore.put_evidence``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    actor: str
    action: str
    timestamp: datetime
    source_locator: str | None = None


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
    ) -> EvidenceItem:
        """Build an EvidenceItem from raw bytes, deriving id/raw_content_hash correctly."""
        raw_hash = sha256_hex(raw_bytes)
        record = ProvenanceRecord(
            actor=f"adapter:{source_adapter}@{adapter_version}",
            action="ingested",
            timestamp=collected_at,
            source_locator=source_locator,
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
