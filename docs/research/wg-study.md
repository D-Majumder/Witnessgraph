# WG-Study: A Controlled Analyst-Reasoning Study

Status: **experimental infrastructure only, now including a credible
local participant-facing runner. No human study has been conducted and
no human participant data exists anywhere in this repository or its
history.** This document describes a protocol and the software built to
run it, not a completed experiment. No production Witnessgraph code
(`src/witnessgraph`, `frontend/`) was modified to build this
infrastructure. See `research/wg_study/` for the implementation,
`tests/unit/test_wg_study.py` and
`tests/unit/test_wg_study_pilot_package.py` for its test suite, and
these companion documents for the participant-facing package built on
top of this design:

- `docs/research/wg-study-participant-protocol.md` — exact session
  mechanics, what a participant sees, and every safety/isolation
  guarantee the runner makes.
- `docs/research/wg-study-consent-ethics.md` — draft consent text and
  ethics-review status (explicitly not yet reviewed or approved).
- `docs/research/wg-study-preregistration.md` — draft preregistration
  package (sample size and statistical test family are explicitly not
  yet decided).
- `docs/research/wg-study-reporting.md` — the reporting plan a future
  real dataset must be held to, including the explicit pilot-vs-
  confirmatory distinction, the practical-claim boundaries, and the
  rules preventing selective reporting of null/negative results.

Reproduce the developer-validation self-check from the repository root:

```sh
python -m research.wg_study validate
python -m research.wg_study list-cases
python -m research.wg_study freeze
python -m research.wg_study analyze
```

`analyze` will report `has_participant_data: False` and print `"No
human-participant results were collected."` — this is correct and
expected. No participant response file exists anywhere in this
repository or its history (`research/wg_study/data/` is `.gitignore`d —
see §13).

## 0. Exact commands

```sh
# Researcher: pipeline self-check (no human involved, no real data written).
python -m research.wg_study validate

# Researcher: print the fixed 9-case manifest.
python -m research.wg_study list-cases

# Researcher: print the frozen study manifest (versions, seed, case-manifest hash) --
# run this once per study version and record the output alongside any collected data.
python -m research.wg_study freeze

# Researcher/reviewer: walk through the real participant flow with correct answers
# revealed after each response; writes only to the developer-validation file, never
# the real participant dataset. See docs/research/wg-study-participant-protocol.md §1.
python -m research.wg_study pilot-walkthrough

# Participant: run one real session end to end.
python -m research.wg_study run
python -m research.wg_study run --participant-id <token>   # to resume the same assignment

# Researcher: validate a collected dataset's integrity (rejects, never repairs,
# malformed/duplicate/out-of-manifest records -- see dataset_validation.py).
python -m research.wg_study validate-dataset

# Researcher: analyze whatever real participant data currently exists.
python -m research.wg_study analyze
```

## 1. Research question

WG-Bench (V1/V2/V3, see `docs/research/wg-bench.md`) measures whether
Witnessgraph's own recursive root-evidence resolution, invoked through
its real, unmodified production API, correctly classifies fixtures
relative to independently-authored ground truth. It never involves a
human reader, and its ground-truth author is also its own implementer —
V3's own report names this as its "biggest remaining threat to
validity."

WG-Study asks a narrower, different-in-kind question:

> Does explicit root-evidence provenance reasoning help an *analyst*
> avoid false-corroboration interpretations compared with graph/path
> information without recursive root-evidence explanation?

This is **not** a question about:

- the truth of any piece of evidence,
- authenticity,
- causality,
- attribution,
- guilt, or
- epistemic independence in the everyday sense.

It is a question about whether a human reader can correctly identify a
deliberately specified **provenance-level relationship** between graph
chains and their root evidence, given one of three different
presentations of the same underlying case.

## 2. Hypotheses

**H1-Study.** Participants given explicit recursive root-evidence
provenance information (Condition C) will have a lower provenance-level
false-corroboration rate than participants given graph/path information
without recursive root-evidence explanation (Condition A).

**H2-Study.** Participants given direct evidence references (Condition
B) will perform better than path-only participants (Condition A), but
worse than participants given recursive root-evidence provenance
information (Condition C) on cases requiring provenance indirection.

