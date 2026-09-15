"""Shared, deterministic graph-construction helper for WG-Bench fixtures.

Mirrors the ``_Graph`` test helper in ``tests/unit/test_graph.py``:
entity ids are deterministic (``entity-<name>``), not random, so two
independently built copies of the same fixture are directly comparable
-- required by WG-Bench's deterministic-replay check (H2, see
``research.wg_bench.evaluation``). Evidence identity is never invented
here: every ``EvidenceItem`` id is the real SHA-256 content hash
Witnessgraph's own ``EvidenceItem.create`` computes from the exact bytes
passed to :meth:`FixtureGraphBuilder.evidence`, exactly as it would be
for genuinely ingested evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime

from witnessgraph.core.entities import Entity
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.relationships import Relationship
from witnessgraph.store.case import Case

#: Fixed, arbitrary timestamp for every object WG-Bench constructs.
#: Never part of any identity hash Witnessgraph computes (see
#: ``NormalizedEvent``/``Relationship``/``TimeAssertion``'s own
#: ``identity_hash`` methods, which all exclude ``created_at``), so its
#: exact value has no bearing on determinism -- it exists only because
#: the object constructors require *some* timestamp.
FIXTURE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


class FixtureGraphBuilder:
    """Builds one fixture's entities/relationships into a real ``Case``.

    Not itself part of Witnessgraph's production code path -- every
    method here only calls existing, unmodified ``Store``/core-model
    constructors (``Entity``, ``EvidenceItem.create``,
    ``Relationship.create``), exactly as a real ingest adapter or the CLI
    would.
    """

    def __init__(self, case: Case) -> None:
        self.case = case
        self._entities: dict[str, str] = {}
        self._evidence_by_label: dict[str, str] = {}

    def entity(self, name: str) -> str:
        """Deterministic id per name (``entity-<name>``), created once."""
        if name not in self._entities:
            entity_id = f"entity-{name}"
            self.case.store.put_entity(
                Entity(
                    id=entity_id,
                    entity_type="node",
                    identifiers={"name": name},
                    derived_from=(self._structural_placeholder(),),
                )
            )
            self._entities[name] = entity_id
        return self._entities[name]

    def _structural_placeholder(self) -> str:
        """A trivial, shared ``EvidenceItem`` id used only to satisfy
        ``Entity.derived_from``'s non-empty-lineage requirement.

        Entity lineage plays no role in path/evidence-overlap analysis
        (only *relationship* ``derived_from`` does); using one fixed
        placeholder here, instead of the fixture's own labeled evidence,
        keeps entity construction visibly separate from the evidence a
        fixture's ground truth actually reasons about via
        :meth:`evidence`.
        """
        return self.evidence("_entity_lineage_placeholder", b"wg-bench:structural-placeholder")

    def evidence(self, label: str, raw_bytes: bytes) -> str:
        """Register (or fetch) a labeled ``EvidenceItem``.

        Two calls with the same ``raw_bytes`` -- even under different
        labels -- collapse to the same ``EvidenceItem.id``, exactly as
        real ingestion would (content addressing, DESIGN.md principle
        1). This is deliberately never hidden: the BYTE_DISTINCT_SAME_SOURCE
        fixture specifically exploits the opposite case (different
        bytes, same declared conceptual source) to demonstrate a known
        limitation, not to work around it.
        """
        if label not in self._evidence_by_label:
            item = EvidenceItem.create(
                raw_bytes=raw_bytes,
                source_adapter="wg_bench",
                adapter_version="0.0.0",
                source_locator=f"wg_bench:{label}",
                collected_at=FIXTURE_TIME,
            )
            self.case.store.put_evidence(item)
            self._evidence_by_label[label] = item.id
        return self._evidence_by_label[label]

    def edge(
        self,
        source: str,
        target: str,
        derived_from_labels: tuple[str, ...],
        *,
        relationship_type: str = "connected_to",
    ) -> str:
        """A directed relationship ``source -> target``, citing the
        already-registered evidence labels named in
        ``derived_from_labels`` (see :meth:`evidence`)."""
        derived_from = tuple(self._evidence_by_label[label] for label in derived_from_labels)
        rel = Relationship.create(
            relationship_type=relationship_type,
            source_entity_id=self.entity(source),
            target_entity_id=self.entity(target),
            derived_from=derived_from,
            created_at=FIXTURE_TIME,
        )
        self.case.store.put_relationship(rel)
        return rel.id

    @property
    def evidence_by_label(self) -> dict[str, str]:
        """A snapshot of every label registered so far, excluding the
        internal entity-lineage placeholder -- a fixture's ground truth
        never references that label."""
        return {
            label: eid
            for label, eid in self._evidence_by_label.items()
            if label != "_entity_lineage_placeholder"
        }
