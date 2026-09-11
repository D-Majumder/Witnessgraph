"""Shared contract every built-in EvidenceAdapter must satisfy."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from witnessgraph.ingest.adapters.csv_timeline_adapter import CsvTimelineAdapter
from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
from witnessgraph.ingest.adapters.syslog_adapter import SyslogAdapter
from witnessgraph.ingest.base import SourceDescriptor

FIXTURES = Path(__file__).parent.parent / "fixtures"
NOW = datetime(2026, 1, 1, tzinfo=UTC)

ADAPTER_CASES = [
    (JsonlAdapter(), FIXTURES / "sample_events.jsonl"),
    (CsvTimelineAdapter(), FIXTURES / "sample_timeline.csv"),
    (SyslogAdapter(), FIXTURES / "sample.syslog"),
]
ADAPTER_IDS = [a.adapter_id for a, _ in ADAPTER_CASES]
all_adapters = pytest.mark.parametrize("adapter,source_path", ADAPTER_CASES, ids=ADAPTER_IDS)

# CSV rows are structurally always normalizable (every column becomes an
# attribute, however sparse), unlike JSONL/syslog lines which can fail to
# parse entirely -- so the "some evidence has no NormalizedEvent" property
# below intentionally does not apply to csv_timeline.
ADAPTER_CASES_WITH_UNPARSEABLE_LINES = [
    (a, p) for a, p in ADAPTER_CASES if a.adapter_id != "csv_timeline"
]
UNPARSEABLE_IDS = [a.adapter_id for a, _ in ADAPTER_CASES_WITH_UNPARSEABLE_LINES]
adapters_with_unparseable_lines = pytest.mark.parametrize(
    "adapter,source_path", ADAPTER_CASES_WITH_UNPARSEABLE_LINES, ids=UNPARSEABLE_IDS
)


@all_adapters
def test_can_handle_its_own_fixture(adapter, source_path: Path) -> None:
    assert adapter.can_handle(SourceDescriptor(path=source_path))


@all_adapters
def test_ingest_yields_at_least_one_evidence_item(adapter, source_path: Path) -> None:
    source = SourceDescriptor(path=source_path)
    results = list(adapter.ingest(source, collected_at=NOW))
    assert len(results) > 0
    for evidence, _normalized in results:
        assert evidence.source_adapter == adapter.adapter_id
        assert evidence.adapter_version == adapter.adapter_version


@all_adapters
def test_ingest_yields_at_least_one_normalized_event(adapter, source_path: Path) -> None:
    """Every built-in adapter's fixture contains at least one line it can normalize."""
    source = SourceDescriptor(path=source_path)
    results = list(adapter.ingest(source, collected_at=NOW))
    assert any(normalized is not None for _evidence, normalized in results)


@adapters_with_unparseable_lines
def test_unparseable_lines_still_become_evidence(adapter, source_path: Path) -> None:
    """Every jsonl/syslog fixture contains one deliberately unparseable line
    (see SECURITY.md / DESIGN.md principle 1: evidence is preserved even
    when it cannot be normalized)."""
    source = SourceDescriptor(path=source_path)
    results = list(adapter.ingest(source, collected_at=NOW))
    assert any(normalized is None for _evidence, normalized in results)


@all_adapters
def test_ingest_is_deterministic(adapter, source_path: Path) -> None:
    source = SourceDescriptor(path=source_path)
    run_1 = [e.id for e, _ in adapter.ingest(source, collected_at=NOW)]
    run_2 = [e.id for e, _ in adapter.ingest(source, collected_at=NOW)]
    assert run_1 == run_2


@all_adapters
def test_every_normalized_event_traces_back_to_its_evidence(adapter, source_path: Path) -> None:
    source = SourceDescriptor(path=source_path)
    for evidence, normalized in adapter.ingest(source, collected_at=NOW):
        if normalized is not None:
            assert evidence.id in normalized.derived_from
