"""In-process adapter registry.

Design note: the Phase-0 sketch of this project favored entry-points-
based discovery, so third-party packages could register adapters without
forking core. For v0.1, an explicit in-process registry was chosen
instead -- it is simpler to reason about and test in this environment,
and upgrading to entry-points discovery later is a small, additive
change (this module's public functions would not need to change shape).
"""

from __future__ import annotations

from witnessgraph.ingest.base import EvidenceAdapter

_REGISTRY: dict[str, EvidenceAdapter] = {}


def register_adapter(adapter: EvidenceAdapter) -> None:
    _REGISTRY[adapter.adapter_id] = adapter


def get_adapter(adapter_id: str) -> EvidenceAdapter:
    try:
        return _REGISTRY[adapter_id]
    except KeyError as exc:
        known = sorted(_REGISTRY)
        raise KeyError(f"no adapter registered as {adapter_id!r}; known: {known}") from exc


def list_adapters() -> list[str]:
    return sorted(_REGISTRY)


def _register_builtin_adapters() -> None:
    from witnessgraph.ingest.adapters.csv_timeline_adapter import CsvTimelineAdapter
    from witnessgraph.ingest.adapters.jsonl_adapter import JsonlAdapter
    from witnessgraph.ingest.adapters.syslog_adapter import SyslogAdapter

    for adapter_cls in (JsonlAdapter, CsvTimelineAdapter, SyslogAdapter):
        register_adapter(adapter_cls())


_register_builtin_adapters()
