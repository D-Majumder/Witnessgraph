"""Determinism/byte-level tests for witnessgraph.report.render.

Covers: repeated-rendering determinism, insertion-order independence,
Unicode bidi/zero-width/control-character neutralization, opaque
path-like string rendering, UTF-8 validity, and the zero-CR-byte
invariant -- see docs/phase2-v0.2-spec.md §7/§12/§13 and the approved
Revision 2 implementation plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import EvidenceRef, Hypothesis
from witnessgraph.core.provenance import compute_manifest
from witnessgraph.core.relationships import Relationship
from witnessgraph.core.time_model import TimeAssertion, TimePrecision
from witnessgraph.core.tracked_finding import FindingStatus, TrackedGapFinding
from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction
from witnessgraph.report.render import render_report, render_report_bytes

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@dataclass
class _FakeStore:
    """A minimal, hand-built Store fake that preserves raw insertion order
    (unlike SqliteStore, which already orders by id at the SQL level) so
    that order-independence tests exercise render.py's own sorting, not
    the underlying store's incidental behavior."""

    evidence: dict[str, EvidenceItem] = field(default_factory=dict)
    events: dict[str, NormalizedEvent] = field(default_factory=dict)
    entities: dict[str, Entity] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    time_assertions: dict[str, TimeAssertion] = field(default_factory=dict)
    hypotheses: dict[str, Hypothesis] = field(default_factory=dict)
    tracked_findings: dict[str, TrackedGapFinding] = field(default_factory=dict)
    tracked_contradictions: dict[str, TrackedTimeContradiction] = field(default_factory=dict)

    def put_evidence(self, item: EvidenceItem) -> None:
        self.evidence[item.id] = item

    def get_evidence(self, id: str) -> EvidenceItem | None:
        return self.evidence.get(id)

    def list_evidence(self) -> list[EvidenceItem]:
        return list(self.evidence.values())

    def put_normalized_event(self, event: NormalizedEvent) -> None:
        self.events[event.id] = event

    def get_normalized_event(self, id: str) -> NormalizedEvent | None:
        return self.events.get(id)

    def list_normalized_events(self) -> list[NormalizedEvent]:
        return list(self.events.values())

    def put_entity(self, entity: Entity) -> None:
        self.entities[entity.id] = entity

    def get_entity(self, id: str) -> Entity | None:
        return self.entities.get(id)

    def list_entities(self) -> list[Entity]:
        return list(self.entities.values())

    def put_relationship(self, relationship: Relationship) -> None:
        self.relationships[relationship.id] = relationship

    def get_relationship(self, id: str) -> Relationship | None:
        return self.relationships.get(id)

    def list_relationships(self) -> list[Relationship]:
        return list(self.relationships.values())

    def put_time_assertion(self, assertion: TimeAssertion) -> None:
        self.time_assertions[assertion.id] = assertion

    def get_time_assertion(self, id: str) -> TimeAssertion | None:
        return self.time_assertions.get(id)

    def list_time_assertions(self) -> list[TimeAssertion]:
        return list(self.time_assertions.values())

    def put_hypothesis(self, hypothesis: Hypothesis) -> None:
        self.hypotheses[hypothesis.id] = hypothesis

    def get_hypothesis(self, id: str) -> Hypothesis | None:
        return self.hypotheses.get(id)

    def list_hypotheses(self) -> list[Hypothesis]:
        return list(self.hypotheses.values())

    def create_tracked_finding(self, finding: TrackedGapFinding) -> TrackedGapFinding:
        existing = self.tracked_findings.get(finding.id)
        if existing is not None:
            return existing
        self.tracked_findings[finding.id] = finding
        return finding

    def annotate_tracked_finding(
        self,
        id: str,
        *,
        status: FindingStatus,
        annotated_by: str,
        annotated_at: datetime,
        note: str | None,
    ) -> TrackedGapFinding:
        existing = self.tracked_findings.get(id)
        if existing is None:
            raise ValueError(f"no tracked finding {id!r} to annotate")
        updated = existing.with_annotation(
            status=status, annotated_by=annotated_by, annotated_at=annotated_at, note=note
        )
        self.tracked_findings[id] = updated
        return updated

    def get_tracked_finding(self, id: str) -> TrackedGapFinding | None:
        return self.tracked_findings.get(id)

    def list_tracked_findings(self) -> list[TrackedGapFinding]:
        return list(self.tracked_findings.values())

    def create_tracked_contradiction(
        self, contradiction: TrackedTimeContradiction
    ) -> TrackedTimeContradiction:
        existing = self.tracked_contradictions.get(contradiction.id)
        if existing is not None:
            return existing
        self.tracked_contradictions[contradiction.id] = contradiction
        return contradiction

    def annotate_tracked_contradiction(
        self,
        id: str,
        *,
        status: FindingStatus,
        annotated_by: str,
        annotated_at: datetime,
        note: str | None,
    ) -> TrackedTimeContradiction:
        existing = self.tracked_contradictions.get(id)
        if existing is None:
            raise ValueError(f"no tracked contradiction {id!r} to annotate")
        updated = existing.with_annotation(
            status=status, annotated_by=annotated_by, annotated_at=annotated_at, note=note
        )
        self.tracked_contradictions[id] = updated
        return updated

    def get_tracked_contradiction(self, id: str) -> TrackedTimeContradiction | None:
        return self.tracked_contradictions.get(id)

    def list_tracked_contradictions(self) -> list[TrackedTimeContradiction]:
        return list(self.tracked_contradictions.values())

    def close(self) -> None:
        pass


