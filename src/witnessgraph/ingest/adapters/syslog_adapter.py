"""SyslogAdapter: a deliberately narrow parser for classic BSD-style syslog lines."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.ingest.adapters._lines import iter_raw_lines
from witnessgraph.ingest.base import SourceDescriptor

# Matches lines shaped like:
#   "Jan 12 03:04:05 hostname process[1234]: message text"
# This is NOT a full RFC 3164/5424 implementation -- it is a narrow,
# honest parser for the classic BSD format. Lines that don't match are
# still preserved as EvidenceItem(s), just without a NormalizedEvent
# (same "preserve evidence even when it can't be normalized" philosophy
# as JsonlAdapter).
_SYSLOG_LINE_RE = re.compile(
    r"^(?P<month>\w{3})\s+(?P<day>\d{1,2})\s+(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<host>\S+)\s+(?P<process>[\w./-]+?)(\[(?P<pid>\d+)\])?:\s*(?P<message>.*)$"
)


class SyslogAdapter:
    adapter_id = "syslog"
    adapter_version = "0.1.0"

    def can_handle(self, source: SourceDescriptor) -> bool:
        return source.path.suffix.lower() in (".log", ".syslog") or source.kind_hint == "syslog"

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
            )

            match = _SYSLOG_LINE_RE.match(line) if line is not None else None
            normalized: NormalizedEvent | None = None
            if match:
                fields = match.groupdict()
                attributes = {
                    "host": fields["host"],
                    "process": fields["process"],
                    "pid": fields.get("pid") or "",
                    "message": fields["message"],
                    # Classic BSD syslog carries no year/timezone; we deliberately
                    # keep this as an opaque string rather than guessing at a
                    # full timestamp (DESIGN.md principle 3: no silent inference).
                    "raw_timestamp": f"{fields['month']} {fields['day']} {fields['time']}",
                }
                normalized = NormalizedEvent.create(
                    event_type="syslog_line",
                    attributes=attributes,
                    derived_from=(evidence.id,),
                    created_at=collected_at,
                )

            yield evidence, normalized, raw_line
