"""Per-condition rendering of a ``StudyCase``.

This module MUST NEVER import ``research.wg_study.answer_key`` --
enforced by
``tests/unit/test_wg_study.py::test_presentation_module_never_imports_answer_key``.
The function below is the ONLY place that decides what a participant in
a given condition actually sees; it receives full-fidelity case data and
selectively hides fields, never receiving or needing to know a correct
answer to do so.

Condition definitions (``docs/research/wg-study.md`` section 3):

- PATH_ONLY: entities, relationships, path count. No evidence-reference
  information at all.
- DIRECT_EVIDENCE: PATH_ONLY plus each chain's direct (unresolved)
  reference labels.
- WITNESSGRAPH: DIRECT_EVIDENCE plus each chain's recursively-resolved
  root-evidence labels.

No condition's rendering uses color, ordering, or any other visual/
positional cue that itself encodes ground truth -- ``ChainPresentation``
fields are emitted in a fixed, case-structural order (``chain_index``)
regardless of any answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from research.wg_study.model import Condition, StudyCase


@dataclass(frozen=True)
class ChainPresentation:
    chain_index: int
    entity_labels: tuple[str, ...]
    relationship_labels: tuple[str, ...]
    #: None when this condition does not reveal evidence-reference
    #: information at all (PATH_ONLY).
    direct_reference_labels: tuple[str, ...] | None
    #: None unless WITNESSGRAPH.
    root_evidence_labels: tuple[str, ...] | None


@dataclass(frozen=True)
class CaseView:
    case_id: str
    condition: Condition
    source_entity_label: str
    target_entity_label: str
    path_count: int
    chains: tuple[ChainPresentation, ...]


def present_case(case: StudyCase, condition: Condition) -> CaseView:
    show_direct = condition in (Condition.DIRECT_EVIDENCE, Condition.WITNESSGRAPH)
    show_root = condition is Condition.WITNESSGRAPH
    chains = tuple(
        ChainPresentation(
            chain_index=chain.chain_index,
            entity_labels=chain.entity_labels,
            relationship_labels=chain.relationship_labels,
            direct_reference_labels=(chain.direct_reference_labels if show_direct else None),
            root_evidence_labels=(chain.root_evidence_labels if show_root else None),
        )
        for chain in case.chains
    )
    return CaseView(
        case_id=case.case_id,
        condition=condition,
        source_entity_label=case.source_entity_label,
        target_entity_label=case.target_entity_label,
        path_count=case.path_count,
        chains=chains,
    )