def _fixed_object_set() -> tuple[EvidenceItem, NormalizedEvent, Entity, TimeAssertion, Hypothesis]:
    evidence = EvidenceItem.create(
        raw_bytes=b"fixed content",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="fixed.log:1",
        collected_at=NOW,
    )
    event = NormalizedEvent(
        id="11111111-1111-1111-1111-111111111111",
        event_type="fixed_event",
        derived_from=(evidence.id,),
        created_at=NOW,
    )
    entity = Entity(
        id="22222222-2222-2222-2222-222222222222",
        entity_type="host",
        identifiers={"hostname": "fixed-host"},
        derived_from=(evidence.id,),
    )
    assertion = TimeAssertion(
        id="33333333-3333-3333-3333-333333333333",
        subject_event_id=event.id,
        value=NOW,
        precision=TimePrecision.EXACT,
        source_evidence_id=evidence.id,
        asserted_by="adapter:jsonl",
        created_at=NOW,
    )
    hypothesis = Hypothesis(
        id="44444444-4444-4444-4444-444444444444",
        statement="fixed statement",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=evidence.id),),
        inferred_by="analyst:test",
        created_at=NOW,
    )
    return evidence, event, entity, assertion, hypothesis


def _render_for(store: _FakeStore) -> str:
    manifest = compute_manifest(store)
    return render_report(
        case_name="x", store=store, recomputed_manifest=manifest, recorded_manifest=None
    )


def test_render_report_is_deterministic_across_repeated_calls() -> None:
    store = _FakeStore()
    evidence, event, entity, assertion, hypothesis = _fixed_object_set()
    store.put_evidence(evidence)
    store.put_normalized_event(event)
    store.put_entity(entity)
    store.put_time_assertion(assertion)
    store.put_hypothesis(hypothesis)

    first = _render_for(store)
    second = _render_for(store)
    assert first == second


def test_render_report_is_order_independent() -> None:
    """Two stores holding identical object ids/field values, populated in
    different insertion orders, must render byte-identical output."""
    evidence, event, entity, assertion, hypothesis = _fixed_object_set()

    store_a = _FakeStore()
    store_a.put_hypothesis(hypothesis)
    store_a.put_entity(entity)
    store_a.put_evidence(evidence)
    store_a.put_normalized_event(event)
    store_a.put_time_assertion(assertion)

    store_b = _FakeStore()
    store_b.put_evidence(evidence)
    store_b.put_time_assertion(assertion)
    store_b.put_normalized_event(event)
    store_b.put_entity(entity)
    store_b.put_hypothesis(hypothesis)

    assert _render_for(store_a) == _render_for(store_b)


def test_render_report_bytes_is_utf8_and_lf_only() -> None:
    store = _FakeStore()
    evidence, event, entity, assertion, hypothesis = _fixed_object_set()
    store.put_evidence(evidence)
    manifest = compute_manifest(store)
    report_bytes = render_report_bytes(
        case_name="x", store=store, recomputed_manifest=manifest, recorded_manifest=None
    )
    assert b"\r" not in report_bytes
    decoded = report_bytes.decode("utf-8")  # must not raise
    assert decoded.encode("utf-8") == report_bytes


def test_unicode_bidi_control_is_neutralized() -> None:
    store = _FakeStore()
    evidence, event, entity, assertion, _unused = _fixed_object_set()
    hypothesis = Hypothesis(
        id="55555555-5555-5555-5555-555555555555",
        statement="the attacker used a RLO\u202e character",
        supporting_evidence=(EvidenceRef(kind="evidence_item", id=evidence.id),),
        inferred_by="analyst:test",
        created_at=NOW,
    )
    store.put_evidence(evidence)
    store.put_hypothesis(hypothesis)
    report = _render_for(store)
    assert "\u202e" not in report
    assert "\\u202E" in report


def test_unicode_zero_width_is_neutralized() -> None:
    store = _FakeStore()
    evidence, event, entity, assertion, _unused = _fixed_object_set()
    entity2 = Entity(
        id="66666666-6666-6666-6666-666666666666",
        entity_type="host",
        identifiers={"hostname": "wo\u200brkstation"},
        derived_from=(evidence.id,),
    )
    store.put_evidence(evidence)
    store.put_entity(entity2)
    report = _render_for(store)
    assert "\u200b" not in report
    assert "\\u200B" in report


def test_embedded_cr_in_untrusted_value_is_neutralized() -> None:
    store = _FakeStore()
    evidence = EvidenceItem.create(
        raw_bytes=b"data",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="path/with\rcarriage.log:1",
        collected_at=NOW,
    )
    store.put_evidence(evidence)
    manifest = compute_manifest(store)
    report_bytes = render_report_bytes(
        case_name="x", store=store, recomputed_manifest=manifest, recorded_manifest=None
    )
    assert b"\r" not in report_bytes
    assert b"\\u000D" in report_bytes


def test_source_locator_windows_style_path_rendered_verbatim() -> None:
    """source_locator must render exactly as stored -- never reprocessed
    through pathlib/os.path, so backslashes survive unchanged."""
    store = _FakeStore()
    evidence = EvidenceItem.create(
        raw_bytes=b"data",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator=r"C:\Users\alice\case\events.jsonl:12",
        collected_at=NOW,
    )
    store.put_evidence(evidence)
    report = _render_for(store)
    assert r"C:\Users\alice\case\events.jsonl:12" in report


def test_code_span_fencing_survives_embedded_backticks() -> None:
    store = _FakeStore()
    evidence = EvidenceItem.create(
        raw_bytes=b"data",
        source_adapter="jsonl",
        adapter_version="0.1.0",
        source_locator="path``with``backticks",
        collected_at=NOW,
    )
    store.put_evidence(evidence)
    report = _render_for(store)
    assert "path``with``backticks" in report
