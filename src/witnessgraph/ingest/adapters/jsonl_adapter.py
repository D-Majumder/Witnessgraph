"""JsonlAdapter: ingests newline-delimited JSON, one EvidenceItem per line."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.ingest.adapters._lines import iter_raw_lines
from witnessgraph.ingest.base import SourceDescriptor


class JsonlAdapter:
    """Ingests newline-delimited JSON objects, one EvidenceItem per line.

    Each non-blank line becomes its own EvidenceItem (its content hash
    covers exactly that line's bytes). If the line parses as a JSON
    object, a NormalizedEvent is also produced, whose attributes are the
    object's top-level keys stringified. A line that fails to parse as
    JSON, or fails to decode as UTF-8, still becomes an EvidenceItem --
    evidence is preserved even when it cannot be normalized -- but yields
    no NormalizedEvent. One bad line never prevents the other lines in
    the same file from being ingested.
    """

    adapter_id = "jsonl"
    adapter_version = "0.1.0"

    def can_handle(self, source: SourceDescriptor) -> bool:
        return source.path.suffix.lower() in (".jsonl", ".ndjson") or source.kind_hint == "jsonl"

    def ingest(
        self, source: SourceDescriptor, *, collected_at: datetime
    ) -> Iterator[tuple[EvidenceItem, NormalizedEvent | None, bytes]]:
        file_bytes = source.path.read_bytes()
        for line_no, raw_line, line in iter_raw_lines(file_bytes):
            if not raw_line.strip():
                continue

            evidence = EvidenceItem.create(
                raw_bytes=raw_line,
                source_adapter=self.adapter_id,
                adapter_version=self.adapter_version,
                source_locator=f"{source.path}:{line_no}",
                collected_at=collected_at,
                source_id=source.source_id,
            )

            normalized: NormalizedEvent | None = None
            obj = None
            if line is not None:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    obj = None

            if isinstance(obj, dict):
                event_type = str(obj.get("event_type", "unknown"))
                attributes = {str(k): str(v) for k, v in obj.items()}
                normalized = NormalizedEvent.create(
                    event_type=event_type,
                    attributes=attributes,
                    derived_from=(evidence.id,),
                    created_at=collected_at,
                )

            yield evidence, normalized, raw_line
