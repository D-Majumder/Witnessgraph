"""BYTE_DISTINCT_SAME_SOURCE (ADVERSARIAL): two root EvidenceItems that
are intentionally byte-distinct but, per this fixture's own
independently declared ground truth, represent the same conceptual/
source record.

Diamond A -> {B, C} -> D. E1 is one authentication log line as exported
with a trailing newline; E2 is the exact same underlying record,
re-exported without one. E1.id != E2.id (their SHA-256 content hashes
differ), so Witnessgraph will correctly, mechanically report the two
chains as root-evidence-disjoint ("independent" at the provenance
level) -- but per this fixture's declared ground truth, they are NOT
independent observations of reality; they are one record, duplicated
during evidence handling.

This is a known, disclosed limitation, not a bug: root-evidence
disjointness is a content-hash property of the exact bytes ingested,
never a claim about real-world/source-level independence. See
``docs/research/wg-bench.md``'s "adversarial byte-distinct limitation"
section.
"""

from __future__ import annotations

from research.wg_bench.graph_builder import FixtureGraphBuilder
from research.wg_bench.model import BuiltFixture, ExpectedChain, GroundTruth
from witnessgraph.store.case import Case

FIXTURE_ID = "byte-distinct-same-source-01"
FIXTURE_CLASS = "BYTE_DISTINCT_SAME_SOURCE"

_RECORD_WITH_NEWLINE = b'{"event":"auth_success","user":"alice","host":"ws-1"}\n'
_RECORD_WITHOUT_NEWLINE = b'{"event":"auth_success","user":"alice","host":"ws-1"}'

GROUND_TRUTH = GroundTruth(
    fixture_id=FIXTURE_ID,
    fixture_class=FIXTURE_CLASS,
    description=(
        "Diamond A->{B,C}->D. Chain 'via B' roots to {E1}; chain 'via C' roots to "
        "{E2}. E1 and E2 are byte-distinct SHA-256 content hashes, but per this "
        "fixture's own declared ground truth they are the SAME underlying "
        "authentication log line, re-exported once with and once without a "
        "trailing newline."
    ),
    expected_shortest_path_count=2,
    expected_chains=(
        ExpectedChain(label="via B", root_evidence_labels=frozenset({"E1"})),
        ExpectedChain(label="via C", root_evidence_labels=frozenset({"E2"})),
    ),
    # At the content-hash (provenance) level these are, correctly and
    # mechanically, distinct/disjoint -- that is exactly the adversarial
    # point, not an error in this ground truth.
    root_sets_identical=False,
    root_sets_disjoint=True,
    root_sets_partial_overlap=False,
    is_adversarial=True,
    baseline_expected_classification="multiple_paths",
    provenance_expected_classification="independent",
    known_limitation=(
        "Witnessgraph reports these two chains as root-evidence independent because "
        "E1 and E2 are byte-distinct SHA-256 content hashes. Per this fixture's own "
        "declared ground truth, E1 and E2 are two re-exports of the same underlying "
        "authentication log line (one with, one without a trailing newline) and are "
        "NOT epistemically independent. Root-evidence disjointness is a "
        "provenance-level, content-hash property -- it does not, and cannot, verify "
        "real-world source-level independence."
    ),
    notes=(
        "WG-Bench's adversarial limitation fixture. The 'independent' verdict below "
        "is documented as correct per Witnessgraph's own (content-hash) provenance "
        "model, not as a bug to be fixed -- this fixture exists to make the "
        "boundary of that model's guarantee explicit and measured, never hidden."
    ),
)


def build(case: Case) -> BuiltFixture:
    g = FixtureGraphBuilder(case)
    g.evidence("E1", _RECORD_WITH_NEWLINE)
    g.evidence("E2", _RECORD_WITHOUT_NEWLINE)
    g.edge("A", "B", ("E1",))
    g.edge("B", "D", ("E1",))
    g.edge("A", "C", ("E2",))
    g.edge("C", "D", ("E2",))
    return BuiltFixture(
        source_entity_id=g.entity("A"),
        target_entity_id=g.entity("D"),
        evidence_by_label=g.evidence_by_label,
    )