Neither hypothesis is confirmed, disconfirmed, or even tested by
anything in this repository as of this document's writing. They are
stated here, precisely, so that a future pilot has a fixed, falsifiable
target to collect data against — see §18/§19.

## 3. Experimental conditions

Three between-subject presentation conditions
(`research.wg_study.model.Condition`):

| Condition | What the participant sees | What is withheld |
| --- | --- | --- |
| **A — PATH_ONLY** | Graph structure: entities, relationships, path count, each chain's own entity/relationship labels. | All evidence-reference information — no direct references, no root evidence. |
| **B — DIRECT_EVIDENCE** | Everything in A, plus each chain's *direct*, unresolved evidence-reference labels (the raw, un-followed `derived_from` ids WG-Bench's Baseline 2 also uses). | Recursively-resolved root evidence. |
| **C — WITNESSGRAPH** | Everything in B, plus each chain's recursively-resolved *root* evidence labels. | Nothing structural is additionally withheld relative to B/A — Condition C is a strict superset. |

`research/wg_study/presentation.py::present_case` is the single function
that implements this table. It is the only code path in this package
that decides what a participant actually sees, and it imports nothing
from `research/wg_study/answer_key.py` — see §6/§14 and
`tests/unit/test_wg_study.py::test_presentation_module_never_imports_answer_key`,
which parses the module's own AST to enforce this at test time, not just
by convention.

No condition uses color, layout, or ordering to hint at ground truth;
every chain's fields are emitted in a fixed structural order
(`chain_index`) regardless of any answer, and Condition C's *additional*
fields are the only thing that differs from B, never a re-ordering or
re-styling of what B already shows.

## 4. Task definition

For every case with two or more relevant chains, the participant answers
one question **per pair of chains**:

> "For chain *i* and chain *j* ...: based only on the information shown
> for this case, are their root evidence sets SHARED, DISJOINT, or is
> this INDETERMINATE from what is shown?"

Possible answers (`research.wg_study.model.Answer`):

- `SHARED_ROOT_EVIDENCE`
- `DISJOINT_ROOT_EVIDENCE`
- `INDETERMINATE`

WG-Study deliberately asks pairwise questions for **every** case with
2+ chains, not only ones whose ground truth happens to be a
partial-overlap case (see `research/wg_study/questions.py`'s module
docstring). Generating a different question *format* — one holistic
question vs. several pairwise ones — conditioned on ground truth would
itself leak a structural signal about which fixture class a case
belongs to. Asking uniformly-pairwise questions sidesteps that: a
fully-shared or fully-disjoint case is simply the case where every
pairwise answer happens to agree, not a different kind of question.

A case with **fewer than two** relevant chains (WG-Study's negative
control, case type I below) instead asks one single question — whether
there is a second, comparable chain at all — with correct answer
`INDETERMINATE` by construction (there is nothing to compare).

## 5. Case design

WG-Study's fixed, deterministic 9-case manifest
(`research.wg_study.case_builder.CASE_SELECTION`) draws each case from
an already-existing, already-tested WG-Bench V1/V2/V3 fixture — never a
newly-authored graph — one fixture per case type:

| Case type | WG-Bench fixture | Chains | Purpose |
| --- | --- | --- | --- |
| A. SHARED_ROOT | `shared-root-01` | 2 | Canonical shared-but-not-identical case. |
| B. DISJOINT_ROOT | `disjoint-roots-01` | 2 | Canonical true-independence case. |
| C. DIRECT-REFERENCE DECOY | `v3-direct-reference-decoy-01` | 2 | Direct references differ but recursively resolve to a shared root. |
| D. MULTI-LEVEL INDIRECTION | `v3-multi-level-lineage-01` | 2 | Multiple `derived_from` levels before reaching root. |
| E. MIXED DEPTH | `v3-mixed-root-depth-01` | 2 | One chain reaches root directly; the other through indirection. |
| F. PARTIAL OVERLAP | `partial-overlap-01` | 3 | Pairwise questions required; H3's exact case. |
| G. HIGH PATH MULTIPLICITY, SHARED | `high-path-shared-root-01` | 6 | Many chains, one root. |
| H. HIGH PATH MULTIPLICITY, DISJOINT | `high-path-disjoint-root-01` | 6 | Many chains, disjoint roots. |
| I. NEGATIVE CONTROL | `single-path-01` | 1 | No multiplicity to misinterpret at all. |

