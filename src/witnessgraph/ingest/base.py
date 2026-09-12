"""EvidenceAdapter protocol and SourceDescriptor.

See SECURITY.md and DESIGN.md principle 6: a SourceDescriptor always
points at something that already exists on the local filesystem. There
is no network-capable source kind, and no adapter may reach out to a
live target.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem


@dataclass(frozen=True)
class SourceDescriptor:
    """Describes one already-existing evidence source to be ingested."""

    path: Path
    kind_hint: str | None = None


class EvidenceAdapter(Protocol):
    """The contract every ingestion adapter must satisfy.

    ``ingest`` yields one ``(evidence, normalized, raw_bytes)`` triple per
    record. ``raw_bytes`` is exactly the byte string ``evidence`` was
    built from (i.e. ``sha256_hex(raw_bytes) == evidence.raw_content_hash``)
    -- see docs/phase3-v0.3-design.md §6.7/§8: the pipeline needs the raw
    bytes themselves, not just their hash, to persist them into the
    case's content-addressed blob store.
    """

    adapter_id: str
    adapter_version: str

    def can_handle(self, source: SourceDescriptor) -> bool: ...

    def ingest(
        self, source: SourceDescriptor, *, collected_at: datetime
    ) -> Iterator[tuple[EvidenceItem, NormalizedEvent | None, bytes]]: ...
