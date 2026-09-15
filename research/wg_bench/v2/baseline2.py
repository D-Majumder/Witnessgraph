"""BASELINE 2: direct evidence-reference comparison.

The strongest non-recursive baseline: for each returned chain, builds the
set of *direct*, unresolved ``Relationship.derived_from`` ids -- exactly
as stored, never followed through a ``NormalizedEvent`` into its own
``derived_from`` -- and classifies chains by pairwise overlap of those
raw id sets.

Deliberately does NOT call ``analyze_paths_evidence_overlap`` and does
NOT resolve any ``NormalizedEvent`` (no recursion past one, direct,
un-followed hop). This is the realistic "an analyst reads each
relationship's own derived_from field and compares ids directly, without
chasing multi-level lineage" baseline -- WG-Bench V2's central comparison
is this baseline versus Witnessgraph's actual recursive resolution (see
docs/research/wg-bench.md's V2 section, "the key result").
"""

from __future__ import annotations

from witnessgraph.correlate.graph import TraversalStep

DIRECTLY_DISJOINT = "directly_disjoint"
DIRECTLY_OVERLAPPING = "directly_overlapping"
NOT_APPLICABLE = "not_applicable"


def chain_direct_reference_ids(chain: tuple[TraversalStep, ...]) -> frozenset[str]:
    """Every raw, unresolved id every relationship on this chain cites via
    ``derived_from`` -- may be an ``EvidenceItem`` id or a
    ``NormalizedEvent`` id, indistinguishable from each other at this
    level (that indistinguishability, and its consequences, is exactly
    what this baseline is designed to expose)."""
    ids: set[str] = set()
    for step in chain:
        ids.update(step.relationship.derived_from)
    return frozenset(ids)


def classify_by_direct_references(chains: tuple[tuple[TraversalStep, ...], ...]) -> str:
    """Bucket a set of returned chains by pairwise direct-reference-set
    overlap. Mirrors ``analyze_paths_evidence_overlap``'s three-valued
    shape so it is directly comparable to Witnessgraph's own verdict."""
    if len(chains) < 2:
        return NOT_APPLICABLE
    sets = [chain_direct_reference_ids(chain) for chain in chains]
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            if sets[i] & sets[j]:
                return DIRECTLY_OVERLAPPING
    return DIRECTLY_DISJOINT


def implies_independent_corroboration(classification: str) -> bool:
    """The reading a consumer of direct-evidence-reference comparison
    would draw: every chain pairwise-direct-disjoint implies independent,
    corroborating support."""
    return classification == DIRECTLY_DISJOINT