`research/wg_study/case_builder.py::_build_one` builds each fixture's
graph against a real, fresh `Case`/`SqliteStore`, then calls
Witnessgraph's actual, unmodified `find_all_shortest_paths` and
`analyze_paths_evidence_overlap` — used strictly to discover case
*structure* (how many chains, which entities/relationships/direct-refs/
root-evidence-ids each one touches), **never** to determine a correct
answer (see §6). Every id that appears is then relabeled with a neutral,
deterministic, per-case sequential label:

- entities → `N-01`, `N-02`, ...
- relationships → `R-01`, `R-02`, ...
- direct/unresolved references → `D-01`, `D-02`, ...
- root evidence → `E-01`, `E-02`, ...

Label assignment is sorted by the *original* content-hash id string, not
by build order, so it carries no incidental information about how the
fixture was constructed. No case, chain, or label name ever contains a
substring like `"SHARED"`, `"DISJOINT"`, `"INDEPENDENT"`, or
`"CORROBORAT"` —
`tests/unit/test_wg_study.py::test_neutral_labels_never_encode_classification`
enforces this over the full case manifest. (An earlier draft of
`case_builder.py` generated case ids like `wgstudy-01-shared_root`,
which *did* leak the classification into a participant-visible
identifier; that test caught it during development, and the case-id
scheme was corrected to the neutral `wgstudy-01` form seen in the final
manifest — see the git history of `case_builder.py` for this exact
finding, made and fixed before any commit reached `main`.)

Case representation is intentionally balanced (one fixture per type, not
weighted toward "gotcha" cases) rather than adversarially maximized —
WG-Bench V3 already exists for adversarial stress-testing of the
production engine itself; WG-Study exists to test human reasoning over a
representative case spread.

## 6. Ground-truth methodology

