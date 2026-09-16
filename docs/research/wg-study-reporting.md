# WG-Study: Reporting Plan and Research Governance

**Status: DRAFT — describes how a future real dataset will be reported,
not a report of any existing dataset.** No human participant data exists
anywhere in this repository or its history as of this document's
writing. Nothing in this document is a result. It exists so that the
exact reporting standard a future dataset will be held to is fixed in
writing before that dataset exists, alongside
`docs/research/wg-study-preregistration.md` (the analysis-commitment
document) and `docs/research/wg-study-consent-ethics.md` (the
ethics/consent document). See `docs/research/wg-study.md` for the full
study design this document reports against.

## 1. Study version

Every report must open by stating the exact frozen study package it
covers: the `study_version` string (`model.STUDY_VERSION`), the
`answer_key_version`, and the `case_manifest_hash` — all three obtained
by running `python -m research.wg_study freeze` at data-collection time
and archived alongside the raw dataset (see §18 and
`docs/research/wg-study.md` §12). A report covering data collected under
more than one `study_version` must say so explicitly and report each
version's results separately — `dataset_validation.py` already rejects
mixed-version records at the per-record level, but a report is a second,
human-readable place this must never be silently blurred.

## 2. Participant count

Report, at minimum: total participants who started a session, total who
completed all 9 cases, total whose data passed
`dataset_validation.validate_dataset` with zero rejections, and the
per-condition count among those valid participants. A participant who
started but did not finish is reported, not omitted — see §4 (missing
data) and §5 (exclusions) for how their partial data is handled.

## 3. Condition allocation

Report the realized per-condition participant count (A/B/C) actually
achieved by `runner.assign_condition`'s deterministic
`sha256(seed:participant_id) mod 3` assignment, not merely the count
the study aimed to reach. Because assignment is a hash of each
participant's own id rather than a controlled round-robin, allocation
across the three arms is expected to be *approximately* but not
necessarily *exactly* even; report the actual counts and, if materially
imbalanced, say so rather than implying a balanced design occurred.

## 4. Missing data

Report the count and rate of expected-but-absent responses (a
participant who saw a case but did not answer one of its questions
before stopping) using `analysis.py`'s `missing_response_rate`. State
explicitly whether missingness differed by condition — a missingness
imbalance is itself evidence of a possible condition-driven effect (e.g.
Condition C's presentation being harder to parse and prompting more
early dropout) and must never be reported as if it were random.

## 5. Exclusions

