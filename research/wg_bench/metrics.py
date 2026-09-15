"""Aggregate WG-Bench metrics.

Computed separately over four groups of `FixtureEvaluation` records that
must never be pooled into one blended score (see
``docs/research/wg-bench.md``'s evaluation-groups discussion): the
binary-classification group (>=2 expected chains, non-adversarial,
not the PARTIAL_OVERLAP class), the single-path sanity group, the
partial-overlap group, and the adversarial group.

Every metric here is an exact ratio of integer counts over a fixed,
known-composition fixture set -- never an approximation or a value that
requires interpreting how "good" a given decimal is; ``float`` values
returned by ``ConfusionMatrix``'s properties are always an exact
division of two recorded integers, reproducible bit-for-bit given the
same fixture set.
"""

from __future__ import annotations

from dataclasses import dataclass

from research.wg_bench.evaluation import FixtureEvaluation

#: Fixture classes excluded from the binary-classification group and
#: reported in their own, separate group instead -- see module docstring.
BINARY_EXCLUDED_CLASSES = frozenset({"PARTIAL_OVERLAP"})


@dataclass(frozen=True)
class ConfusionMatrix:
    """Positive class = ground truth ``root_sets_disjoint is True``
    ("root-evidence independent at the provenance level"). Only ever
    computed over fixtures where that ground truth is not None (see
    :func:`_confusion_matrix`)."""

    true_positive: int
    false_positive: int
    false_negative: int
    true_negative: int

    @property
    def total(self) -> int:
        return self.true_positive + self.false_positive + self.false_negative + self.true_negative

    @property
    def accuracy(self) -> float | None:
        """(TP + TN) / total. None when total is 0 (no applicable fixtures)."""
        return (self.true_positive + self.true_negative) / self.total if self.total else None

    @property
    def precision(self) -> float | None:
        """TP / (TP + FP): of everything predicted independent, the
        fraction that truly is. None when nothing was predicted independent."""
        denom = self.true_positive + self.false_positive
        return self.true_positive / denom if denom else None

    @property
    def recall(self) -> float | None:
        """TP / (TP + FN): of everything truly independent, the fraction
        correctly predicted so. None when nothing truly is."""
        denom = self.true_positive + self.false_negative
        return self.true_positive / denom if denom else None

    @property
    def false_positive_rate(self) -> float | None:
        """FP / (FP + TN): of everything truly NOT independent, the
        fraction wrongly predicted independent -- the precise
        "false-corroboration rate" this benchmark's headline metric
        uses. None when nothing truly is non-independent."""
        denom = self.false_positive + self.true_negative
        return self.false_positive / denom if denom else None


def _confusion_matrix(evaluations: list[FixtureEvaluation], *, predicted: str) -> ConfusionMatrix:
    """``predicted`` is ``"baseline"`` or ``"witnessgraph"``: which
    method's binary "root-evidence independent" prediction to score
    against ``ground_truth_root_sets_disjoint``. Fixtures where that
    ground truth is None (not a binary-applicable question) contribute
    nothing to any cell."""
    tp = fp = fn = tn = 0
    for e in evaluations:
        truth = e.ground_truth_root_sets_disjoint
        if truth is None:
            continue
        pred = (
            e.baseline_implies_independent_corroboration
            if predicted == "baseline"
            else bool(e.witnessgraph_fully_evidence_independent)
        )
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
class GroupMetrics:
    group: str
    fixture_ids: tuple[str, ...]
    baseline_confusion: ConfusionMatrix
    witnessgraph_confusion: ConfusionMatrix
    baseline_false_corroboration_count: int
    witnessgraph_false_corroboration_count: int
    deterministic_replay_success_count: int
    deterministic_replay_total: int

    @property
    def deterministic_replay_success_rate(self) -> float | None:
        return (
            self.deterministic_replay_success_count / self.deterministic_replay_total
            if self.deterministic_replay_total
            else None
        )


