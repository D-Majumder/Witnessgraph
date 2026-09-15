"""BASELINE 1: path-structure reasoning.

Answers WG-Bench V2's methodological question: "can ordinary inspection
of the graph paths -- entity ids, relationship ids, the structural shape
of each chain -- already reveal the relevant root-evidence-independence
distinction, with no evidence-reference reasoning at all?"

Deliberately does NOT inspect ``Relationship.derived_from`` (that is
exactly what distinguishes it from Baseline 2, see ``baseline2.py``) and
does NOT call ``analyze_paths_evidence_overlap`` or resolve any
``NormalizedEvent``. It only ever looks at what
``find_all_shortest_paths`` itself already returns: each chain's ordered
``TraversalStep``s, each step's ``relationship.id``,
``relationship.source_entity_id``/``target_entity_id``.

This baseline exists to isolate one specific question from Baseline 2's:
is *structural* path information (which the analyst already sees just by
counting/skimming distinct chains, with no provenance lookup at all)
already sufficient, or does an analyst need to additionally consult
evidence-reference fields (Baseline 2) to do any better than path-count
alone? See docs/research/wg-bench.md's V2 section for the answer.
"""

from __future__ import annotations

from witnessgraph.correlate.graph import TraversalStep

STRUCTURALLY_DISJOINT = "structurally_disjoint"
STRUCTURALLY_OVERLAPPING = "structurally_overlapping"
NOT_APPLICABLE = "not_applicable"


def chain_entity_ids(chain: tuple[TraversalStep, ...]) -> frozenset[str]:
    """Every entity id (source and target of every hop) a chain touches."""
    ids: set[str] = set()
    for step in chain:
        ids.add(step.relationship.source_entity_id)
        ids.add(step.relationship.target_entity_id)
    return frozenset(ids)


def chain_relationship_ids(chain: tuple[TraversalStep, ...]) -> frozenset[str]:
    return frozenset(step.relationship.id for step in chain)


def _endpoints(chains: tuple[tuple[TraversalStep, ...], ...]) -> frozenset[str]:
    """Source/target entity ids common to every chain by construction (all
    chains connect the same source->target pair) -- excluded from the
    structural-overlap comparison, since sharing them is definitionally
    universal and carries no discriminating signal."""
    endpoints: set[str] = set()
    for chain in chains:
        if chain:
            endpoints.add(chain[0].from_entity_id)
            endpoints.add(chain[-1].to_entity_id)
    return frozenset(endpoints)


def pairwise_structural_overlap(
    chain_a: tuple[TraversalStep, ...],
    chain_b: tuple[TraversalStep, ...],
    endpoints: frozenset[str],
) -> bool:
    """True if two chains share any non-endpoint entity id or any
    relationship id -- the only signal Baseline 1 is permitted to use."""
    entities_a = chain_entity_ids(chain_a) - endpoints
    entities_b = chain_entity_ids(chain_b) - endpoints
    if entities_a & entities_b:
        return True
    return bool(chain_relationship_ids(chain_a) & chain_relationship_ids(chain_b))


def classify_by_structure(chains: tuple[tuple[TraversalStep, ...], ...]) -> str:
    """Bucket a set of returned chains by pairwise structural overlap.

    Mirrors ``analyze_paths_evidence_overlap``'s three-valued shape
    (independent/not_independent/not_applicable) so it is directly
    comparable, but the underlying signal is purely structural (entity
    and relationship ids), never evidence.
    """
    if len(chains) < 2:
        return NOT_APPLICABLE
    endpoints = _endpoints(chains)
    for i in range(len(chains)):
        for j in range(i + 1, len(chains)):
            if pairwise_structural_overlap(chains[i], chains[j], endpoints):
                return STRUCTURALLY_OVERLAPPING
    return STRUCTURALLY_DISJOINT


def implies_independent_corroboration(classification: str) -> bool:
    """The reading a consumer of structural-only path inspection would
    draw: every chain pairwise-structurally-distinct implies independent,
    corroborating support. Mirrors ``baseline.implies_independent_corroboration``'s
    naming discipline exactly, applied to this baseline's own classification."""
    return classification == STRUCTURALLY_DISJOINT
