"""V3 extension of ``research.wg_bench.v2.graph_builder.FixtureGraphBuilderV2``.

Adds exactly two capabilities V2's fixtures never needed, both required
to represent structural patterns V2 does not cover:

1. :meth:`chained_event` -- a ``NormalizedEvent`` whose own ``derived_from``
   names another ``NormalizedEvent`` (not an ``EvidenceItem`` directly),
   producing genuine N>1-level lineage (``Relationship -> Event -> Event
   -> ... -> EvidenceItem``). V2's own ``multi_level_lineage.py`` fixture
   states this is impossible under "any current ingest adapter" -- true
   for the adapters, but investigation for V3 (see
   ``docs/research/wg-bench.md`` V3 §3/§15) found nothing in
   ``core.events.NormalizedEvent`` (a bare, unvalidated ``tuple[str, ...]``
   field beyond a non-empty check) or ``correlate.graph._resolve_root_evidence_ids``
   (an explicit, cycle-safe BFS) that forbids it at the data-model level.
   This method constructs exactly that case directly against the store,
   the same way V2's ``event()`` already does for one-level events --
   still no production code modified, still the real ``NormalizedEvent.create``.

2. :meth:`dangling` -- registers a label for a syntactically valid but
   never-stored id (no ``EvidenceItem``, no ``NormalizedEvent`` created for
   it), for building fixtures that reference a dangling ``derived_from``
   id -- a case ``core/`` does not forbid (no referential integrity is
   enforced at construction time) and ``correlate.graph.resolve_evidence_ref``
   already documents handling via its ``"not_found"`` kind. Used by
   V3's ``DIRECT_REFERENCE_CONVERGENCE`` fixture to test whether a
   baseline that compares raw, unresolved ids can be fooled by a shared
   *dangling* id that contributes zero actual root evidence.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FIXTURE_TIME
from research.wg_bench.v2.graph_builder import FixtureGraphBuilderV2
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.ids import content_hash
from witnessgraph.store.case import Case


class FixtureGraphBuilderV3(FixtureGraphBuilderV2):
    def __init__(self, case: Case) -> None:
        super().__init__(case)

    def chained_event(
        self,
        label: str,
        *,
        event_type: str,
        derived_from_labels: tuple[str, ...],
        attributes: dict[str, str] | None = None,
    ) -> str:
        """Register (or fetch) a labeled ``NormalizedEvent`` whose
        ``derived_from`` may name evidence labels, other event labels
        (chaining N>1 levels deep), or a mix of both -- resolved against
        whichever registry actually has each label, via the inherited
        :meth:`_resolve_ref_label`.
        """
        if label not in self._event_by_label:
            derived_from = tuple(self._resolve_ref_label(ref) for ref in derived_from_labels)
            event = NormalizedEvent.create(
                event_type=event_type,
                attributes=attributes,
                derived_from=derived_from,
                created_at=FIXTURE_TIME,
            )
            self.case.store.put_normalized_event(event)
            self._event_by_label[label] = event.id
        return self._event_by_label[label]

    def dangling(self, label: str) -> str:
        """Register a label for a syntactically valid id that is never
        written to the store -- a stand-in for a malformed/dangling
        ``derived_from`` reference. Deterministic (content-hash of the
        label) so two independent builds of the same fixture still agree,
        preserving WG-Bench's determinism guarantee.
        """
        if label not in self._event_by_label:
            fake_id = "dangling-" + content_hash({"_type": "WgBenchV3Dangling", "label": label})
            self._event_by_label[label] = fake_id
        return self._event_by_label[label]
