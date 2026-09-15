"""Shared data model for WG-Bench V2.

V2 keeps V1's core discipline -- ground truth is hand-authored by
reasoning about a fixture's intended topology, kept in a physically
separate dataclass from what the runner actually observes -- and extends
it with a second, distinct evidence-set concept: **direct** evidence/event
references (the raw, unresolved ids a chain's relationships cite) versus
**root** evidence references (V1's concept: what those ids resolve down to
after following any ``NormalizedEvent`` indirection). Collapsing these two
into one field would silently re-introduce exactly the ambiguity V2 exists
to measure -- see ``docs/research/wg-bench.md``'s V2 section, item A/B/C/D
distinction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from witnessgraph.store.case import Case


@dataclass(frozen=True)
class ExpectedChainV2:
    """One shortest-path chain a V2 fixture's author expects to exist.

    ``direct_reference_labels`` are the symbolic labels of the raw,
    unresolved ids every relationship on this chain cites via
    ``derived_from`` -- may name evidence labels, event labels, or both.
    ``root_evidence_labels`` are V1's existing concept: what those ids
    resolve to after following any ``NormalizedEvent`` indirection down to
    root ``EvidenceItem`` ids. For a fixture with no ``NormalizedEvent``
    indirection at all (as in every V1 fixture), the two are identical by
    construction; V2's new fixtures are specifically the ones where they
    diverge.
    """

    label: str
    direct_reference_labels: frozenset[str]
    root_evidence_labels: frozenset[str]


@dataclass(frozen=True)
class GroundTruthV2:
    """Independently-authored ground truth for one WG-Bench V2 fixture."""

    fixture_id: str
    fixture_class: str
    description: str

    expected_shortest_path_count: int
    expected_chains: tuple[ExpectedChainV2, ...]

    #: Whether every pair of expected chains' *direct* (unresolved)
    #: reference sets is disjoint. None when fewer than 2 chains.
    direct_sets_disjoint: bool | None
    #: Whether every pair of expected chains' *root* (resolved) evidence
    #: sets is disjoint -- V1's existing concept, the question
    #: ``analyze_paths_evidence_overlap``'s ``fully_evidence_independent``
    #: answers. None when fewer than 2 chains.
    root_sets_disjoint: bool | None
    #: True whenever at least one pair of expected chains shares some, but
    #: not all, root evidence. Always False when fewer than 2 chains.
    root_sets_partial_overlap: bool

    #: True for a fixture deliberately designed to probe a known
    #: limitation of Witnessgraph's provenance model (e.g.
    #: BYTE_DISTINCT_SAME_SOURCE) rather than to test ordinary, expected-
    #: correct behavior.
    is_adversarial: bool
    #: Conceptual/source-identity groups, independently declared as
    #: benchmark metadata ONLY -- never derived from any method's output,
    #: never fed back into any classification. Each inner frozenset is a
    #: set of chain labels the fixture author judges to represent the
    #: *same* real-world source/record, independent of what root evidence
    #: id(s) they happen to cite. None for fixtures making no such claim.
    #: See docs/research/wg-bench.md V2 §16 for why this must never
    #: become a production inference.
    conceptual_source_groups: tuple[frozenset[str], ...] | None

    #: A human-readable description of a known representational
    #: limitation this fixture is designed to expose. None if none.
    known_limitation: str | None
    #: Free-text explanation of the reasoning behind this fixture's
    #: ground truth, for a human auditor.
    notes: str


@dataclass(frozen=True)
class BuiltFixtureV2:
    """The concrete graph one V2 fixture's ``build()`` function produced,
    plus both label->id maps needed to translate ``GroundTruthV2``'s
    labels into ids comparable against actual output."""

    source_entity_id: str
    target_entity_id: str
    evidence_by_label: dict[str, str]
    event_by_label: dict[str, str]

    def resolve_ref_label(self, label: str) -> str:
        if label in self.evidence_by_label:
            return self.evidence_by_label[label]
        return self.event_by_label[label]


BuildFnV2 = Callable[[Case], BuiltFixtureV2]


@dataclass(frozen=True)
class FixtureV2:
    """One registered WG-Bench V2 fixture: its ground truth plus the
    function that builds its graph into a fresh, empty ``Case``."""

    ground_truth: GroundTruthV2
    build: BuildFnV2
