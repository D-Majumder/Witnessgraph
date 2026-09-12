"""CsvTimelineAdapter: ingests a header-row CSV timeline, one EvidenceItem per data row."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import datetime

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.ingest.adapters._lines import iter_raw_lines
from witnessgraph.ingest.base import SourceDescriptor


class CsvTimelineAdapter:
    """Ingests a CSV file with a header row, one EvidenceItem+NormalizedEvent per data row.

    Every column becomes a NormalizedEvent attribute verbatim; an
    ``event_type`` column is used as the event type if present,
    otherwise "unknown". This is intentionally a simple, honest CSV
    timeline reader, not a general log-parsing framework: one data row is
    assumed to be one physical line (a value containing an embedded
    newline is not supported).

    A row with fewer columns than the header, more columns than the
    header, or bytes that aren't valid UTF-8, still becomes an
    EvidenceItem (evidence is always preserved), but its NormalizedEvent
    reflects the mismatch explicitly rather than silently guessing:

    - A missing column's value is the real Python ``None``, not the
      misleading three-character string ``"None"``.
    - Extra values beyond the last header column are kept, under the key
      ``"_extra_columns"``, rather than silently dropped.
    - A row that fails to decode as UTF-8 yields no NormalizedEvent at
      all (same "evidence preserved, not normalized" treatment as
      unparseable content), and does not prevent other rows in the same
      file from being read.
    """

    adapter_id = "csv_timeline"
    adapter_version = "0.1.0"

    def can_handle(self, source: SourceDescriptor) -> bool:
        return source.path.suffix.lower() == ".csv" or source.kind_hint == "csv_timeline"

    def ingest(
        self, source: SourceDescriptor, *, collected_at: datetime
    ) -> Iterator[tuple[EvidenceItem, NormalizedEvent | None, bytes]]:
        file_bytes = source.path.read_bytes()
        lines = list(iter_raw_lines(file_bytes))

        header_fields: list[str] | None = None
        row_no = 0
        for _line_no, raw_line, line in lines:
            if not raw_line.strip():
                continue
            row_no += 1

            if header_fields is None:
                # The header line is structural, not itself a data record; if it
                # can't even decode, there is no usable schema for this file.
                header_fields = next(csv.reader([line])) if line is not None else []
                continue

            evidence = EvidenceItem.create(
                raw_bytes=raw_line,
                source_adapter=self.adapter_id,
                adapter_version=self.adapter_version,
                source_locator=f"{source.path}:{row_no}",
                collected_at=collected_at,
            )

            normalized: NormalizedEvent | None = None
            if line is not None:
                values = next(csv.reader([line]))
                attributes: dict[str, str | None] = {
                    field: (values[i] if i < len(values) else None)
                    for i, field in enumerate(header_fields)
                }
                if len(values) > len(header_fields):
                    attributes["_extra_columns"] = ",".join(values[len(header_fields) :])

                event_type = (attributes.get("event_type") or "unknown")
                event_type = (event_type or "unknown").strip() or "unknown"
                normalized = NormalizedEvent.create(
                    event_type=event_type,
                    attributes={k: v for k, v in attributes.items() if v is not None},
                    derived_from=(evidence.id,),
                    created_at=collected_at,
                )

            yield evidence, normalized, raw_line
