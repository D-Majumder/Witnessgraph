"""Builds WG-Study's fixed case manifest from existing, already-validated
WG-Bench V1/V2/V3 fixtures.

For each selected fixture this module:

1. builds the fixture's graph against a real, fresh ``Case``/``SqliteStore``
   (the same store production code uses);
2. calls Witnessgraph's actual, unmodified ``find_all_shortest_paths`` and
   ``analyze_paths_evidence_overlap`` through their ordinary Python API --
   this is used ONLY to discover case *structure* (how many chains exist,
   which entities/relationships/direct-references/root-evidence-ids each
   one touches), never to determine a correct answer;
3. relabels every id that appears with a neutral, deterministic,
   per-case sequential label (``N-01`` entities, ``R-01`` relationships,
   ``D-01`` direct/unresolved references, ``E-01`` root evidence) --
   never a label that encodes the fixture's classification;
4. derives each pairwise question's correct answer from the fixture's
   own independently-authored ``GroundTruthV2.expected_chains`` root
   evidence *labels* (as the fixture author wrote them), matched to the
   actual chain via root-evidence-id-set equality -- NEVER from
   ``analyze_paths_evidence_overlap()``'s own boolean verdict. See
   ``answer_key.py``'s docstring.

The case selection below covers WG-Study's 9 case types (A-I in
``docs/research/wg-study.md`` section 5), one fixture per type, chosen
from WG-Bench's existing, already-tested fixture pool -- this
deliberately reuses fixtures whose own ``build()`` output has already
been independently verified against their ground truth by WG-Bench's own
test suite, rather than re-authoring new graphs from scratch.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from research.wg_bench.v2 import baseline1, baseline2
from research.wg_bench.v2 import fixtures as v2_fixtures
from research.wg_bench.v2.model import FixtureV2, GroundTruthV2
from research.wg_bench.v3 import fixtures as v3_fixtures
from research.wg_study.answer_key import CaseAnswerKey, PairwiseAnswer
from research.wg_study.model import Answer, ChainView, StudyCase
from witnessgraph.correlate.graph import (
    DEFAULT_PATH_MAX_DEPTH,
    DEFAULT_PATHS_LIMIT,
    analyze_paths_evidence_overlap,
    find_all_shortest_paths,
)
from witnessgraph.store.case import Case

ANSWER_KEY_VERSION = "wg-study-v1"

#: (case_type, underlying WG-Bench fixture_id) -- WG-Study's fixed,
#: deterministic case manifest. One fixture per case type from
#: ``docs/research/wg-study.md`` section 5 (A-I), each drawn from an
#: already-existing, already-tested WG-Bench V1/V2/V3 fixture.
CASE_SELECTION: tuple[tuple[str, str], ...] = (
    ("SHARED_ROOT", "shared-root-01"),
    ("DISJOINT_ROOT", "disjoint-roots-01"),
    ("DIRECT_REFERENCE_DECOY", "v3-direct-reference-decoy-01"),
    ("MULTI_LEVEL_INDIRECTION", "v3-multi-level-lineage-01"),
    ("MIXED_DEPTH", "v3-mixed-root-depth-01"),
    ("PARTIAL_OVERLAP", "partial-overlap-01"),
    ("HIGH_PATH_MULTIPLICITY_SHARED", "high-path-shared-root-01"),
    ("HIGH_PATH_MULTIPLICITY_DISJOINT", "high-path-disjoint-root-01"),
    ("NEGATIVE_CONTROL", "single-path-01"),
)


def _all_fixtures_by_id() -> dict[str, FixtureV2]:
    all_f = v2_fixtures.all_fixtures() + v3_fixtures.all_fixtures()
    by_id = {f.ground_truth.fixture_id: f for f in all_f}
    return by_id


def _neutral_labels(prefix: str, ids: set[str]) -> dict[str, str]:
    """Deterministic: sorted by the original (content-hash) id string, so
    label assignment never depends on insertion/build order -- only on
    the id values themselves, which are already assigned before this
    function runs and carry no information about the answer."""
    return {orig: f"{prefix}-{i + 1:02d}" for i, orig in enumerate(sorted(ids))}


def _build_answer_key(
    case_id: str,
    gt: GroundTruthV2,
    resolve_label_to_id: dict[str, str],
    actual_root_id_sets: list[frozenset[str]],
) -> CaseAnswerKey:
    expected_root_id_sets = [
        frozenset(resolve_label_to_id[label] for label in c.root_evidence_labels)
        for c in gt.expected_chains
    ]

    # Greedy matching: for a fixture with two chains sharing an identical
    # root-evidence-label set (e.g. DIRECT_REFERENCE_DECOY, where both
    # chains resolve to {"E1"}), which specific candidate a given actual
    # chain is paired with is immaterial to the pairwise answer -- every
    # tied candidate yields the same root label set, and therefore the
    # same SHARED/DISJOINT verdict for any pairing. Consuming each
    # expected-chain index at most once still catches a genuine
    # correspondence failure (zero candidates).
    used: set[int] = set()
    index_to_expected: dict[int, int] = {}
    for actual_idx, actual_ids in enumerate(actual_root_id_sets):
        matches = [
            k for k, exp in enumerate(expected_root_id_sets) if exp == actual_ids and k not in used
        ]
        if not matches:
            raise ValueError(
                f"cannot map chain {actual_idx} of fixture {gt.fixture_id} to its "
                f"independently-authored ground truth (root ids {sorted(actual_ids)} match no "
                f"unused expected chain); WG-Study requires this correspondence to hold for its "
                f"selected fixtures."
            )
        chosen = matches[0]
        used.add(chosen)
        index_to_expected[actual_idx] = chosen

    n = len(actual_root_id_sets)
    pairwise: list[PairwiseAnswer] = []
    for i in range(n):
        for j in range(i + 1, n):
            labels_i = gt.expected_chains[index_to_expected[i]].root_evidence_labels
            labels_j = gt.expected_chains[index_to_expected[j]].root_evidence_labels
            shared = bool(labels_i & labels_j)
            pairwise.append(
                PairwiseAnswer(
                    chain_pair=(i, j),
                    correct_answer=(Answer.SHARED_ROOT if shared else Answer.DISJOINT_ROOT),
                )
            )

    whole_case_answer = Answer.INDETERMINATE if n < 2 else None

    return CaseAnswerKey(
        case_id=case_id,
        fixture_id=gt.fixture_id,
        answer_key_version=ANSWER_KEY_VERSION,
        whole_case_answer=whole_case_answer,
        pairwise_answers=tuple(pairwise),
        ground_truth_root_sets_disjoint=gt.root_sets_disjoint,
        ground_truth_root_sets_partial_overlap=gt.root_sets_partial_overlap,
        notes=gt.notes,
    )


def _build_one(
    case_type: str, fixture: FixtureV2, case_index: int
) -> tuple[StudyCase, CaseAnswerKey]:
    gt = fixture.ground_truth
    with tempfile.TemporaryDirectory(prefix=f"wgstudy-{gt.fixture_id}-") as d:
        case = Case.create(Path(d) / "case")
        try:
            built = fixture.build(case)
            result = find_all_shortest_paths(
                case.store,
                built.source_entity_id,
                built.target_entity_id,
                max_depth=DEFAULT_PATH_MAX_DEPTH,
                limit=DEFAULT_PATHS_LIMIT,
            )
            overlap = analyze_paths_evidence_overlap(case.store, result)

            entity_ids: set[str] = {built.source_entity_id, built.target_entity_id}
            relationship_ids: set[str] = set()
            direct_ids: set[str] = set()
            for chain in result.paths:
                entity_ids |= baseline1.chain_entity_ids(chain)
                relationship_ids |= baseline1.chain_relationship_ids(chain)
                direct_ids |= baseline2.chain_direct_reference_ids(chain)
            root_ids: set[str] = set()
            for chain_evidence in overlap.chains:
                root_ids |= set(chain_evidence.root_evidence_ids)

            entity_labels = _neutral_labels("N", entity_ids)
            rel_labels = _neutral_labels("R", relationship_ids)
            direct_labels = _neutral_labels("D", direct_ids)
            root_labels = _neutral_labels("E", root_ids)

            chains: list[ChainView] = []
            actual_root_id_sets: list[frozenset[str]] = []
            for idx, chain in enumerate(result.paths):
                chain_root_ids = frozenset(overlap.chains[idx].root_evidence_ids)
                actual_root_id_sets.append(chain_root_ids)
                chains.append(
                    ChainView(
                        chain_index=idx,
                        entity_labels=tuple(
                            sorted(entity_labels[e] for e in baseline1.chain_entity_ids(chain))
                        ),
                        relationship_labels=tuple(
                            sorted(
                                rel_labels[r] for r in baseline1.chain_relationship_ids(chain)
                            )
                        ),
                        direct_reference_labels=tuple(
                            sorted(
                                direct_labels[d]
                                for d in baseline2.chain_direct_reference_ids(chain)
                            )
                        ),
                        root_evidence_labels=tuple(sorted(root_labels[r] for r in chain_root_ids)),
                    )
                )

            # Deliberately neutral: this id is shown to participants (it
            # appears in prompts/logs), so it must not embed `case_type`
            # (which names the fixture's classification, e.g.
            # "shared_root") the way an earlier draft of this function
            # did -- see tests/unit/test_wg_study.py's
            # test_neutral_labels_never_encode_classification.
            case_id = f"wgstudy-{case_index:02d}"
            study_case = StudyCase(
                case_id=case_id,
                case_type=case_type,
                source_entity_label=entity_labels[built.source_entity_id],
                target_entity_label=entity_labels[built.target_entity_id],
                path_count=len(result.paths),
                chains=tuple(chains),
            )

            resolve_label_to_id = dict(built.evidence_by_label)
            answer_key = _build_answer_key(case_id, gt, resolve_label_to_id, actual_root_id_sets)

            return study_case, answer_key
        finally:
            case.close()


def build_all_cases() -> tuple[tuple[StudyCase, CaseAnswerKey], ...]:
    """Builds WG-Study's full, fixed 9-case manifest, in
    ``CASE_SELECTION``'s declared order."""
    by_id = _all_fixtures_by_id()
    results = []
    for case_index, (case_type, fixture_id) in enumerate(CASE_SELECTION, start=1):
        fixture = by_id[fixture_id]
        results.append(_build_one(case_type, fixture, case_index))
    return tuple(results)