Report, as an explicit list with counts and reasons (never folded
silently into a lower participant count): every record rejected by
`dataset_validation.validate_dataset` (missing field, mixed study
version, unknown condition/case/question, malformed answer, negative
response time, duplicate participant/case/question key — see that
module's docstring), and every `is_developer_validation=True` record
excluded by `analysis.analyze`. No other exclusion criterion exists in
this protocol as of this writing (see
`docs/research/wg-study-preregistration.md` §8); if a future revision
of that document adds one (e.g. removing implausibly fast responses),
this reporting plan requires it be applied identically and reported
with its own count, never applied selectively per condition.

## 6. Primary outcome

**False-corroboration rate**: the proportion of ground-truth-SHARED
answers that a participant answered DISJOINT
(`analysis.ConditionMetrics.false_corroboration_rate`), reported per
condition (A, B, C), with the count of SHARED-ground-truth questions the
rate is computed over stated alongside it (a rate without its
denominator is not an adequate report). This mirrors WG-Bench's own
false-corroboration definition applied to a human response instead of a
computed classifier's output (`docs/research/wg-study.md` §9).

## 7. Secondary outcomes

Report, per condition, exactly the metrics already implemented in
`analysis.ConditionMetrics`: `response_count`, `accuracy`,
`shared_root_accuracy`, `disjoint_root_accuracy`,
`partial_overlap_pair_accuracy`, `mean_response_time_ms`,
`median_response_time_ms`, `indeterminate_rate`,
`missing_response_rate`. No secondary outcome not already implemented
in `analysis.py` may be introduced into a report without first being
added to that module and to
`docs/research/wg-study-preregistration.md` §4 — a report must never be
the first place a new metric is defined.

## 8. Descriptive statistics

Before any inferential comparison, report plain per-condition
descriptives: N, mean/median response time, the primary and secondary
outcome values from §6/§7, and — because responses are clustered within
participant (§12) — the number of participants each condition's
question-level count is drawn from, not only the question-level count
itself. A report showing "312 responses" without also showing how many
participants those 312 responses came from invites a reader to
mistake question-count precision for participant-count precision.

## 9. Planned condition comparisons

Three pairwise comparisons on the primary outcome, exactly as fixed in
`docs/research/wg-study-preregistration.md` §6: A-vs-B, B-vs-C, A-vs-C.
H2-Study's comparison is additionally restricted, per that document, to
case types requiring provenance indirection (C/D/E —
`docs/research/wg-study.md` §5). No comparison outside this
pre-specified set is reported as confirmatory; any additional comparison
that looks interesting after seeing the data is reported under §14
(exploratory analyses) instead, labeled as such.

## 10. Effect-size reporting

Every reported comparison states an effect size (e.g. a risk
difference or odds ratio appropriate to a binary outcome — the specific
choice is fixed alongside the test family in
`docs/research/wg-study-preregistration.md` §6, not invented at report
time) alongside, never instead of, any p-value. A comparison reported
with a p-value and no effect size is treated as incomplete under this
plan.

## 11. Confidence intervals where appropriate

Every effect-size estimate is reported with a confidence interval at a
level fixed in advance (conventionally 95%, but the exact level is set
when the statistical test family is finally chosen — see
`docs/research/wg-study-preregistration.md` §6). A point estimate
reported without an interval is treated as incomplete under this plan,
in the same way a p-value without an effect size is.

## 12. Statistical-test selection principles

The final statistical test cannot be chosen until the sample-size and
design decisions in `docs/research/wg-study-preregistration.md` §5–§6
are resolved, and this document does not resolve them (see
`docs/research/wg-study.md` §10 for why no inferential statistics are
implemented in this repository yet). What this document fixes now,
before that choice is made, is the *principle* the eventual choice must
satisfy:

- **Clustering must be modeled, not ignored.** Every participant
  answers multiple questions across multiple cases; the individual
  question is not an independent observation, and treating each of a
  participant's ~9–39 answered questions as if it were a separate,
  independent participant would understate variance and inflate
  apparent significance. A future confirmatory analysis must use a
  method that accounts for within-participant clustering — e.g. a
  mixed-effects/hierarchical model with a per-participant random
  effect, a cluster-robust variance estimator, or an analysis
  aggregated to one summary value per participant before comparison
  across conditions — not a naive per-question proportions test that
  treats every question as its own participant.
- **Binary correctness outcomes** (e.g. a single question's
  SHARED/DISJOINT/INDETERMINATE answer scored correct/incorrect against
  the answer key) are a natural fit for a generalized linear
  mixed-effects model with a binomial/logistic link and a
  per-participant random intercept, or an equivalent
  clustering-aware alternative — the exact choice is deferred to
  `docs/research/wg-study-preregistration.md` §6.
- **Repeated observations per participant** (multiple cases, multiple
  pairwise questions per case) argue for a repeated-measures-aware
  design regardless of which specific test family is ultimately chosen;
  this is the same clustering concern stated generally above, restated
  here because it directly determines which test families are even
  eligible.
- **Condition comparisons** (A-vs-B, B-vs-C, A-vs-C) require a
  multiple-comparison correction across the three comparisons (e.g.
  Bonferroni or Holm — not yet chosen, see
  `docs/research/wg-study-preregistration.md` §6) applied consistently,
  not selectively to whichever comparisons turn out significant.
- **Response time** is a continuous, typically right-skewed measure;
  a future analysis should not assume normality without checking, and
  should consider a log transform, a non-parametric comparison, or a
  suitable generalized linear model — again deferred, not decided here.

**This document does not lock in a specific statistical test.** Doing
so before the sample size and unit-of-analysis decisions in
`docs/research/wg-study-preregistration.md` §5–§6 are settled would
mean choosing a test blind to the design it will actually run on. The
final method must be frozen in writing, in the preregistration
document, before any confirmatory data collection begins — never
selected or adjusted after real data has been seen.

## 13. Multiple-comparison considerations

Restated for reporting (not analysis-design) purposes: a report presents
all three pre-specified condition comparisons together, with the same
correction applied to all three, in the same report — never a subset
chosen because the others were non-significant, and never a correction
applied only after seeing which comparisons "need" one.

## 14. Exploratory analyses

Any analysis not listed in §9 (e.g. a per-case-type breakdown noticed
only after looking at the data, or a response-time-by-accuracy
interaction) may be reported, but only in a clearly labeled "Exploratory
analyses (not pre-registered, hypothesis-generating only)" section,
never intermixed with or presented as if it were a confirmatory result
from §9. No p-value from this section is described as "significant" in
the confirmatory sense; at most, it is described as suggestive and
flagged as a candidate for a future pre-registered confirmatory test.

## 15. Deviations from preregistration

Any way the actual collected data or analysis departs from
`docs/research/wg-study-preregistration.md` (e.g. a different final
sample size than planned, a participant excluded for a reason not
listed in that document's §8, a test family substituted for the one
frozen there) is reported explicitly, with the reason, in its own
"Deviations" section — never silently absorbed into the main results as
though the preregistration had always matched what was done. This
mirrors that document's own §10 commitment.

## 16. Limitations

A report states, at minimum, every applicable item from §17 (threats to
validity) as it actually bears on the collected data — e.g. if the
final sample size was small, the report says so and states what that
means for the precision of the reported effect sizes and intervals,
rather than only listing the threat abstractly.

## 17. Threats to validity

In addition to `docs/research/wg-study.md` §15's existing list, a report
must address:

- **Same-author benchmark construction.** Every WG-Study case is drawn
  from a WG-Bench fixture whose ground truth was authored by the same
  person who built Witnessgraph's production engine and every prior
  WG-Bench iteration (`docs/research/wg-study.md` §15 already states
  this for the case set generally; a report restates it specifically in
  light of whatever result was found).
- **Synthetic/controlled cases.** All 9 cases are synthetic and
  relabeled, not drawn from real casework; a result here says something
  about reasoning over this specific representation, not automatically
  about real investigative material.
- **Participant expertise.** This protocol does not currently restrict
  or record participant expertise/background (no demographic field
  exists in the schema — intentionally, see §16 of the mission this
  document responds to). A report cannot claim a finding generalizes to
  professional analysts specifically unless the actual participant pool
  is described and that description supports the claim.
- **Sample size.** See
  `docs/research/wg-study-preregistration.md` §5 — until that section
  is completed with a justified target, any report's precision is
  whatever the pilot's small sample happens to produce, and must be
  reported as such (wide intervals expected, not a defect to explain
  away).
- **Learning effects.** A participant sees all 9 cases in one session;
  an order effect (getting better/worse across the session) is possible
  and is exactly what per-participant case-order randomization
  (`docs/research/wg-study.md` §7) exists to let a future analysis
  check for, not eliminate.
- **Condition imbalance.** See §3 — between-subject hash-based
  assignment does not guarantee exactly equal arms.
- **Interface effects.** The current interface is a plain CLI
  (`docs/research/wg-study-participant-protocol.md`); a finding could
  reflect how well a participant tolerates a CLI-based task as much as
  the underlying provenance-reasoning question.
- **Response-time measurement.** Timing is measured with
  `time.perf_counter()` around the exact console read/write calls in
  `session.py`; it includes any time the participant spends distracted
  or interrupted mid-question, since there is no mechanism to detect or
  exclude such gaps. Report response-time results with this caveat.
- **Task comprehension.** A participant who does not understand the
  instructions may answer INDETERMINATE frequently or answer
  inconsistently; §10's usability-focused pilot phase exists
  specifically to surface this before it contaminates a confirmatory
  run.
- **Ecological validity.** A short CLI task with synthetic, relabeled
  cases is not equivalent to real casework performed under real
  professional conditions, time pressure, or stakes.
- **Provenance model assumptions.** WG-Study's ground truth treats two
  chains as SHARED exactly when their authored root-evidence label sets
  intersect (`docs/research/wg-study.md` §6); this is a property of the
  declared case model, not an independently verified fact about any
  real-world evidence.
- **Analyst interpretation differences.** Different participants may
  reasonably interpret "the same underlying evidence" differently even
  given identical information; the INDETERMINATE option exists partly
  to let a participant register genuine uncertainty rather than forcing
  a guess that would look like disagreement about ground truth.
- **Byte-distinct/same-source limitation.** Root-evidence identity in
  this protocol is evaluated at the level of the case model's declared
  `EvidenceItem` identifiers, not at the level of, e.g., byte-for-byte
  file comparison or independent source verification; two records
  sharing a root evidence id are "the same declared source" in this
  protocol's terms, not independently confirmed to be the literal same
  physical artifact by some means outside the model.
- **Provenance ≠ epistemic independence.** Disjoint root evidence in
  this protocol's terms is a property of the declared case model, not
  proof that two observations are independent, authentic, or truthful
  in the everyday sense (see §21 below and
  `docs/research/wg-study.md` §1). A report must never describe a
  DISJOINT finding as "independently verified" or "corroborated" in
  that stronger sense.
- **Possible ceiling/floor effects.** If Condition C reaches
  near-perfect accuracy on most case types, remaining variance may be
  too small to detect a further B-vs-C difference regardless of true
  effect size; conversely, near-chance performance across all
  conditions on a hard case type may reflect task difficulty rather
  than a condition effect. Either pattern is itself worth reporting
  descriptively (§8) even before any inferential comparison.

## 18. Reproducibility requirements

A report must state, or link to, all of: the exact `freeze` output for
the study version(s) covered (§1), the exact commit/software version of
this repository used to run the sessions, the raw
`participant_responses.jsonl` file (or a clear statement of where it is
archived, if not included directly, given its `.gitignore`d status —
see `docs/research/wg-study.md` §13), the `validate-dataset` output run
against that file, and the exact `analyze` output (or equivalent direct
`analysis.analyze` call) the reported numbers were computed from. A
number in a report that cannot be regenerated from these five items
together is not adequately reported under this plan.

---

## 19. Pilot vs. confirmatory study

WG-Study's real-world rollout is explicitly split into two phases with
different purposes, different data-handling rules, and — critically —
different evidentiary weight. Conflating them (treating pilot data as
if it were confirmatory evidence) is exactly the failure mode this
section exists to prevent.

### Phase 1 — Pilot

**Purpose:** usability, comprehension, timing, leakage detection, task
difficulty, variance estimation, and protocol refinement — *not*
hypothesis testing. A pilot exists to find out whether the task and
interface work as intended and to produce a rough variance estimate
that a later power calculation can use, not to produce a result that
supports or refutes H1-Study/H2-Study.

**What a pilot is for, concretely:**
- Confirming participants understand the instructions and the
  SHARED/DISJOINT/INDETERMINATE task without additional explanation.
- Confirming no condition's presentation leaks the answer key or is
  simply confusing (§17's "condition C hard to understand" possibility
  — a pilot is where this should be caught, not a confirmatory run).
- Getting a first empirical estimate of response-time and outcome
  variance, needed as an input to §12's eventual power calculation.
- Surfacing any protocol friction (confusing wording, an
  unrepresentative case, a CLI usability problem) while the cost of
  fixing it is still low.

**Pilot data must not be used as confirmatory evidence** for
H1-Study/H2-Study unless a future revision of
`docs/research/wg-study-preregistration.md` explicitly states, in
advance of the pilot's own data collection, that the pilot is being run
as (or will be pooled into) the confirmatory dataset — this document
does not authorize that by default, and no such statement currently
exists in that document.

### Phase 2 — Confirmatory / formal study

**Purpose:** test H1-Study/H2-Study using the pre-registered analysis
plan, once `docs/research/wg-study-preregistration.md` §5 (sample size)
and §6 (statistical test family) are completed in writing — informed by
Phase 1's variance estimate, among other inputs — and, separately, once
`docs/research/wg-study-consent-ethics.md`'s ethics/institutional
determination is resolved. A confirmatory run's results are reported
per §1–§18 above and interpreted per §21.

**A pilot is not skippable by being small.** A small confirmatory-labeled
study run without having first fixed sample size and test family in
writing is not a "small confirmatory study" — it is an unregistered
pilot mislabeled as confirmatory, which this document exists to
prevent.

---

## 20. Research-to-practice significance

The practical value this study investigates is **not** "an automated
system can replace a forensic or intelligence analyst's judgment."
That claim is out of scope for this protocol and is not made anywhere
in this repository. What is actually being investigated is narrower and
more concrete — whether making provenance chains inspectable, in the
specific way Witnessgraph's recursive root-evidence resolution does,
helps a human reader avoid a specific, well-defined interpretive error.
Concretely, the intended (not proven) benefits under evaluation are:

- Making provenance chains inspectable to a human reader, rather than
  leaving relationship-derivation depth opaque.
- Exposing when multiple graph paths actually rely on the same
  underlying declared evidence, versus appearing structurally distinct
  while sharing a root.
- Reducing structural path-count overinterpretation — the tendency to
  read "many paths" as "many independent confirmations" when the paths
  may recursively resolve to the same root evidence.
- Preserving provenance through normalization/derivation layers (e.g.
  `NormalizedEvent` indirection) rather than losing it once data has
  passed through such a layer.
- Making analytical conclusions traceable back to the specific
  evidence they rest on.
- Helping an investigator distinguish "more paths" from "more
  underlying evidence" — the central distinction this entire research
  program (WG-Bench and WG-Study together) exists to make precise and,
  eventually, to test in human hands.

**These are intended benefits to be evaluated, not benefits this
repository has established.** No claim in this document, or in any
other WG-Study document, should be read as asserting that any of the
above has been demonstrated — that is exactly what a future
confirmatory study (§19) would test.

## 21. The practical claim, stated carefully

To avoid overstatement in any future write-up, the practical claim this
research program is entitled to make — now, and even after a positive
confirmatory result — is bounded as follows:

> Witnessgraph investigates whether provenance-aware graph reasoning can
> help analysts distinguish structural multiplicity from provenance
> multiplicity.

> The system does not establish epistemic independence merely because
> root evidence identifiers differ.

> Disjoint provenance is a property of the declared case model, not
> proof that two observations are independent, authentic, or truthful.

No document in this repository may state a stronger claim than these
three sentences license, regardless of what a future pilot or
confirmatory result shows. A positive result narrows to "helping
analysts" under the specific, controlled conditions tested; it does not
extend to "proving independence," "verifying authenticity," or any
claim about ground truth outside this protocol's own declared case
model.

## 22. Candidate research contribution

Witnessgraph provides a deterministic mechanism for recursively
resolving relationship provenance to root `EvidenceItem` identifiers
through `NormalizedEvent` indirection, allowing structural graph-path
multiplicity to be evaluated separately from overlap in declared root
evidence.

**This is a candidate research contribution whose empirical usefulness
remains to be tested.** It is not claimed to be universally novel, no
claim is made that no other system can do this, and no claim is made
that prior art in provenance-tracking or evidence-graph systems has been
exhausted or surveyed. WG-Bench (V1–V3) establishes that the mechanism
behaves correctly against independently-authored ground truth at the
computational level; WG-Study is the mechanism by which this repository
would establish (or fail to establish) that the same distinction is
useful to a human reader — which is the actual, narrower claim this
research program is built to test.

## 23. Null and negative results — explicit interpretation rules

This section exists to make cherry-picking structurally difficult by
fixing, in advance, how specific negative or mixed outcomes must be
described. A future report is expected to match its language to
whichever of these actually occurred, not to reach for the most
favorable of these framings regardless of the data.

- **If the study finds no meaningful difference between Condition B and
  Condition C:** this is evidence against the practical-usefulness
  hypothesis (recursive resolution's value fails to transfer into a
  legible human-readable benefit beyond direct-evidence references
  alone) — reported as exactly that, not reframed as a "successful null
  result confirming the system works as expected" or omitted.
- **If Condition C improves accuracy but substantially increases
  response time relative to A/B:** both effects are reported together,
  explicitly, as a speed/accuracy trade-off — never reporting the
  accuracy gain alone while leaving the time cost for a footnote or
  omitting it.
- **If Condition C improves provenance classification (accuracy) but
  does not reduce the false-corroboration rate specifically:** this
  exact, narrower finding is reported precisely as stated — improved
  general accuracy is not substituted for, or conflated with, the
  primary outcome's specific claim about false corroboration.
- **If participants cannot understand Condition C's presentation** (near-
  chance accuracy specifically in that condition, or qualitative pilot
  feedback indicating confusion): this is reported as a usability/
  presentation-design finding, not silently excluded from the dataset
  or reported as if it were evidence about human provenance reasoning
  in general. Per §17/§19, this is exactly the class of finding the
  pilot phase exists to catch before a confirmatory run; if it appears
  only in a confirmatory run, it must still be reported, not discarded.