Ground truth (`research/wg_study/answer_key.py`) is physically separate
from participant-facing case data (`model.py`'s `StudyCase`/`ChainView`)
and from the presentation layer (`presentation.py`, which never imports
`answer_key.py` at all).

Critically, each pairwise answer is derived from the underlying WG-Bench
fixture's own **independently-authored** `GroundTruthV2.expected_chains`
root-evidence *labels* — the labels the fixture's original author wrote
by reasoning about the fixture's intended topology, before ever running
the production engine against it (see `docs/research/wg-bench.md`'s
ground-truth methodology sections for V1/V2/V3). Two chains are SHARED
in WG-Study's answer key exactly when their *authored* root-evidence
label sets intersect; DISJOINT when they do not.

WG-Study's answer key is **never** derived from calling
`analyze_paths_evidence_overlap()` and copying its verdict. The
production engine is invoked once, during case construction, solely to
discover which entities/relationships/paths exist so a faithful
participant-facing rendering can be built — see
`case_builder.py::_build_one`'s and `_build_answer_key`'s docstrings for
the exact mechanism, including how each actual returned chain is matched
to its authored ground-truth chain by root-evidence-id-set equality
(with an explicit, tested tie-break for the one case,
`DIRECT_REFERENCE_DECOY`, where two authored chains share an identical
root-label set by design).

## 7. Randomization / counterbalancing

`research/wg_study/runner.py` implements:

- **Between-subject condition assignment**
  (`assign_condition(participant_id)`): a deterministic
  `sha256(seed:participant_id) mod 3`. Each participant sees exactly one
  condition. This was chosen over a within-subject design specifically
  to avoid a participant seeing a case's Condition-B rendering and then
  its Condition-C rendering later, which would let them "solve" earlier
  cases retroactively rather than measuring genuine reasoning under one
  fixed information condition. The documented cost is a larger required
  sample size per condition than a within-subject design would need.
- **Deterministic case-order randomization**
  (`case_order(participant_id, case_ids)`): `random.Random` seeded from
  `f"{STUDY_SEED}:{participant_id}:order"`, so every participant gets a
  reproducible-but-individually-varied case order, supporting a later
  check for order effects without every participant seeing cases in the
  identical sequence.

`STUDY_SEED = "wg-study-v1-seed"` is a fixed, recorded constant. Changing
it changes every future participant's assignment/ordering and must be
treated as a new study version.

This is a deliberately simple design for a **credible pilot**, not a
fully-powered factorial study — see §16/§17.

## 8. Participant data model

`research.wg_study.model.ParticipantResponse`:

```
participant_id       str   # caller-supplied; expected to be an anonymous token
condition             Condition
case_id               str
question_id           str
answer                Answer
correct_answer        Answer   # stamped at recording time from the answer key; never shown to the participant
response_time_ms      int
timestamp             str      # ISO-8601 UTC
optional_notes        str | None
study_version         str      # model.STUDY_VERSION at recording time -- see §12
is_developer_validation bool   # True only for validation.py/session.run_pilot_walkthrough records
```

`correct_answer` is stored on every response for later analysis — this
is recorded metadata, not something the participant ever sees during the
task; the on-screen rendering path (`presentation.py`) has no access to
`answer_key.py` at all (§3/§6), so this is not a leak in the
participant-facing sense the rest of this document is concerned with.

No name, email, student id, address, phone number, or other
directly-identifying field exists in this schema —
`tests/unit/test_wg_study.py::test_participant_response_schema_has_no_identifying_fields`
pins this. The tool requires no authentication and makes no network
call anywhere in `research/wg_study/` (`storage.py` is local-filesystem
only).

## 9. Primary and secondary metrics

**Primary outcome: false-corroboration rate.** The proportion of
ground-truth-SHARED_ROOT answers (i.e., genuinely *not*
provenance-disjoint) that a participant answered DISJOINT_ROOT — this
mirrors WG-Bench's own false-corroboration definition exactly, applied
to a human response instead of a computed classifier's output. This
metric is deliberately never called "evidence independence accuracy" —
see `docs/research/wg-bench.md`'s own terminology discipline, which this
document follows for the same reason: root-evidence disjointness is a
provenance-level property, not a claim about real-world epistemic
independence, whether the reasoner is a function or a person.

**Secondary outcomes**, computed per condition
(`research.wg_study.analysis.ConditionMetrics`):

- `response_count`
- `accuracy` — provenance-level classification accuracy (never
  "evidence independence accuracy")
- `shared_root_accuracy`, `disjoint_root_accuracy`
- `partial_overlap_pair_accuracy` — restricted to pairwise (not
  single-question) responses
- `mean_response_time_ms`, `median_response_time_ms`
- `indeterminate_rate`
- `missing_response_rate`

## 10. Analysis methodology

`research/wg_study/analysis.py::analyze` computes the metrics above from
whatever responses actually exist, after unconditionally excluding every
`is_developer_validation=True` record. **If zero real-participant
responses exist — which is the case throughout this repository as of
this writing — `analyze` returns `has_participant_data=False` and the
literal message `"No human-participant results were collected."`,
computing nothing further.** It never estimates, extrapolates
interpolates, or synthesizes a value from an empty or near-empty
dataset.

No inferential statistics (p-values, confidence intervals, hypothesis
tests) are implemented anywhere in this package. This is deliberate: a
credible significance test requires committing in advance to a test
family, a multiple-comparison correction plan (three pairwise condition
comparisons — A vs B, B vs C, A vs C — invite exactly this problem), and
a minimum sample size the test's assumptions actually hold at. None of
that exists yet because no data collection has been designed at that
level of detail. A future extension adding inferential statistics must
document, at minimum: the assumptions each test requires, why that test
was selected over alternatives, the effect size reported alongside any
p-value, the confidence interval, and the multiple-comparison correction
applied across the three condition-pair comparisons — this document
records that requirement now so it cannot be silently skipped later.

## 11. Developer validation

`research/wg_study/validation.py::run_developer_validation` exercises
the full pipeline — case building, per-condition presentation, question
generation, response recording (including the local JSONL storage
round-trip), answer-key matching, and metric computation — by answering
every generated question **correctly** (per the answer key) across all
three conditions, with zero human input. Every record produced is
stamped `is_developer_validation=True` and written to a file physically
separate from the real participant-response file
(`storage.DEV_VALIDATION_FILE` vs. `storage.PARTICIPANT_RESPONSES_FILE`);
`analysis.analyze` excludes such records unconditionally, and this
exclusion is itself asserted as part of what developer validation
checks (a "does the pipeline know these aren't real data" check, not
just a "did recording work" check).

This is a pipeline-correctness self-check, **not a research result** —
it can only confirm internal consistency (do recorded answers round-trip
correctly, does the answer key resolve every question, does an
all-correct response set report 100% accuracy and zero
false-corroboration by construction), never anything about human
reasoning.

## 12. Reproducibility

- The case manifest (`case_builder.build_all_cases()`) is deterministic:
  case ids, case order, and every neutral label are fixed functions of
  the underlying fixture set, not of wall-clock time or build order.
  `tests/unit/test_wg_study.py::test_case_manifest_is_deterministic_across_independent_builds`
  builds the manifest twice independently and asserts byte-for-byte
  dataclass equality.
- `ANSWER_KEY_VERSION = "wg-study-v1"` is recorded on every
  `CaseAnswerKey` so a future study run can detect and report an
  answer-key version mismatch against any dataset collected under a
  different version.
- `STUDY_SEED` (§7) is fixed and recorded in source, not generated at
  runtime, so condition assignment and case ordering are exactly
  reproducible from the seed alone.
- Software/environment: Python 3.11, this repository's `pyproject.toml`
  dependency set — identical to WG-Bench's own reproducibility baseline
  (see `docs/research/wg-bench.md`).
- **Study-freeze manifest** (`research/wg_study/manifest.py`,
  `python -m research.wg_study freeze`): deterministically recomputes a
  `StudyManifest` — study version, answer-key version, case count/ids, a
  SHA-256 hash of the canonical case manifest, condition values,
  randomization seed and protocol description, and the Python/platform
  version — from the current case builder and answer key.
  `model.STUDY_VERSION` is stamped on every stored `ParticipantResponse`
  (§8), so a collected dataset can always be checked against the exact
  frozen package that produced it; `dataset_validation.py` rejects any
  record whose `study_version` does not match the dataset's own declared
  version (a "mixed study versions" dataset). Run `freeze` once per
  study version and keep its output alongside any collected data as that
  version's permanent record — this is WG-Study's reproducibility/
  version-capture mechanism, standing in for a heavier snapshot/tag
  scheme since the manifest is fully and deterministically
  recomputable from source.

## 13. Privacy / data handling

- **Local-only.** `storage.py` performs no network I/O anywhere.
- **No cloud upload.** Nothing in this package makes an HTTP request.
- **No unnecessary personal data.** The schema (§8) carries no name,
  email, address, or other directly-identifying field.
- **No authentication required.** The CLI (`__main__.py`) requires no
  login or credential.
- **Safe output paths.** `storage.append_response`'s `out_dir` parameter
  is either the module's own fixed `data/` directory or an explicit
  `Path` a caller constructs directly in code — never a path built by
  concatenating participant-supplied strings, so a hostile
  `participant_id` cannot cause a path-traversal write (pinned by
  `tests/unit/test_wg_study.py::test_append_response_never_uses_participant_supplied_path`).
- **Explicit dataset versioning.** `answer_key_version` on every
  `CaseAnswerKey` (§12).
- `research/wg_study/data/` is `.gitignore`d — no participant or
  developer-validation response file is committed to this repository.
- **Dataset integrity validation.** `research/wg_study/dataset_validation.py`
  (`python -m research.wg_study validate-dataset`) checks every raw
  record in the participant dataset file — missing fields, mixed study
  versions, unknown condition/case/question ids, malformed answers,
  negative response times, and duplicate participant/case/question
  keys — and reports each rejection with a reason. It never repairs or
  guesses a corrected value; a malformed record is excluded and logged,
  never silently coerced
  (`tests/unit/test_wg_study_pilot_package.py::test_validate_dataset_never_repairs_only_rejects`).
- **No participant-controlled filesystem paths, no command execution
  through participant input.** The interactive runner
  (`research/wg_study/session.py`) only ever writes to the module's
  fixed `data/` directory (or an explicit caller-constructed `Path` in
  tests/tooling), and only ever parses a typed answer against a fixed
  alias table (`session._ANSWER_ALIASES`) — an unrecognized string is
  rejected and reprompted, never executed or interpolated anywhere. See
  `docs/research/wg-study-participant-protocol.md` §4 for the full
  session-integrity guarantee list.

## 14. Ethics considerations

This is technical pilot-study **infrastructure**, not an approved human-
subject study. No claim of institutional review or ethics-committee
approval is made anywhere in this repository, because none has been
sought — building this software did not itself involve any human
participant. Before any real participant data is collected under this
protocol, the study owner should determine whether applicable
institutional or regulatory rules require ethics/IRB-equivalent review
for this kind of task-based, anonymous, non-deceptive study, and obtain
it if so, before recruiting anyone. This document does not substitute
for that determination. See `docs/research/wg-study-consent-ethics.md`
for a draft consent text and risk assessment prepared for that
review — itself explicitly marked as unreviewed and unapproved.

## 15. Threats to validity

- **No participant data exists.** Every metric this package can compute
  is currently `None`/"no data" — see §10's demonstrated `analyze()`
  output. Nothing in this document should be read as a result.
- **Small, non-adversarially-maximized case set (9 cases).** Chosen for
  balanced coverage of the taxonomy in §5, not statistical power; a real
  pilot's minimum viable sample size has not been computed here (that
  requires committing to an analysis plan first — see §10).
