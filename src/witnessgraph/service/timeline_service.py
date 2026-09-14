"""Structured timeline -- a thin wrapper over ``correlate.timeline``."""

from __future__ import annotations

from witnessgraph.correlate.timeline import build_timeline_json
from witnessgraph.store.case import Case


def get_timeline(case: Case, *, event_type: str | None = None) -> list[dict[str, object]]:
    return build_timeline_json(case.store, event_type=event_type)