- **General rule:** every pre-specified comparison from §9 is reported
  regardless of its outcome. A comparison is never dropped from a
  report because it was non-significant or "unclear," and no reframing
  of a null result as a success (or a positive result as more decisive
  than its confidence interval supports) is permitted under this plan.

## 24. Research checklist

**Before pilot:**
- [ ] Ethics/institutional determination resolved
  (`docs/research/wg-study-consent-ethics.md`).
- [ ] Participant protocol reviewed
  (`docs/research/wg-study-participant-protocol.md`).
- [ ] Consent text reviewed (`docs/research/wg-study-consent-ethics.md`
  §3).
- [ ] Participant instructions finalized (`instructions.py`).
- [ ] Study version frozen (`python -m research.wg_study freeze`,
  output archived).
- [ ] Clean environment verified (no stray files in
  `research/wg_study/data/`; `git status` clean before starting).
- [ ] Participant runner smoke-tested end to end
  (`python -m research.wg_study pilot-walkthrough`, and/or `run` into a
  disposable, clearly-labeled test id later deleted — never left mixed
  into the real dataset).
- [ ] Data-storage procedure established (where
  `participant_responses.jsonl` will be archived after collection,
  consistent with §18).

**Before confirmatory collection:**
- [ ] Sample-size calculation finalized
  (`docs/research/wg-study-preregistration.md` §5).
- [ ] Statistical analysis plan frozen
  (`docs/research/wg-study-preregistration.md` §6, informed by §12
  above).
- [ ] Protocol preregistered (an actual registry submission — OSF,
  AsPredicted, or equivalent — not merely this repository's draft
  document).
- [ ] Software/study version frozen for the confirmatory run
  (`python -m research.wg_study freeze`, output archived and referenced
  in the registration).
- [ ] Exclusion rules finalized in writing
  (`docs/research/wg-study-preregistration.md` §8).
- [ ] Data-retention procedure established.

**After collection:**
- [ ] Raw data preserved (the exact `participant_responses.jsonl`
  archived, not merely its computed summary).
- [ ] Dataset validated (`python -m research.wg_study validate-dataset`,
  output archived).
- [ ] Exclusions recorded (§5).
- [ ] Frozen analysis executed exactly as pre-registered.
- [ ] Any deviation from the preregistration documented (§15).
- [ ] Primary outcome reported (§6), regardless of outcome.
- [ ] Null/negative results reported per §23, regardless of outcome.
- [ ] Reproducibility artifacts archived (§18).