- **Fixture provenance.** Every underlying case is drawn from a WG-Bench
  fixture whose ground truth was authored by the same person who built
  Witnessgraph's production engine and every prior WG-Bench iteration
  (V1/V2/V3 all name this as a threat to validity; it applies here
  identically, one level up — a human study using benchmark cases the
  study designer also authored is not independent of the design of
  those cases, whatever the underlying engine says).
- **Between-subject design cost.** Larger required sample size per
  condition than a within-subject design, and no way to measure a given
  individual's *improvement* from one condition to another — only
  between-group comparison (§7).
- **Neutral-labeling residual risk.** WG-Study relabels every id to
  avoid semantic leakage, but cannot fully rule out *structural* leakage
  — e.g., a sufficiently attentive participant across many cases in the
  DIRECT_EVIDENCE condition specifically could in principle infer that
  "shared root" cases correlate with some structural regularity in how
  WG-Bench fixtures happen to be built, since the case pool is small and
  drawn from a fixed, already-published fixture set. A larger, more
  varied case pool would reduce (not eliminate) this risk.
  §5 documents one real instance of exactly this class of risk
  (case-id leakage) that was caught and fixed before commit.
  - **CLI-only interface.** The current runner is a plain CLI
    (`__main__.py`), not a graphical interface with precise timing
    capture; §16 discusses this as an open engineering decision for a
    real pilot, not yet made.

