"""Aggregate WG-Bench V2 metrics -- four methods (baseline0, baseline1,
baseline2, witnessgraph) each scored identically over four
never-pooled evaluation groups (binary / single_path / partial_overlap /
adversarial), exactly mirroring V1's evaluation-groups discipline (see
``research.wg_bench.metrics``) but extended from two methods to four.

Every metric here is an exact ratio of integer counts over a fixed,
known-composition fixture set -- never an approximation.
"""

from __future__ import annotations

from dataclasses import dataclass

from research.wg_bench.metrics import ConfusionMatrix
from research.wg_bench.v2.evaluation import FixtureEvaluationV2

METHODS = ("baseline0", "baseline1", "baseline2", "witnessgraph")

#: Fixture classes excluded from the binary-classification group and
#: reported in their own, separate group instead. "PARTIAL_OVERLAP_COMPLEX"
#: is a V3-only class (research.wg_bench.v3); listed here, not duplicated
#: in a V3-local copy, so V2 and V3 share one grouping rule and V2's own
#: results (which never contain this class) are completely unaffected.
BINARY_EXCLUDED_CLASSES = frozenset(
    {"PARTIAL_OVERLAP", "PARTIAL_MULTI_ROOT", "PARTIAL_OVERLAP_COMPLEX"}
)


def _confusion_matrix(evaluations: list[FixtureEvaluationV2], *, method: str) -> ConfusionMatrix:
    tp = fp = fn = tn = 0
    for e in evaluations:
        truth = e.ground_truth_root_sets_disjoint
        if truth is None:
            continue
        pred = bool(e.predicted_independent[method])
        if pred and truth:
            tp += 1
        elif pred and not truth:
            fp += 1
        elif not pred and truth:
            fn += 1
        else:
            tn += 1
    return ConfusionMatrix(true_positive=tp, false_positive=fp, false_negative=fn, true_negative=tn)


@dataclass(frozen=True)
class GroupMetricsV2:
    group: str
    fixture_ids: tuple[str, ...]
    #: {"baseline0": ConfusionMatrix, "baseline1": ..., "baseline2": ..., "witnessgraph": ...}
    confusion: dict[str, ConfusionMatrix]
    false_corroboration_count: dict[str, int]
    deterministic_replay_success_count: int
    deterministic_replay_total: int

    @property
    def deterministic_replay_success_rate(self) -> float | None:
        return (
            self.deterministic_replay_success_count / self.deterministic_replay_total
            if self.deterministic_replay_total
            else None
        )


def _group_metrics(group: str, evaluations: list[FixtureEvaluationV2]) -> GroupMetricsV2:
    return GroupMetricsV2(
        group=group,
        fixture_ids=tuple(e.fixture_id for e in evaluations),
        confusion={m: _confusion_matrix(evaluations, method=m) for m in METHODS},
        false_corroboration_count={
            m: sum(1 for e in evaluations if e.false_corroboration[m]) for m in METHODS
        },
        deterministic_replay_success_count=sum(1 for e in evaluations if e.deterministic_replay_ok),
        deterministic_replay_total=len(evaluations),
    )


@dataclass(frozen=True)
class PartialOverlapFindingV2:
    """Per-fixture pairwise-information accounting for a partial-overlap
    fixture, for BOTH root evidence (Witnessgraph's own representation)
    and direct references (Baseline 2's) -- lets a reader see whether
    Baseline 2's boolean loses the same pairwise information Witnessgraph's
    boolean does (it does, structurally, by the same "any pair overlaps ->
    False" rule), independent of whether the two methods' *root* verdicts
    themselves agree."""

    fixture_id: str
    total_chain_pairs: int
    root_disjoint_pairs: int
    root_boolean_verdict: bool | None
    direct_disjoint_pairs: int
    direct_boolean_verdict: bool | None

    @property
    def root_pairs_masked_by_boolean(self) -> int:
        return self.root_disjoint_pairs if self.root_boolean_verdict is False else 0

    @property
    def direct_pairs_masked_by_boolean(self) -> int:
        return self.direct_disjoint_pairs if self.direct_boolean_verdict is False else 0

    @property
    def information_loss_rate(self) -> float | None:
        """root_pairs_masked_by_boolean / total_chain_pairs -- the exact
        fraction of this fixture's pairwise relational structure the
        single top-level Witnessgraph boolean does not surface."""
        return (
            self.root_pairs_masked_by_boolean / self.total_chain_pairs
            if self.total_chain_pairs
            else None
        )


def _partial_overlap_findings(
    evaluations: list[FixtureEvaluationV2],
) -> tuple[PartialOverlapFindingV2, ...]:
    findings: list[PartialOverlapFindingV2] = []
    for e in evaluations:
        root_sets = [set(s) for s in e.actual_root_sets]
        direct_sets = [set(s) for s in e.actual_direct_sets]
        n = len(root_sets)
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        root_disjoint = sum(1 for i, j in pairs if not (root_sets[i] & root_sets[j]))
        direct_disjoint = sum(1 for i, j in pairs if not (direct_sets[i] & direct_sets[j]))
        findings.append(
            PartialOverlapFindingV2(
                fixture_id=e.fixture_id,
                total_chain_pairs=len(pairs),
                root_disjoint_pairs=root_disjoint,
                root_boolean_verdict=e.predicted_independent["witnessgraph"],
                direct_disjoint_pairs=direct_disjoint,
                direct_boolean_verdict=e.predicted_independent["baseline2"],
            )
        )
    return tuple(findings)


@dataclass(frozen=True)
class BenchmarkMetricsV2:
    binary: GroupMetricsV2
    single_path: GroupMetricsV2
    partial_overlap: GroupMetricsV2
    adversarial: GroupMetricsV2
    partial_overlap_findings: tuple[PartialOverlapFindingV2, ...]
    total_fixtures: int
    all_ground_truth_matches: bool
    all_deterministic_replay_ok: bool


def compute_metrics(evaluations: list[FixtureEvaluationV2]) -> BenchmarkMetricsV2:
    binary_group = [
        e
        for e in evaluations
        if e.ground_truth_binary_applicable
        and not e.is_adversarial
        and e.fixture_class not in BINARY_EXCLUDED_CLASSES
    ]
    single_path_group = [
        e for e in evaluations if not e.ground_truth_binary_applicable and not e.is_adversarial
    ]
    partial_overlap_group = [e for e in evaluations if e.fixture_class in BINARY_EXCLUDED_CLASSES]
    adversarial_group = [e for e in evaluations if e.is_adversarial]

    return BenchmarkMetricsV2(
        binary=_group_metrics("binary", binary_group),
        single_path=_group_metrics("single_path", single_path_group),
        partial_overlap=_group_metrics("partial_overlap", partial_overlap_group),
        adversarial=_group_metrics("adversarial", adversarial_group),
        partial_overlap_findings=_partial_overlap_findings(partial_overlap_group),
        total_fixtures=len(evaluations),
        all_ground_truth_matches=all(
            e.path_count_matches_expected
            and e.root_sets_match_expected
            and e.direct_sets_match_expected
            for e in evaluations
        ),
        all_deterministic_replay_ok=all(e.deterministic_replay_ok for e in evaluations),
    )