def _group_metrics(group: str, evaluations: list[FixtureEvaluation]) -> GroupMetrics:
    return GroupMetrics(
        group=group,
        fixture_ids=tuple(e.fixture_id for e in evaluations),
        baseline_confusion=_confusion_matrix(evaluations, predicted="baseline"),
        witnessgraph_confusion=_confusion_matrix(evaluations, predicted="witnessgraph"),
        baseline_false_corroboration_count=sum(
            1 for e in evaluations if e.baseline_false_corroboration
        ),
        witnessgraph_false_corroboration_count=sum(
            1 for e in evaluations if e.witnessgraph_false_corroboration
        ),
        deterministic_replay_success_count=sum(
            1 for e in evaluations if e.deterministic_replay_ok
        ),
        deterministic_replay_total=len(evaluations),
    )


@dataclass(frozen=True)
class PartialOverlapFinding:
    """Per-fixture information-loss accounting for a PARTIAL_OVERLAP
    fixture: how many of its chain *pairs* are actually root-evidence-
    disjoint, versus what the single top-level boolean verdict alone
    would tell a reader."""

    fixture_id: str
    total_chain_pairs: int
    disjoint_pairs: int
    non_disjoint_pairs: int
    boolean_verdict: bool | None
    shared_evidence_ids: tuple[str, ...]

    @property
    def pairs_masked_by_boolean(self) -> int:
        """Genuinely root-evidence-disjoint pairs the single top-level
        boolean does not surface, because that verdict is False as soon
        as *any* pair overlaps -- 0 whenever the boolean is not False
        (nothing is being masked)."""
        return self.disjoint_pairs if self.boolean_verdict is False else 0


def _partial_overlap_findings(
    evaluations: list[FixtureEvaluation],
) -> tuple[PartialOverlapFinding, ...]:
    findings: list[PartialOverlapFinding] = []
    for e in evaluations:
        sets = [set(root_set) for root_set in e.actual_root_sets]
        n = len(sets)
        pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
        disjoint = sum(1 for i, j in pairs if not (sets[i] & sets[j]))
        findings.append(
            PartialOverlapFinding(
                fixture_id=e.fixture_id,
                total_chain_pairs=len(pairs),
                disjoint_pairs=disjoint,
                non_disjoint_pairs=len(pairs) - disjoint,
                boolean_verdict=e.witnessgraph_fully_evidence_independent,
                shared_evidence_ids=e.witnessgraph_shared_evidence_ids,
            )
        )
    return tuple(findings)


@dataclass(frozen=True)
class BenchmarkMetrics:
    binary: GroupMetrics
    single_path: GroupMetrics
    partial_overlap: GroupMetrics
    adversarial: GroupMetrics
    partial_overlap_findings: tuple[PartialOverlapFinding, ...]
    total_fixtures: int
    #: True iff every fixture's own hand-authored ground truth (path
    #: count, root evidence sets, and expected provenance
    #: classification) matched what its build/analysis actually
    #: produced -- a correctness/regression signal, never a measure of
    #: whether the baseline "did well."
    all_ground_truth_matches: bool
    all_deterministic_replay_ok: bool


def compute_metrics(evaluations: list[FixtureEvaluation]) -> BenchmarkMetrics:
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

    return BenchmarkMetrics(
        binary=_group_metrics("binary", binary_group),
        single_path=_group_metrics("single_path", single_path_group),
        partial_overlap=_group_metrics("partial_overlap", partial_overlap_group),
        adversarial=_group_metrics("adversarial", adversarial_group),
        partial_overlap_findings=_partial_overlap_findings(partial_overlap_group),
        total_fixtures=len(evaluations),
        all_ground_truth_matches=all(
            e.path_count_matches_expected
            and e.root_sets_match_expected
            and e.provenance_matches_expected
            for e in evaluations
        ),
        all_deterministic_replay_ok=all(e.deterministic_replay_ok for e in evaluations),
    )