## 16. Expected limitations for a real pilot

Before real participant collection, the following remain open and are
explicitly out of scope for this milestone:

- Participant recruitment plan and sample-size target — the
  preregistration draft (`docs/research/wg-study-preregistration.md`)
  explicitly leaves §5 (sample size) and §6 (statistical test family)
  unfilled pending this.
- ~~A genuinely usable participant-facing interface.~~ **Done as of this
  milestone**: `python -m research.wg_study run` is a credible local CLI
  walkthrough (`research/wg_study/session.py`, `instructions.py`) built
  strictly on the existing `model.py`/`presentation.py`/`questions.py`/
  `runner.py` architecture, with zero changes to case-building,
  presentation, or answer-key logic. See
  `docs/research/wg-study-participant-protocol.md` for its exact
  mechanics. A minimal local-only web page remains a possible future
  alternative front end but is not required to run a credible pilot.
- Ethics/IRB-equivalent review determination and, if required, approval
  (§14) — a draft consent/risk document now exists
  (`docs/research/wg-study-consent-ethics.md`) to support that review,
  but the review itself has not happened.
- A pre-registered analysis plan, including the inferential-statistics
  requirements listed in §10, decided *before* any real data is seen —
  a draft now exists (`docs/research/wg-study-preregistration.md`) with
  its sample-size and test-family sections explicitly left open pending
  the decisions §5/§6 of that document describe.
- Possibly a larger/more varied case pool (§15) if a pilot's initial
  results suggest structural-leakage risk is material.
- An in-software consent-acknowledgment step before a real session
  starts (`docs/research/wg-study-consent-ethics.md` §6) — the current
  `run` command does not yet display or require acknowledgment of the
  draft consent text.
