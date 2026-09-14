"""Structured, machine-readable timeline: NormalizedEvents in time order.

Fills the gap identified in ``docs/phase-ui-v1-architecture-design.md``
§5 gap #4: before this module, the only structured (JSON) path to
normalized-event + time-assertion data was the whole-case report tree
(``report.render_json.build_report_json_tree``'s ``timeline`` array);
the ``timeline`` CLI command itself was text-only.

No second temporal model: this reads existing public attributes of
``NormalizedEvent``/``TimeAssertion`` directly and builds a plain
dict/list tree -- the exact same shape
``report.render_json._build_timeline`` already produced, moved here so
both the report renderer and ``witnessgraph.service`` share one
implementation instead of two. Sort key, field selection, and ordering
are unchanged from before this module existed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.time_model import TimeAssertion
from witnessgraph.store.base import Store


def _timeline_sort_key(
    event: NormalizedEvent, assertions_by_event: dict[str, list[TimeAssertion]]
) -> datetime:
    times = assertions_by_event.get(event.id, [])
    return min((a.value for a in times), default=event.created_at)


def build_timeline_json(store: Store, *, event_type: str | None = None) -> list[dict[str, Any]]:
    """Every ``NormalizedEvent`` in ``store``, earliest-known-time first.

    Mirrors ``timeline``'s own sort key exactly: the minimum
    ``TimeAssertion.value`` recorded for that event, or the event's own
    ``created_at`` when it has none. ``event_type`` (optional) filters
    the returned entries to one type -- a display filter only, applied
    after sorting, never changing which events are considered or their
    relative order.
    """
    assertions_by_event: dict[str, list[TimeAssertion]] = {}
    for assertion in store.list_time_assertions():
        assertions_by_event.setdefault(assertion.subject_event_id, []).append(assertion)

    events = sorted(
        store.list_normalized_events(),
        key=lambda e: (_timeline_sort_key(e, assertions_by_event), e.id),
    )
    if event_type is not None:
        events = [e for e in events if e.event_type == event_type]

    result = []
    for event in events:
        assertions = sorted(assertions_by_event.get(event.id, []), key=lambda a: a.id)
        result.append(
            {
                "id": event.id,
                "event_type": event.event_type,
                "entity_ids": list(event.entity_ids),
                "derived_from": list(event.derived_from),
                "attributes": dict(event.attributes),
                "time_assertions": [
                    {
                        "id": a.id,
                        "value": a.value,
                        "precision": a.precision.value,
                        "asserted_by": a.asserted_by,
                        "source_evidence_id": a.source_evidence_id,
                    }
                    for a in assertions
                ],
            }
        )
    return result
