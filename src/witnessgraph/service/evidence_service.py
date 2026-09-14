"""Evidence browsing and single-reference resolution.

Fills the rest of ``docs/phase-ui-v1-architecture-design.md`` §5 gap #3
that the first vertical slice deliberately left out (see
``docs/phase-ui-v1-implementation.md``'s deferred-items list from that
milestone): a standalone Evidence *browse* view now has a real list
endpoint to call, in addition to the single-reference resolution
(``resolve_evidence``) already used by the Entity/Relationship detail
panels' provenance disclosure.

``list_evidence`` deliberately reuses the same, smaller EvidenceItem
shape ``resolve_evidence``/every graph result's ``evidence_lineage``
already produce (id, source_adapter, adapter_version, source_locator,
raw_size_bytes, collected_at, observed_at) -- not
``report.render_json``'s separate, larger shape that additionally
includes ``chain_of_custody`` (that shape belongs to the whole-case
report, a different, already-existing view, per that module's own
documented distinction).
"""

from __future__ import annotations

from witnessgraph.correlate.graph import (
    evidence_item_to_json,
    resolve_evidence_ref,
    resolved_evidence_ref_to_json,
)
from witnessgraph.store.case import Case


def list_evidence(case: Case, *, source_adapter: str | None = None) -> list[dict[str, object]]:
    """Every EvidenceItem in ``case``, sorted by id, optionally filtered
    to one ``source_adapter``. Never exposes raw blob bytes or a
    filesystem path -- only the same metadata fields already returned by
    ``resolve_evidence``/graph-result provenance."""
    items = sorted(case.store.list_evidence(), key=lambda e: e.id)
    if source_adapter is not None:
        items = [item for item in items if item.source_adapter == source_adapter]
    return [evidence_item_to_json(item) for item in items]


def resolve_evidence(case: Case, ref_id: str) -> dict[str, object]:
    """Resolve ``ref_id`` to its EvidenceItem/NormalizedEvent record.

    Never raises for an unknown id: a dangling ``derived_from`` reference
    is a real, documented possibility in this engine (``core/`` does not
    enforce referential integrity at construction time -- see
    ``correlate.graph.resolve_evidence_ref``'s own docstring), reported
    as ``{"kind": "not_found", ...}``, never a 404 -- this is a
    resolution *report*, not a resource lookup that can fail. Also used
    as the Evidence-browse view's own "detail" fetch: a ref_id taken from
    ``list_evidence``'s own output always resolves to ``kind:
    "evidence_item"``.
    """
    return resolved_evidence_ref_to_json(resolve_evidence_ref(case.store, ref_id))
