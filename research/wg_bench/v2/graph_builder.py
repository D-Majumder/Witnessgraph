"""V2 extension of ``research.wg_bench.graph_builder.FixtureGraphBuilder``
that adds ``NormalizedEvent`` construction, needed to build fixtures with
multi-level ``derived_from`` lineage (Relationship -> NormalizedEvent ->
EvidenceItem) rather than V1's exclusively single-level
(Relationship -> EvidenceItem) fixtures.

Not itself part of Witnessgraph's production code path -- exactly like
V1's builder, every method here only calls existing, unmodified
``Store``/core-model constructors (``NormalizedEvent.create`` in
addition to V1's ``Entity``/``EvidenceItem.create``/``Relationship.create``).
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FIXTURE_TIME, FixtureGraphBuilder
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.relationships import Relationship
from witnessgraph.store.case import Case


class FixtureGraphBuilderV2(FixtureGraphBuilder):
    """Adds :meth:`event` (a labeled ``NormalizedEvent``, one indirection
    level above an ``EvidenceItem``) and lets :meth:`edge` cite either
    evidence labels or event labels interchangeably in
    ``derived_from_labels`` -- exactly as a real ``Relationship.derived_from``
    id can name either kind of record (see ``correlate.graph``'s
    ``_resolve_root_evidence_ids`` docstring).
    """

    def __init__(self, case: Case) -> None:
        super().__init__(case)
        self._event_by_label: dict[str, str] = {}

    def event(
        self,
        label: str,
        *,
        event_type: str,
        derived_from_evidence_labels: tuple[str, ...],
        attributes: dict[str, str] | None = None,
    ) -> str:
        """Register (or fetch) a labeled ``NormalizedEvent``, derived from
        one or more already-registered evidence labels.

        Two calls with identical ``event_type``/``attributes``/resolved
        ``derived_from`` collapse to the same id, exactly as
        ``NormalizedEvent.create`` already guarantees (content-derived
        identity) -- mirroring how :meth:`FixtureGraphBuilder.evidence`
        already documents the same collapsing behavior for byte-identical
        evidence.
        """
        if label not in self._event_by_label:
            derived_from = tuple(
                self._evidence_by_label[ref_label] for ref_label in derived_from_evidence_labels
            )
            event = NormalizedEvent.create(
                event_type=event_type,
                attributes=attributes,
                derived_from=derived_from,
                created_at=FIXTURE_TIME,
            )
            self.case.store.put_normalized_event(event)
            self._event_by_label[label] = event.id
        return self._event_by_label[label]

    def edge(
        self,
        source: str,
        target: str,
        derived_from_labels: tuple[str, ...],
        *,
        relationship_type: str = "connected_to",
    ) -> str:
        """As :meth:`FixtureGraphBuilder.edge`, but ``derived_from_labels``
        may name either an evidence label (see :meth:`evidence`) or an
        event label (see :meth:`event`) -- resolved against whichever
        registry actually has it, exactly as a real ``Relationship``'s
        ``derived_from`` can point at either kind of record.
        """
        derived_from = tuple(self._resolve_ref_label(label) for label in derived_from_labels)
        rel = Relationship.create(
            relationship_type=relationship_type,
            source_entity_id=self.entity(source),
            target_entity_id=self.entity(target),
            derived_from=derived_from,
            created_at=FIXTURE_TIME,
        )
        self.case.store.put_relationship(rel)
        return rel.id

    def _resolve_ref_label(self, label: str) -> str:
        if label in self._evidence_by_label:
            return self._evidence_by_label[label]
        if label in self._event_by_label:
            return self._event_by_label[label]
        raise KeyError(f"Unknown evidence/event label: {label!r}")

    @property
    def event_by_label(self) -> dict[str, str]:
        """A snapshot of every event label registered so far."""
        return dict(self._event_by_label)
