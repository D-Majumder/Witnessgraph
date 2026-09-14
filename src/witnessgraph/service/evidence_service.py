"""Resolve one evidence-lineage id (an EvidenceItem or NormalizedEvent).

Fills exactly as much of ``docs/phase-ui-v1-architecture-design.md`` §5
gap #3 as the first vertical slice actually needs: not a standalone
Evidence *browse* view (deferred -- see the milestone report), but the
one lookup the Entity detail panel's own provenance disclosure requires
-- resolving an ``Entity.derived_from`` id the same way a relationship's
``evidence_lineage`` already resolves ``Relationship.derived_from``,
via the exact same :func:`~witnessgraph.correlate.graph.resolve_evidence_ref`
the engine already uses for that.
"""

from __future__ import annotations

from witnessgraph.correlate.graph import resolve_evidence_ref, resolved_evidence_ref_to_json
from witnessgraph.store.case import Case


def resolve_evidence(case: Case, ref_id: str) -> dict[str, object]:
    """Resolve ``ref_id`` to its EvidenceItem/NormalizedEvent record.

    Never raises for an unknown id: a dangling ``derived_from`` reference
    is a real, documented possibility in this engine (``core/`` does not
    enforce referential integrity at construction time -- see
    ``correlate.graph.resolve_evidence_ref``'s own docstring), reported
    as ``{"kind": "not_found", ...}``, never a 404 -- this is a
    resolution *report*, not a resource lookup that can fail.
    """
    return resolved_evidence_ref_to_json(resolve_evidence_ref(case.store, ref_id))
