"""Shared data model for WG-Bench: ground truth, built fixtures, and the
registered-fixture record.

Every ``GroundTruth`` field is hand-authored by reasoning about a
fixture's intended graph topology -- never by running
``find_all_shortest_paths``/``analyze_paths_evidence_overlap`` and
copying back what they return. ``research.wg_bench.evaluation`` is the
only place ground truth and actual Witnessgraph output are ever compared
against each other, and it keeps them in physically separate dataclasses
so a reader can never mistake one for the other.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from witnessgraph.store.case import Case


@dataclass(frozen=True)
class ExpectedChain:
    """One shortest-path chain a fixture's author expects to exist.

    ``label`` is a human-readable name for this chain (e.g. ``"via B"``),
    never used for matching -- comparison against actual output is by
    root evidence *set*, order-independent (see
    ``research.wg_bench.evaluation``). ``root_evidence_labels`` are
    *symbolic* labels (e.g. ``"E1"``), resolved to real, content-derived
    ``EvidenceItem`` ids only once a fixture's ``build()`` function has
    actually run -- see ``BuiltFixture.evidence_by_label``.
    """

    label: str
    root_evidence_labels: frozenset[str]


@dataclass(frozen=True)
class GroundTruth:
    """Independently-authored ground truth for one WG-Bench fixture."""

    fixture_id: str
    fixture_class: str
    description: str

    expected_shortest_path_count: int
    expected_chains: tuple[ExpectedChain, ...]

    #: Whether every expected chain's root evidence set is identical to
    #: every other's. ``None`` when fewer than 2 chains are expected --
    #: the comparison does not apply.
    root_sets_identical: bool | None
    #: Whether *every pair* of expected chains' root evidence sets is
    #: disjoint -- the "fully independent" question
    #: ``fully_evidence_independent`` answers. ``None`` when fewer than
    #: 2 chains are expected.
    root_sets_disjoint: bool | None
    #: True whenever at least one pair of expected chains shares some,
    #: but not all, root evidence -- neither fully identical nor fully
    #: disjoint. Always False when fewer than 2 chains are expected.
    root_sets_partial_overlap: bool

    #: True for a fixture deliberately designed to probe a known
    #: limitation of Witnessgraph's provenance model (see
    #: BYTE_DISTINCT_SAME_SOURCE) rather than to test ordinary,
    #: expected-correct behavior.
    is_adversarial: bool

    #: The classification this fixture's author expects the path-count-
    #: only baseline (``research.wg_bench.baseline``) to produce.
    baseline_expected_classification: str
    #: The verdict this fixture's author expects
    #: ``analyze_paths_evidence_overlap`` to produce, expressed as
    #: ``"independent"`` / ``"not_independent"`` / ``"not_applicable"``
    #: -- mirroring ``fully_evidence_independent``'s True/False/None.
    provenance_expected_classification: str

    #: A human-readable description of a known representational
    #: limitation this fixture is designed to expose (the boolean
    #: verdict's information loss for partial overlap, or the gap
    #: between provenance-level and epistemic independence). ``None``
    #: when this fixture exposes no such limitation.
    known_limitation: str | None
    #: Free-text explanation of the reasoning behind this fixture's
    #: ground truth, for a human auditor.
    notes: str


@dataclass(frozen=True)
class BuiltFixture:
    """The concrete graph one fixture's ``build()`` function produced in
    a real ``Case``, plus the symbolic-label -> real-id mapping needed to
    translate ``GroundTruth``'s labels into ids comparable against
    Witnessgraph's actual output."""

    source_entity_id: str
    target_entity_id: str
    evidence_by_label: dict[str, str]


BuildFn = Callable[[Case], BuiltFixture]


@dataclass(frozen=True)
class Fixture:
    """One registered WG-Bench fixture: its ground truth plus the
    function that builds its graph into a fresh, empty ``Case``."""

    ground_truth: GroundTruth
    build: BuildFn
