# WG-Study: Draft Preregistration Package

**Status: DRAFT — NOT YET PREREGISTERED.** No submission has been made
to any registry (e.g. OSF, AsPredicted), and no real participant data
exists anywhere in this repository or its history as of this document's
writing. This document exists to fix, in writing and before any real
data collection, the exact analysis this study will run — so that a
future analysis cannot be silently adjusted after seeing results. See
`docs/research/wg-study.md` §10 for why this repository implements no
inferential statistics yet, §16/§20 for this document's place in the
sequence of prerequisites before real recruitment, and
`docs/research/wg-study-reporting.md` §19 for the explicit distinction
this protocol draws between a usability/variance-estimation **pilot**
and a hypothesis-testing **confirmatory study** — this document's §5/§6
must be completed, and an actual registry submission made, before any
confirmatory (not pilot) data collection begins.

## 1. Research questions and hypotheses

Verbatim from `docs/research/wg-study.md` §1–§2:

- **Research question:** Does explicit root-evidence provenance
  reasoning help an analyst avoid false-corroboration interpretations
  compared with graph/path information without recursive root-evidence
  explanation?
- **H1-Study:** Condition C (WITNESSGRAPH) participants will have a
  lower provenance-level false-corroboration rate than Condition A
  (PATH_ONLY) participants.
- **H2-Study:** Condition B (DIRECT_EVIDENCE) participants will perform
  better than Condition A but worse than Condition C, specifically on
  cases requiring provenance indirection (case types C/D/E — see
  `docs/research/wg-study.md` §5).

## 2. Design

Between-subject, three-arm (A/B/C), deterministic condition assignment
and case-order randomization from a fixed seed
(`research.wg_study.runner`, `STUDY_SEED = "wg-study-v1-seed"`). Every
participant sees all 9 cases, in a per-participant deterministic order,
under exactly one condition. See `docs/research/wg-study.md` §7 for the
randomization mechanism and its documented within-subject-design
trade-off.

## 3. Primary outcome measure

**False-corroboration rate**: the proportion of ground-truth-SHARED
answers that a participant answered DISJOINT (`analysis.py`'s
`false_corroboration_rate` per `ConditionMetrics`). Computed separately
per condition (A, B, C).

## 4. Secondary outcome measures

Exactly the set already implemented in
`research.wg_study.analysis.ConditionMetrics` (see
`docs/research/wg-study.md` §9): `response_count`, `accuracy`,
`shared_root_accuracy`, `disjoint_root_accuracy`,
`partial_overlap_pair_accuracy`, `mean_response_time_ms`,
`median_response_time_ms`, `indeterminate_rate`,
`missing_response_rate`.

## 5. Sample size

**Not yet determined.** No power analysis has been run because no
minimum detectable effect size has been chosen. This is listed
explicitly, rather than filled with a placeholder number, so that a
future revision of this document cannot be mistaken for having done
this work. Before recruitment begins, this section must be replaced
with: the minimum effect size considered practically meaningful for the
false-corroboration-rate difference in H1-Study, the significance level
and power target used, the resulting per-condition sample size, and the
test family assumed (§6) when computing it.

## 6. Planned statistical analysis

**Not yet implemented in code anywhere in this repository** —
`research.wg_study.analysis.py` deliberately implements no inferential
statistics (§10 of the main design document explains why). This section
records, in advance, the minimum commitments any future implementation
must satisfy before it is used to interpret real data:

- Three planned pairwise condition comparisons on the primary outcome:
  A-vs-B, B-vs-C, A-vs-C.
- A multiple-comparison correction applied across those three
  comparisons (e.g. Bonferroni or Holm — the specific choice is an open
  item, not yet made) before any comparison is reported as
  "significant."
- The specific test family (e.g. a proportions test suited to a binary
  per-question SHARED/not-SHARED outcome, or a mixed-effects logistic
  model accounting for repeated measurements within participant across
  cases) is an open item — not yet chosen. Choosing it requires first
  deciding whether the unit of analysis is per-question or
  per-participant, which in turn interacts with the sample-size
  calculation in §5. Both must be settled together, in writing, before
  data collection, not derived post hoc from whatever data collection
  produces. **Whichever test is ultimately chosen must account for
  within-participant clustering** (each participant answers many
  questions across many cases, so individual questions are not
  independent observations) — see
  `docs/research/wg-study-reporting.md` §12 for the fuller statement of
  this principle and the candidate analysis families it identifies
  without locking one in.
- Effect size and its confidence interval must be reported alongside
  any p-value for every comparison — a p-value alone will not be
  reported as the whole result.
- H2-Study's "falls strictly between" comparison additionally requires
  restricting the sample to case types C/D/E before testing (see
  `docs/research/wg-study.md` §18), which must be a pre-specified subset
  test, not a post hoc one chosen after seeing which case types show a
  pattern.

## 7. Stopping rule

Data collection stops at the pre-registered sample size from §5, once
that section is completed — not upon observing significance, and not
upon informal inspection of interim results. No interim analysis for
early stopping is planned; if one is later desired, it must be
pre-specified with its own alpha-spending correction before
implementation, not added ad hoc.

## 8. Exclusion criteria

- Any record with `is_developer_validation=True` is excluded
  unconditionally (already implemented — `analysis.analyze`).
- Any record rejected by `dataset_validation.validate_dataset` (missing
  field, mixed study version, unknown condition/case/question,
  malformed answer, negative response time, or duplicate
  participant/case/question key — see that module's docstring) is
  excluded from analysis, with the rejection reason logged via
  `python -m research.wg_study validate-dataset`, never silently
  dropped without a record of why.
- No other exclusion criterion (e.g. removing "too fast" or "too slow"
  responses as suspected inattentive answering) is currently defined.
  If one is added later, it must be specified here, in writing, before
  it is applied to real data — not decided by inspecting the collected
  response-time distribution first.

## 9. What would confirm, and what would falsify, each hypothesis

Verbatim from `docs/research/wg-study.md` §18–§19 (repeated here so this
preregistration is self-contained):

**Would support the hypotheses:**
- H1-Study: Condition C's false-corroboration rate is measurably and
  (per §6's pre-registered test) significantly lower than Condition A's,
  at the pre-registered sample size, replicated at least once.
- H2-Study: Condition B's false-corroboration rate falls strictly
  between A's and C's specifically on case types C/D/E.

**Would falsify the hypotheses:**
- Condition C does not reduce false-corroboration relative to Condition
  B.
- Any apparent difference disappears under a reasonable replication.
- Near-chance accuracy across all case types under Condition C
  specifically (evidence of a presentation failure, not a reasoning
  failure — this would not be reported as support for or against the
  hypotheses, but as a confound requiring a presentation-design fix
  before re-testing).
- Condition B performs equivalently to Condition C specifically on
  case types C/D/E.

A null or negative result on either hypothesis will be reported as such
— this document commits to that in advance, per
`docs/research/wg-study.md` §19's own statement that a null result is a
scientifically useful, reportable outcome under this protocol.

## 10. Commitment against post hoc reporting changes

This document, once real data collection begins, may only be amended by
a dated addendum stating exactly what changed and why (e.g. "sample size
recalculated before collection began because X") — never edited in
place to make it read as though the final analysis plan was always the
one that happened to match the collected data.