- A dedicated per-participant data-deletion/withdrawal command
  (`docs/research/wg-study-consent-ethics.md` §5) — currently a manual
  procedure.

## 17. Exact procedure for a future pilot

1. Resolve §14's ethics/IRB-equivalent determination and, if required,
   obtain approval, using `docs/research/wg-study-consent-ethics.md` as
   the starting draft.
2. Fix the analysis plan in writing, before recruiting anyone, by
   completing `docs/research/wg-study-preregistration.md` §5 (sample
   size) and §6 (statistical test family, multiple-comparison
   correction) — the sections that document currently leaves open.
3. Run `python -m research.wg_study freeze` and keep its output as this
   study version's permanent record (§12).
4. Recruit participants and assign each an anonymous `participant_id`
   (no name/email stored — see §13).
5. Each participant runs `python -m research.wg_study run
   --participant-id <token>` directly — see
   `docs/research/wg-study-participant-protocol.md` for exactly what
   they will see and do. This already implements condition assignment,
   case ordering, presentation, question generation, and recording
   end to end; no researcher intervention is needed per session beyond
   supplying the token.
6. Periodically run `python -m research.wg_study validate-dataset` and
   resolve any reported rejections before proceeding further.
7. After collection, run `python -m research.wg_study analyze` (or call
   `analysis.analyze` directly) against
   `storage.PARTICIPANT_RESPONSES_FILE`.
8. Apply the pre-registered analysis plan from step 2 to the resulting
   per-condition metrics. Report results honestly, including a null or
   negative result — see §19.

## 18. What would support H1-Study/H2-Study

- H1-Study: Condition C's false-corroboration rate is measurably and
  (per the pre-registered analysis plan) significantly lower than
  Condition A's, on a sample size the analysis plan determined was
  sufficient, replicated at least once.
- H2-Study: Condition B's false-corroboration rate falls strictly
  between A's and C's specifically on the cases requiring provenance
  indirection (case types C/D/E in §5 — `DIRECT_REFERENCE_DECOY`,
  `MULTI_LEVEL_INDIRECTION`, `MIXED_DEPTH`), mirroring WG-Bench V2/V3's
  own finding that Baseline 2 (direct-evidence, non-recursive) is caught
  out specifically on those case types while tying Witnessgraph
  elsewhere.

## 19. What would falsify them

Per the mission's own falsification criteria, the hypotheses are **not**
supported if any of the following hold once real data exists:

- Condition C does not reduce false-corroboration relative to Condition
  B (H1-Study's B-vs-C comparison, and the sharper form of H2-Study);
- any apparent difference disappears under a reasonable replication
  (repeat data collection, different participant pool);
- participants cannot understand the provenance representation shown in
  Condition C (e.g., near-chance accuracy across all case types, not
  just the indirection-specific ones — evidence of a presentation
  failure, not a reasoning failure);
- Condition B performs equivalently to Condition C specifically on the
  provenance-indirection case types (this would mirror WG-Bench V3's own
  "narrow, not widened" finding for the *computational* comparison,
  suggesting recursive resolution's value is real for the engine but
  does not transfer into a legible human-readable benefit).

A result showing no human benefit from Condition C is a scientifically
useful, reportable outcome under this protocol — not a failure of the
infrastructure.

## 20. Recommended next milestone

This milestone completed the software side of §16's prior list: a
credible local participant-facing runner
(`python -m research.wg_study run`), a developer/pilot walkthrough mode
that cannot contaminate real data, a study-freeze/versioning mechanism,
dataset-integrity validation, and draft consent/ethics and
preregistration documents. What remains, in priority order:

1. **Ethics/IRB-equivalent determination and approval**, using
   `docs/research/wg-study-consent-ethics.md` as the starting draft
   (§14) — a process/documentation step, not software work.
2. **Complete the preregistration's open sections** —
   `docs/research/wg-study-preregistration.md` §5 (sample size) and §6
   (statistical test family and multiple-comparison correction),
   decided in writing before any real data is seen.
3. Optionally: an in-software consent-acknowledgment step and a
   dedicated withdrawal/deletion command (both listed in
   `docs/research/wg-study-consent-ethics.md` §6) before recruiting at
   any scale beyond a small internal pilot.

Only after (1) and (2) are in place should real participant recruitment
begin.
