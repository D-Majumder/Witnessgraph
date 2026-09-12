"""C2 / B2 regressions: adapters must survive malformed bytes without losing
otherwise-valid evidence, and CSV row/column mismatches must be explicit
rather than silently misleading.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from witnessgraph.core.ids import sha256_hex
from witnessgraph.ingest.adapters.csv_timeline_adapter import CsvTimelineAdapter
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.adapters.syslog_adapter import SyslogAdapter
from witnessgraph.ingest.base import SourceDescriptor

NOW = datetime(2026, 1, 1, tzinfo=UTC)

# One well-formed line, one line with an invalid UTF-8 byte, one more
# well-formed line -- for each adapter's own line shape.
_BAD_BYTE_CASES = [
    (
        JsonlAdapter(),
        b'{"event_type": "logon", "user": "alice"}\n'
        b"\xff\xfe this line is not valid utf-8\n"
        b'{"event_type": "logoff", "user": "bob"}\n',
    ),
    (
        CsvTimelineAdapter(),
        b"event_type,user\n"
        b"logon,alice\n"
        b"\xff\xfe,not-utf8\n"
        b"logoff,bob\n",
    ),
    (
        SyslogAdapter(),
        b"Jan 12 03:04:05 host1 sshd[111]: Accepted publickey for alice\n"
        b"Jan 12 03:04:06 \xff\xfe bad bytes here\n"
        b"Jan 12 03:04:07 host1 sshd[112]: Accepted publickey for bob\n",
    ),
]
_BAD_BYTE_IDS = [adapter.adapter_id for adapter, _ in _BAD_BYTE_CASES]


@pytest.mark.parametrize("adapter,raw_bytes", _BAD_BYTE_CASES, ids=_BAD_BYTE_IDS)
def test_invalid_utf8_line_does_not_discard_the_rest_of_the_file(
    adapter, raw_bytes: bytes, tmp_path: Path
) -> None:
    suffix = {"jsonl": ".jsonl", "csv_timeline": ".csv", "syslog": ".syslog"}[adapter.adapter_id]
    path = tmp_path / f"mixed{suffix}"
    path.write_bytes(raw_bytes)

    results = list(adapter.ingest(SourceDescriptor(path=path), collected_at=NOW))

    # Exactly 3 lines/rows in the fixture -> 3 EvidenceItems, no exception,
    # no silently-dropped file.
    assert len(results) == 3

    # The two well-formed records (before and after the bad one) are still
    # normalized; only the middle, invalid-UTF8 one is evidence-only.
    normalized_flags = [normalized is not None for _evidence, normalized, _raw in results]
    assert normalized_flags == [True, False, True]


@pytest.mark.parametrize("adapter,raw_bytes", _BAD_BYTE_CASES, ids=_BAD_BYTE_IDS)
def test_invalid_utf8_evidence_is_still_exactly_content_addressed(
    adapter, raw_bytes: bytes, tmp_path: Path
) -> None:
    """The evidence-only record for the bad line must still be *real*
    evidence: its id must be the exact SHA-256 of its exact raw bytes,
    same as every other record -- not a placeholder or a lossy re-encoding.
    """
    suffix = {"jsonl": ".jsonl", "csv_timeline": ".csv", "syslog": ".syslog"}[adapter.adapter_id]
    path = tmp_path / f"mixed{suffix}"
    path.write_bytes(raw_bytes)

    results = list(adapter.ingest(SourceDescriptor(path=path), collected_at=NOW))
    bad_evidence = next(evidence for evidence, normalized, _raw in results if normalized is None)

    # Reconstruct the exact raw line bytes independently, and confirm the
    # evidence id is exactly sha256(those bytes) -- content-addressing is
    # unaffected by the fact that the bytes don't decode as UTF-8.
    physical_lines = raw_bytes.split(b"\n")
    bad_line = next(line for line in physical_lines if b"\xff\xfe" in line)
    assert bad_evidence.id == sha256_hex(bad_line)
    assert bad_evidence.raw_content_hash == bad_evidence.id


def test_ragged_csv_missing_value_is_not_the_string_none(tmp_path: Path) -> None:
    path = tmp_path / "ragged.csv"
    path.write_bytes(b"event_type,host,user\nlogon,h1,alice\nlogon,h2\n")

    results = list(CsvTimelineAdapter().ingest(SourceDescriptor(path=path), collected_at=NOW))
    short_row = results[1][1]
    assert short_row is not None
    assert "user" not in short_row.attributes  # omitted, not the string "None"
    assert short_row.attributes["host"] == "h2"


def test_ragged_csv_extra_columns_are_preserved_not_dropped(tmp_path: Path) -> None:
    path = tmp_path / "ragged.csv"
    path.write_bytes(b"event_type,host\nlogon,h1,extra1,extra2\n")

    results = list(CsvTimelineAdapter().ingest(SourceDescriptor(path=path), collected_at=NOW))
    row = results[0][1]
    assert row is not None
    assert row.attributes["_extra_columns"] == "extra1,extra2"
    assert row.attributes["host"] == "h1"
