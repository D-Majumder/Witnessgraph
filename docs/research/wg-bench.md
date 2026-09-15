# WG-Bench: An Evidence-Overlap Corroboration Benchmark

Status: completed experimental research infrastructure and initial
benchmark run. No Witnessgraph production code
(`src/witnessgraph`, `service/`, `api/`, `frontend/`) was modified to
build or run this benchmark. See `research/wg_bench/` for the
implementation and `tests/unit/test_wg_bench.py` for its own test
suite.

Reproduce the results in this document from the repository root:

```sh
python -m research.wg_bench
```

## 1. Research question

Does explicit root-evidence overlap analysis
(`witnessgraph.correlate.graph.analyze_paths_evidence_overlap`) reduce
false-corroboration interpretations that would arise from graph path
multiplicity alone?

Terminology used throughout this document, deliberately: **root-evidence
independence at the provenance level** and **root-evidence
disjointness**. This document never uses "epistemic independence,"
"evidentiary truth," "corroboration proof," "authenticity,"
"causality," or "attribution" to describe what Witnessgraph's analysis
establishes — see §11.

## 2. Hypotheses

- **H1.** Root-evidence overlap analysis reduces false-corroboration
  classifications relative to path-count-only analysis on a
  ground-truth benchmark containing shared-root and disjoint-root graph
  chains.
- **H2.** Equivalent benchmark inputs processed through independent
  runs produce deterministically equivalent Witnessgraph objects,
  manifests, graph structures, and analysis results wherever the
  existing deterministic model promises such equivalence.
- **H3.** The current Boolean/null evidence-independence representation
  loses information for partial-overlap cases where multiple chains
  share some, but not all, root `EvidenceItem` ids.

## 3. Benchmark design

WG-Bench (`research/wg_bench/`) is a deterministic, hand-authored
fixture suite. Each fixture:

1. builds a small graph of `Entity`/`Relationship` objects directly
   against a real `Case`/`SqliteStore` (the same store production code
   uses — no test doubles, no mocking of `correlate.graph`);
2. is evaluated by calling Witnessgraph's actual, unmodified
   `find_all_shortest_paths` and `analyze_paths_evidence_overlap`
   through their ordinary Python API — never the CLI's text output;
3. carries hand-authored ground truth (`research/wg_bench/model.py`'s
   `GroundTruth` dataclass) written by reasoning about the fixture's
   intended topology *before* consulting what the implementation
   returns, kept in a physically separate dataclass from what the
   runner actually observes (`FixtureEvaluation`) so the two can never
   be confused with each other.

Every fixture records: its graph structure, expected shortest-path
count, each expected chain's root evidence set, whether those sets are
identical/disjoint/partially overlapping, whether the fixture is
adversarial, the expected baseline classification, the expected
Witnessgraph classification, and any known representational limitation
the fixture is designed to expose.

## 4. Fixture taxonomy

Eight fixture classes, one hand-authored fixture per class (8 fixtures
total):

| Class | Fixture id | Paths | Root sets | Purpose |
| --- | --- | --- | --- | --- |
| `SINGLE_PATH` | `single-path-01` | 1 | n/a | Sanity floor: no multiplicity to interpret at all. |
| `SHARED_ROOT` | `shared-root-01` | 2 | `{E1}`, `{E1,E2}` | Canonical shared-but-not-identical false-corroboration case. |
| `DISJOINT_ROOTS` | `disjoint-roots-01` | 2 | `{E1}`, `{E2}` | The benchmark's "true positive": multiplicity really is independent. |
| `IDENTICAL_ROOT_SETS` | `identical-root-sets-01` | 3 | `{E1}` × 3 | Strongest minimal case: 3 "different" chains, 1 record. |
| `PARTIAL_OVERLAP` | `partial-overlap-01` | 3 | `{E1,E2}`, `{E2,E3}`, `{E4}` | H3: boolean information loss. |
| `BYTE_DISTINCT_SAME_SOURCE` | `byte-distinct-same-source-01` | 2 | `{E1}`, `{E2}` (E1≠E2 but same conceptual record) | Adversarial: provenance vs. epistemic independence. |
| `PATH_COUNT_DECEPTION` | `path-count-deception-01` | 8 | `{E1}` × 8 | Same failure mode as `IDENTICAL_ROOT_SETS`, at scale. |
| `DISJOINT_MULTI_EVIDENCE` | `disjoint-multi-evidence-01` | 2 | `{E1,E2}`, `{E3,E4}` | Multi-root-per-chain resolution, still disjoint. |

## 5. Ground-truth methodology

Every `GroundTruth` value was written by hand, reasoning directly about
each fixture's designed topology (which relationship cites which
evidence label), before the benchmark runner is ever invoked against
it. The ground truth is never derived by running
`analyze_paths_evidence_overlap` and copying its output back — the
per-fixture Python modules under `research/wg_bench/fixtures/` state
the intended path count and each chain's intended root evidence set as
literal, independently-declared values (`research/wg_bench/model.py`'s
`ExpectedChain`), and `research/wg_bench/evaluation.py` is the *only*
place ground truth and actual Witnessgraph output are compared, using
physically separate dataclasses (`GroundTruth` vs. `FixtureEvaluation`)
so the two can never be silently merged.

`tests/unit/test_wg_bench.py::test_fixture_build_matches_its_own_ground_truth`
independently confirms every fixture's `build()` function actually
produces the graph its ground truth describes — a correctness check on
the fixtures themselves, prior to, and separate from, any claim about
Witnessgraph's behavior.

## 6. Baseline definition

`research/wg_bench/baseline.py` implements a deliberately simple,
provenance-blind classifier: it inspects *only* the count of
tied-shortest chains `find_all_shortest_paths` returns.

```
classify_by_path_count(path_count):
    "no_or_single_path"  if path_count < 2
    "multiple_paths"     if path_count >= 2
```

`implies_independent_corroboration(classification)` is `True` exactly
when the classification is `"multiple_paths"` — this operationalizes,
as one explicit line, the naive reading the research question asks
about: that a consumer of path-count-only output, with no
`--explain`/evidence-lineage information, would treat 2+ structurally
distinct chains as implying independent, corroborating support. The
baseline never inspects `derived_from`, `EvidenceItem`, or any other
provenance field.

## 7. Witnessgraph method

For each fixture, WG-Bench calls
`witnessgraph.correlate.graph.find_all_shortest_paths` (default
`max_depth`/`limit`) followed by
`witnessgraph.correlate.graph.analyze_paths_evidence_overlap` on the
result — the exact, unmodified functions the CLI's `graph paths
--explain` and the API/UI's evidence-independence panel already use.
Its `fully_evidence_independent` (`True`/`False`/`None`) is the
method's binary/ternary prediction; `shared_evidence_ids` is recorded
alongside it.

## 8. Metrics — exact definitions

All metrics are computed by `research/wg_bench/metrics.py` as exact
ratios of integer counts over a fixed, known fixture composition —
never estimated, never requiring interpretation of an approximate
value.

Evaluations are split into four groups that are **never pooled into one
aggregate score**:

- **binary** — fixtures where a well-defined "are all chains
  root-evidence-disjoint?" question applies (2+ expected chains), that
  are not adversarial and not the `PARTIAL_OVERLAP` class (5 fixtures).
- **single_path** — fixtures with fewer than 2 expected chains, where
  the independence question does not apply at all (1 fixture).
- **partial_overlap** — the `PARTIAL_OVERLAP`-class fixture(s), reported
  separately because the top-level boolean is a coarser answer than the
  question these fixtures actually pose (1 fixture).
- **adversarial** — fixtures deliberately probing a known limitation of
  the provenance model itself (1 fixture); their confusion-matrix
  numbers are provenance-level correctness only and must never be read
  as validating the adversarial claim (see §11).

For the **binary** group, a confusion matrix is computed per method
(baseline, Witnessgraph), positive class = ground truth
`root_sets_disjoint is True`:

1. **False-corroboration rate** = `FP / (FP + TN)` (the standard False
   Positive Rate): of every fixture that is truly *not*
   root-evidence-independent, the fraction the method wrongly reports
   as independent/implying corroboration.
2. **Provenance-level classification accuracy** = `(TP + TN) / total`,
   computed only where the binary question is well-defined.
3. **Precision** = `TP / (TP + FP)`.
4. **Recall** = `TP / (TP + FN)`.
5. **Confusion matrix** — raw `TP`/`FP`/`FN`/`TN` counts, reported
   alongside every ratio so no ratio is ever presented without its
   denominator.
6. **Partial-overlap information-loss cases** — for each
   `PARTIAL_OVERLAP`-class fixture, every pair of returned chains is
   checked for root-evidence disjointness directly from
   `chains[i].root_evidence_ids` (already part of the existing API);
   `pairs_masked_by_boolean` counts pairs that are genuinely disjoint
   but not surfaced because the single top-level boolean is `False` as
   soon as *any* pair overlaps.
7. **Deterministic replay success rate** = fraction of fixtures for
   which two independent builds (fresh `Case` directories, same
   `build()` call) produce byte-identical manifest hashes *and*
   byte-identical canonical JSON for
   `all_shortest_paths_result_to_json`/`paths_evidence_overlap_to_json`.

No "epistemic independence accuracy" is computed anywhere in this
benchmark — see §11 and §14 for why that would be a category error.

## 9. Results

Full per-fixture JSON is reproducible via `python -m research.wg_bench
--out-dir <dir>`; the run below is the actual output of `python -m
research.wg_bench` at the HEAD this document was committed against.

**Binary-classification group** (`shared-root-01`, `disjoint-roots-01`,
`identical-root-sets-01`, `path-count-deception-01`,
`disjoint-multi-evidence-01`):

| Method | TP | FP | FN | TN | Accuracy | Precision | Recall | False-corroboration rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline (path-count only) | 2 | 3 | 0 | 0 | 0.40 | 0.40 | 1.00 | **1.00** |
| Witnessgraph (root-evidence overlap) | 2 | 0 | 0 | 3 | **1.00** | 1.00 | 1.00 | **0.00** |

Every one of the 3 truly-not-independent binary fixtures
(`shared-root-01`, `identical-root-sets-01`,
`path-count-deception-01`) is a baseline false-corroboration case
(`baseline_false_corroboration = True`) and correctly *not* a
Witnessgraph false-corroboration case
(`witnessgraph_false_corroboration = False`).

**Single-path group** (`single-path-01`): no multiplicity exists;
neither method reports anything to compare
(`fully_evidence_independent = None`, baseline =
`no_or_single_path`) — a well-formed, correctly inapplicable result,
not a data point in the false-corroboration count.

**Partial-overlap group** (`partial-overlap-01`): baseline reports
`multiple_paths` (implying corroboration for all 3 chains at once,
1 false-corroboration case against the "not fully independent" ground
truth); Witnessgraph correctly reports
`fully_evidence_independent = False`. Pairwise accounting:
`total_chain_pairs = 3`, `disjoint_pairs = 2`
(chain A/chain C and chain B/chain C), `pairs_masked_by_boolean = 2`
— see §10.

**Adversarial group** (`byte-distinct-same-source-01`): Witnessgraph
reports `fully_evidence_independent = True`, matching this fixture's
declared ground truth for *provenance-level* disjointness exactly (the
confusion-matrix cell for this fixture is trivially a "true positive"
by construction) — see §11 for why this number must not be read as
validating anything about real-world independence.

**Deterministic replay**: 8/8 fixtures (100%) produced byte-identical
manifest hashes and byte-identical canonical analysis JSON across two
independent builds (`tests/unit/test_wg_bench.py::test_fixture_is_deterministic_across_independent_builds`,
enforced on every CI run, not only reported once).

## 10. Partial-overlap findings (H3)

**H3 is confirmed on this benchmark.** `partial-overlap-01` constructs
three tied-shortest chains: chain A roots to `{E1, E2}`, chain B roots
to `{E2, E3}`, chain C roots to `{E4}`. Pairwise: (A, B) share E2 — not
disjoint; (A, C) and (B, C) share nothing — disjoint. The correct,
current top-level verdict is `fully_evidence_independent = False`
(not every pair is disjoint) — this is not a bug, it answers exactly
the question it is documented to answer. But that single boolean gives
a reader no way to learn that 2 of the 3 chain pairs (66.7%) are, in
fact, root-evidence-disjoint; a case where all three chains mutually
shared evidence would produce the exact same top-level `False` verdict,
indistinguishable from this one without separately inspecting each
chain's own `root_evidence_ids` (which the existing API does already
expose, per chain — the loss is specifically in the single scalar
verdict, not in the underlying data model; see §14 for what this does
and does not mean for the existing implementation).

## 11. Adversarial byte-distinct limitation

**Fixture:** `byte-distinct-same-source-01`. Two `EvidenceItem`s (E1,
E2) are constructed from two byte-distinct raw payloads — the same
JSON authentication record, one exported with a trailing newline, one
without — so `E1.id != E2.id` (different SHA-256 content hashes).
Witnessgraph's `analyze_paths_evidence_overlap` correctly, mechanically
reports the two chains that separately cite E1 and E2 as
root-evidence-disjoint (`fully_evidence_independent = True`).

This is the exact limitation `docs/research/adversarial-contribution-review.md`
§5/§17 identified without a benchmark: **root-evidence disjointness is
a provenance property computed over exact ingested bytes, not a
guarantee that the underlying real-world observations are
independent.** Per this fixture's own, independently declared ground
truth, E1 and E2 are *not* two independent records of reality — they
are one record, duplicated during evidence handling. Witnessgraph has
no way to detect this, by design (content hashing is exactly what
makes its provenance guarantee cheap, verifiable, and free of any
semantic-equivalence judgment call) — and this benchmark does not ask
it to. The adversarial group's confusion-matrix "accuracy" for this
fixture is 1.0 only because the ground truth's `root_sets_disjoint`
field is itself defined at the same content-hash level Witnessgraph
operates at; that number confirms internal consistency of the
provenance model, not epistemic correctness, and must never be quoted
as if it validated the latter.

## 12. Reproducibility findings (H2)

**H2 is confirmed within a single machine/process for every fixture.**
For all 8 fixtures, two independently constructed `Case` directories
(fresh temp directories, identical `build()` call, no shared state)
produced byte-identical `ProvenanceManifest.manifest_hash` values and
byte-identical canonical JSON for both
`all_shortest_paths_result_to_json` and
`paths_evidence_overlap_to_json`. This directly exercises
Witnessgraph's own determinism machinery
(`core.ids.canonical_json_bytes`, content-derived
`Relationship`/`EvidenceItem` ids) exactly as
`test_export_import_roundtrip.py` and the project's `hypothesis`-based
property tests already do for other object types.

**What this does not establish:** cross-machine, cross-OS, or
cross-Python-minor-version determinism. This benchmark, like the
project's existing CI, runs on one environment
(`ubuntu-latest`/local Windows dev machine, Python 3.11). The
adversarial-contribution-review's §13 Experiment 2 design (an N-case ×
M-environment CI matrix) remains unimplemented; extending WG-Bench's
CI job to a small OS/Python matrix is the natural next step to close
this gap (see §15).

## 13. Threats to validity

- **Synthetic fixture bias.** All 8 fixtures are small (2–3 hop),
  hand-authored graphs designed specifically to isolate one mechanism
  each. Real investigation graphs are larger, messier, and rarely this
  clean — this benchmark says nothing about performance on realistic
  case topologies.
- **Analyst-authored ground truth.** Every `GroundTruth` value was
  written by the same person who read `correlate.graph`'s source code
  in detail while producing `docs/research/adversarial-contribution-review.md`.
  While the ground truth was written before running the implementation
  against each fixture (not copied from its output), deep familiarity
  with the mechanism being tested is a real, unavoidable source of
  potential bias — an independent author unfamiliar with the
  implementation might design different, possibly more adversarial,
  fixtures.
- **Byte-distinct/same-source evidence.** §11's limitation is
  demonstrated with exactly one hand-picked example (a trailing
  newline). Real-world "same source, different bytes" scenarios (log
  rotation, re-export in a different encoding, timezone-normalized
  copies, OCR'd duplicates) vary widely in how *plausible* a false
  "independent" reading would be; this benchmark does not sample that
  space, it only proves the failure mode exists.
- **Semantic equivalence not captured by content hashes** is the
  general form of the above: no content-hashing scheme can, by
  construction, recognize two byte-distinct payloads as the same
  underlying fact without some external semantic-equivalence judgment
  Witnessgraph deliberately does not attempt (see `SECURITY.md`/`DESIGN.md`
  principle 6's no-inference stance).
- **Small benchmark size.** 8 fixtures, one per taxonomy class, is
  enough to demonstrate that each documented behavior exists and to
  pin it against regression, but far too small to estimate a reliable
  false-corroboration *rate* for real casework — the reported rates
  (100% baseline FPR, 0% Witnessgraph FPR) describe this exact fixture
  set, not a general-purpose performance guarantee.
- **Path-selection assumptions.** All fixtures use `find_all_shortest_paths`'s
  default `max_depth`/`limit`; behavior at `--limit`-truncated results
  (`truncated = True`) is untested here — `analyze_paths_evidence_overlap`'s
  own documentation already states its verdict describes only the
  chains actually returned, and this benchmark does not independently
  verify that boundary.
- **Boolean/null result limitations.** §10's finding is about the
  single scalar `fully_evidence_independent` field specifically. The
  underlying `PathsEvidenceOverlap.chains` array *does* carry each
  chain's own `root_evidence_ids`, so a consumer willing to compute
  pairwise overlap themselves is not structurally blocked from
  recovering the partial structure — the limitation is that the
  analysis does not compute or expose that pairwise/graded verdict
  itself, not that the information is unrecoverable from the existing
  API.
- **Dependence on Witnessgraph's existing provenance model.** Every
  metric in this benchmark is defined relative to Witnessgraph's own
  notion of root evidence (resolved via `derived_from` down to a root
  `EvidenceItem` id). If that model is wrong or incomplete in some way
  this benchmark's fixtures do not probe, WG-Bench would not detect it
  — it evaluates internal consistency and documented behavior, not the
  model's fitness against ground truth external to Witnessgraph's own
  definitions (this is exactly what §11's adversarial fixture is
  designed to make visible, rather than paper over).
- **Baseline design is circular within the binary group.** Every
  binary-group fixture was deliberately constructed to have path
  multiplicity (that is what makes the independence question
  "binary-applicable" at all), so the path-count-only baseline is
  mechanically "always predicts multiple_paths ⇒ implied independence"
  for all 5 of them by the way the benchmark itself is built — its
  100% false-positive rate on the 3 truly-non-independent fixtures
  should be read as "path count carries zero discriminating signal
  between independent and non-independent multi-path cases" (a real,
  precise, and defensible finding), not as "the baseline is empirically
  wrong 100% of the time on graphs in general."

## 14. What this experiment does NOT establish

- It does not establish that Witnessgraph's root-evidence
  independence check detects source collusion, evidence fabrication,
  re-encoded duplicate sources, or anything about physical or
  institutional independence of the underlying observations (§11).
- It does not establish an "epistemic independence accuracy" — no such
  metric was computed, and none should be inferred from any number in
  §9. Root-evidence disjointness is a provenance property; this
  document reports how well Witnessgraph computes *that* property
  correctly and consistently, never whether that property implies
  real-world evidentiary independence.
- It does not establish that path-count-only reasoning is a realistic
  model of how any actual analyst reads Witnessgraph's output — the
  baseline is a deliberately simple, worst-case stand-in for
  "corroboration read from multiplicity alone with no
  provenance/`--explain` information available," not a claim about
  human behavior (no user study was run).
- It does not establish cross-machine/cross-OS determinism (§12).
- It does not establish anything about performance on realistic,
  larger, or `--limit`-truncated investigation graphs (§13).
- It does not establish that the current boolean/null representation
  is a defect requiring a code change — H3's confirmation is a
  precisely scoped information-loss finding about one field, not a bug
  report; §19 explicitly recommends no engine change on this basis.

**Root-evidence disjointness is a provenance property, not a guarantee
that the underlying observations are epistemically independent.**

## 15. Recommended next research milestone

Extend WG-Bench's determinism check (§12) to a small CI matrix (at
least two OS/Python-minor-version combinations), directly closing the
gap this document's own §12/§13 identify — the cheapest, most
decision-relevant follow-up, since it requires no new fixtures, no new
metrics, and no production-code change, only a CI configuration change
plus reusing the exact `deterministic_replay_ok` check WG-Bench already
computes per fixture. A secondary, larger follow-up is broadening the
fixture set with graphs sized and shaped closer to `examples/sample-case`
(addressing §13's synthetic-fixture-bias and small-benchmark-size
threats) before treating any specific false-corroboration rate reported
here as representative of realistic casework.

**V1's §15 recommendation above was superseded by V2 before either
follow-up was implemented — see the V2 section below.** V2 addresses a
more consequential methodological gap in V1 (the baseline's circularity)
first; the CI-matrix and larger-fixture-set follow-ups remain open, see
V2 §36.

---

# WG-Bench V2: Testing the Baseline, Not Just the System

Status: completed. Extends V1 above (unchanged, still fully valid as the
historical initial benchmark) with two additional non-recursive
baselines and 7 new fixtures. No Witnessgraph production code
(`src/witnessgraph/{core,correlate,ingest,api,cli,replay,report,service,store}`)
or frontend code was modified to build or run V2. See
`research/wg_bench/v2/` for the implementation and
`tests/unit/test_wg_bench_v2.py` for its test suite. `research/wg_bench/`
(V1, including all 8 of its fixtures) is unchanged and still runs and
passes independently.

Reproduce V2's results in this document from the repository root:

```sh
python -m research.wg_bench.v2
```

## 26. V1's methodological limitation

V1 (sections 1-15 above) reported that Witnessgraph's recursive
root-evidence overlap analysis achieved a 0% false-corroboration rate
against a path-count-only baseline that scored 100%. V1's own section 13
already flagged why that comparison is weaker evidence than it first
appears: **every binary-group fixture in V1 was deliberately constructed
to have path multiplicity** (2+ shortest chains) -- that is what makes
the independence question "binary-applicable" to that fixture at all.
Given that construction, `classify_by_path_count`'s rule (>=2 paths =>
"multiple_paths" => implied independence) mechanically predicts
"independent" for every one of them, regardless of whether they actually
are. The baseline's 100% false-positive rate on the 3 truly-non-independent
V1 fixtures is therefore not an empirical finding about how bad
path-count reasoning is in general -- it is close to a restatement of how
the benchmark itself was built. **That result must remain documented as
a simple-control result** (a real, valid demonstration that path count
alone carries literally zero discriminating signal), but it must not be
read as strong evidence that Witnessgraph outperforms a *realistic,
provenance-aware* competitor -- V1 never tested one.

## 27. V2 research question

**Does Witnessgraph's recursive root-evidence analysis provide
information that is not trivially recoverable from path structure or
direct evidence references?**

V2 answers this by inserting two new methods between V1's baseline and
Witnessgraph, forming a four-rung ladder each fixture is evaluated
against identically:

- **Baseline 0** -- path-count-only (V1, unchanged, `research.wg_bench.baseline`).
- **Baseline 1** -- path-structure reasoning (`research.wg_bench.v2.baseline1`).
- **Baseline 2** -- direct evidence-reference comparison (`research.wg_bench.v2.baseline2`).
- **System under test** -- Witnessgraph's actual `find_all_shortest_paths`/`analyze_paths_evidence_overlap`.

## 28. Baseline hierarchy -- exact definitions

All four methods share the same `find_all_shortest_paths` result (the
structural path-finding step is common infrastructure every method uses,
never itself part of the comparison); only Witnessgraph additionally
calls `analyze_paths_evidence_overlap`.

**Baseline 0** (unchanged from V1, section 6): buckets the returned
chain *count* into `no_or_single_path` / `multiple_paths`. Never inspects
any field of an individual chain.

**Baseline 1** (`research.wg_bench.v2.baseline1.classify_by_structure`):
inspects each returned chain's own `TraversalStep`s -- specifically
`relationship.id` and `relationship.source_entity_id`/`target_entity_id`
-- and classifies a set of chains as `structurally_disjoint` only if no
pair shares any non-endpoint entity id or any relationship id, else
`structurally_overlapping`. **Deliberately never inspects
`Relationship.derived_from` at all**, even though V2's mission statement
permits it to -- this is a considered implementation choice, not an
oversight: it isolates one specific question ("does structural path
information alone -- what an analyst sees just by counting/skimming
distinct chains, with zero provenance lookup -- already carry
evidence-discriminating signal?") from the separate question Baseline 2
asks. Never calls `analyze_paths_evidence_overlap`, never resolves a
`NormalizedEvent`.

**Baseline 2** (`research.wg_bench.v2.baseline2.classify_by_direct_references`):
for each returned chain, builds the set of every relationship's raw,
*unresolved* `derived_from` ids across the chain (the "direct reference
set") -- these ids may name an `EvidenceItem` directly or a
`NormalizedEvent` (Baseline 2 cannot tell which, and does not try).
Classifies a set of chains as `directly_disjoint` only if every pair's
direct reference sets are disjoint, else `directly_overlapping`. Never
follows a `NormalizedEvent`'s own `derived_from` (no recursion past one,
un-followed hop) and never calls `analyze_paths_evidence_overlap`. This
is WG-Bench V2's realistic stand-in for "an analyst who reads each
relationship's own `derived_from` field and compares ids directly,
without chasing multi-level lineage" -- the strongest baseline that
still stops short of Witnessgraph's actual recursion.

**System under test**: `witnessgraph.correlate.graph.find_all_shortest_paths`
then `analyze_paths_evidence_overlap`, called through their ordinary,
unmodified public API -- identical to V1 section 7. `_resolve_root_evidence_ids`
follows a `derived_from` id through at most one `NormalizedEvent`
indirection down to root `EvidenceItem` id(s) (see section 29 on why "one
level" is the actual ceiling the current core model supports, not an
arbitrary choice by this benchmark).

Every method's binary "does this imply the connection is independently
corroborated" prediction is scored against the exact same target
question -- the fixture's ground-truth `root_sets_disjoint` (are all
pairs of the fixture's *intended* chains' root evidence sets disjoint) --
which is what makes all four methods' results directly, fairly
comparable (`research.wg_bench.v2.evaluation.FixtureEvaluationV2.predicted_independent`,
scored identically in `research.wg_bench.v2.metrics._confusion_matrix`
for every method).

## 29. Baseline fairness

Per the mission's fairness rule, the stronger baselines receive
information a competent analyst could reasonably obtain from the same
case representation, without secretly invoking Witnessgraph's own
recursive resolver. Baseline 2 is deliberately the *strongest* baseline
that still stops one hop short of full recursion -- it inspects every
relationship's own `derived_from` id, exactly as `--explain` output
already surfaces it, but does not chase that id's own referent's lineage.

One data-model fact shaped fixture design and is disclosed here rather
than left implicit: `core.events.NormalizedEvent` documents that an
`EvidenceItem` never itself has a `derived_from` -- it is always the
root. The current ingest pipeline and core model therefore support
**at most one level** of indirection
(`Relationship -> NormalizedEvent -> EvidenceItem`), never
`NormalizedEvent -> NormalizedEvent -> ... -> EvidenceItem`. V2's
"multi-level lineage" fixture (section 30.C) tests recursive resolution
across every hop of a multi-hop chain, not N>1 levels of event-to-event
chaining, because the latter does not exist anywhere in the current
model for this benchmark to exercise. This is a genuine, disclosed
boundary of what this benchmark can test, not a benchmark design choice
made for convenience -- see section 41.

## 30. Fixture taxonomy

15 fixtures total: the 8 retained V1 fixture classes (unchanged,
adapted into V2's four-method evaluation via
`research.wg_bench.v2.fixtures.v1_adapter` -- their `build()` functions
and ground truth are called and read verbatim, never rewritten) plus 7
new V2-only fixtures.

| Class | Fixture id | Paths | New in V2? |
| --- | --- | --- | --- |
| `SINGLE_PATH` | `single-path-01` | 1 | No (V1) |
| `SHARED_ROOT` | `shared-root-01` | 2 | No (V1) |
| `DISJOINT_ROOTS` | `disjoint-roots-01` | 2 | No (V1) |
| `IDENTICAL_ROOT_SETS` | `identical-root-sets-01` | 3 | No (V1) |
| `PARTIAL_OVERLAP` | `partial-overlap-01` | 3 | No (V1) |
| `BYTE_DISTINCT_SAME_SOURCE` | `byte-distinct-same-source-01` | 2 | No (V1) |
| `PATH_COUNT_DECEPTION` | `path-count-deception-01` | 8 | No (V1) |
| `DISJOINT_MULTI_EVIDENCE` | `disjoint-multi-evidence-01` | 2 | No (V1) |
| `DIRECT_DIFFERENT_SHARED_ROOT` | `direct-different-shared-root-01` | 2 | **Yes** |
| `DIRECT_SAME_ROOT_DISJOINT` | `direct-same-root-disjoint-01` | 2 | **Yes** |
| `MULTI_LEVEL_LINEAGE` | `multi-level-lineage-01` | 2 | **Yes** |
| `MIXED_DIRECT_DERIVED` | `mixed-direct-derived-01` | 2 | **Yes** |
| `HIGH_PATH_SHARED_ROOT` | `high-path-shared-root-01` | 6 | **Yes** |
| `HIGH_PATH_DISJOINT_ROOT` | `high-path-disjoint-root-01` | 6 | **Yes** |
| `PARTIAL_MULTI_ROOT` | `partial-multi-root-01` | 4 | **Yes** |

**Important V1-fixture finding, disclosed up front:** every V1 fixture
was built exclusively with `research.wg_bench.graph_builder.FixtureGraphBuilder`,
which cites `EvidenceItem`s directly -- there is no `NormalizedEvent`
indirection anywhere in a V1 fixture. That means, for every one of the 8
retained V1 fixtures, the *direct* reference set and the *root* evidence
set are identical by construction, so **Baseline 2 cannot be
distinguished from Witnessgraph on any V1 fixture**
(`tests/unit/test_wg_bench_v2.py::test_v1_fixtures_have_identical_direct_and_root_sets`
enforces this as a regression check). This is itself an important,
honestly-reported V2 result: V1's fixture set, by never exercising
multi-level lineage, was structurally incapable of ever distinguishing
"has provenance information" from "recursively resolves provenance
information" -- exactly the ambiguity V2 exists to correct. All 7 new
fixtures below specifically target that gap.

### New V2 fixtures

**A. `DIRECT_DIFFERENT_SHARED_ROOT`** (`direct-different-shared-root-01`).
Two chains cite two *different*, distinctly-identified `NormalizedEvent`s
(`Ev1`, `Ev2` -- different `event_type`/`attributes`, hence different
content-derived ids), both of which `derived_from` the *same* root `E1`.
Direct sets `{Ev1}`/`{Ev2}` are disjoint; root sets `{E1}`/`{E1}` are
not. **Result: Baseline 2 is fooled (predicts independent, false
corroboration); Witnessgraph correctly resolves the shared root.** This
is V2's central, minimal discriminating case.

**B. `DIRECT_SAME_ROOT_DISJOINT`** (`direct-same-root-disjoint-01`).
Two chains cite events with the *same* `event_type`/`attributes`
(`host="shared-gateway"`) -- a surface-level resemblance a human analyst
skimming event summaries might read as "the same kind of record" -- but
different `derived_from` (hence different content-derived ids), and
correctly resolve to disjoint roots (`E1` vs. `E2`). **Result: this
fixture is an honest negative finding.** Every method in this benchmark
compares *ids*, never `event_type`/`attributes` content, so none is
fooled by the surface resemblance -- Baseline 2 and Witnessgraph agree
(both correctly report disjoint). It documents that Baseline 2's
disadvantage relative to Witnessgraph (fixture A above) is specifically
about following `derived_from` indirection to detect a *shared* root,
not about resisting attribute-level distraction, which id-based
comparison already handles for free. Retained as a documented robustness
check, not silently dropped for producing a null result.

**C. `MULTI_LEVEL_LINEAGE`** (`multi-level-lineage-01`). Every one of 4
hops (2 per chain) cites its own distinct `NormalizedEvent`, all four
`derived_from` the single root `E1` -- stresses aggregation across a
whole multi-hop chain, not just one hop (unlike fixture A). Direct sets
`{EvB1,EvB2}`/`{EvC1,EvC2}` are fully disjoint (4 pairwise-distinct
event ids); root sets are both `{E1}`. **Result: Baseline 2 is fooled;
Witnessgraph correctly aggregates each chain's per-hop resolved roots
(a union across steps, per `analyze_paths_evidence_overlap`'s existing
documented behavior) and reports not independent.**

**D. `MIXED_DIRECT_DERIVED`** (`mixed-direct-derived-01`). One chain
cites its root `EvidenceItem` `E1` directly; the other cites a
`NormalizedEvent` `Ev1` that itself `derived_from` `E1` -- same eventual
root, different provenance depth. Direct sets `{E1}`/`{Ev1}` are
disjoint (an `EvidenceItem` id and a `NormalizedEvent` id are never
equal, even when they concern the same underlying record); root sets are
both `{E1}`. **Result: Baseline 2 is fooled; Witnessgraph correctly
normalizes provenance depth.** Tests exactly the "normalization" question
the mission's design specified.

**E. `HIGH_PATH_SHARED_ROOT`** (`high-path-shared-root-01`). Scaled
version of A: 6 chains, each with its own distinct direct reference, all
6 resolving to the one root `E1`. **Result: Baseline 2 is still fooled at
scale** -- the false-corroboration failure mode does not vanish, and if
anything looks more convincing, as chain count grows (the same scaling
argument V1's `PATH_COUNT_DECEPTION` made against Baseline 0 applies
equally to Baseline 2 here).

**F. `HIGH_PATH_DISJOINT_ROOT`** (`high-path-disjoint-root-01`). The
scalable positive/true case: 6 chains, each grounded in its own genuinely
distinct root `EvidenceItem`, no sharing anywhere. **Result: every
method (Baseline 0/1/2, Witnessgraph) correctly agrees these 6 chains are
independently corroborating.** Confirms Baseline 2 and Witnessgraph are
not "always pessimistic" -- both scale correctly on true positives too.

**G. `PARTIAL_MULTI_ROOT`** (`partial-multi-root-01`). A richer,
4-chain version of V1's `PARTIAL_OVERLAP` (3 chains): chain roots
`{E1,E2}`, `{E2,E3}`, `{E3,E4}`, `{E5}`. Of 6 pairwise chain
relationships, 2 overlap (A-B share `E2`; B-C share `E3`) and 4 are
genuinely disjoint (A-C, A-D, B-D, C-D). Direct references are identical
to root evidence here (no `NormalizedEvent` indirection) -- this fixture
is deliberately isolated to the H3 information-loss question (section
37), not conflated with the Baseline-2-vs-Witnessgraph story fixtures A-F
already cover.

## 31. Ground-truth methodology

Identical discipline to V1 section 5: every `GroundTruthV2` value
(`research.wg_bench.v2.model.GroundTruthV2`) is hand-authored by
reasoning about a fixture's intended topology *before* the runner is
invoked against it, kept in a dataclass physically separate from what
the runner observes (`FixtureEvaluationV2`,
`research.wg_bench.v2.evaluation`). V2 additionally distinguishes, per
the mission's item 7 requirement, the following properties, never
collapsed into one field:

- **A. Structural path multiplicity** -- the raw shortest-chain count
  (`expected_shortest_path_count`), independent of any evidence
  question.
- **B. Direct evidence overlap** -- `ExpectedChainV2.direct_reference_labels`
  and `GroundTruthV2.direct_sets_disjoint`: whether the *raw, unresolved*
  ids chains cite are pairwise disjoint.
- **C. Root-evidence overlap** -- `ExpectedChainV2.root_evidence_labels`
  and `GroundTruthV2.root_sets_disjoint`: V1's existing concept, what
  those ids resolve to.
- **D. Conceptual/source identity** -- `GroundTruthV2.conceptual_source_groups`:
  independently declared benchmark metadata *only* (never derived from
  any method's output, never fed back into any classification), used
  exactly once, for `BYTE_DISTINCT_SAME_SOURCE` (section 16/40 below),
  where it records that both chains are judged, by the fixture's author,
  to represent one real-world source record despite disjoint root
  evidence ids. This metadata never becomes, and must never become, a
  production inference -- Witnessgraph has no code path that reads it,
  and none is proposed.

`tests/unit/test_wg_bench_v2.py::test_fixture_build_matches_its_own_ground_truth`
independently confirms every fixture's `build()` produces the graph its
ground truth describes (path count, direct sets, *and* root sets), and
`test_v1_fixtures_have_identical_direct_and_root_sets` independently
confirms the V1-fixture finding in section 30 above.

## 32. Evaluation methodology

`research.wg_bench.v2.evaluation.evaluate_fixture` builds each fixture
twice, independently, into fresh `Case` directories, runs
`find_all_shortest_paths` once per build, then derives all four methods'
classifications from that single shared result (Baseline 0/1/2 from the
returned chains directly; Witnessgraph from `analyze_paths_evidence_overlap`
called on the same result). Every method's binary prediction is compared
against the same `root_sets_disjoint` ground truth (section 28).
Determinism (H2) is checked exactly as V1 did, extended to also require
the new direct-reference multiset (`direct_sets`) to match byte-for-byte
across the two independent builds, not only `root_sets`/manifest/
canonical JSON.

## 33. Metrics -- exact definitions

Identical four-group discipline to V1 section 8 (binary / single_path /
partial_overlap / adversarial, never pooled), computed identically for
all four methods via `research.wg_bench.v2.metrics`.

**Group A -- binary provenance cases** (11 of 15 fixtures: everything
except `single-path-01`, the 2 partial-overlap-class fixtures, and the
1 adversarial fixture). Per method: `TP`/`FP`/`FN`/`TN`, accuracy,
precision, recall, false-positive rate -- identical formulas to V1
section 8.

**Group B -- partial overlap** (2 fixtures: `partial-overlap-01`,
`partial-multi-root-01`). Per fixture: total chain pairs, root-disjoint
pairs, root-boolean verdict, root pairs masked by the boolean,
**information-loss rate** (`root_pairs_masked_by_boolean / total_chain_pairs`,
new in V2 -- V1 reported the masked count but not its rate), plus the
same accounting computed a second time over *direct* reference sets
(`direct_disjoint_pairs`, `direct_boolean_verdict`,
`direct_pairs_masked_by_boolean`) so a reader can see whether Baseline
2's own boolean loses pairwise information the same way Witnessgraph's
does (see section 37).

**Group C -- adversarial** (1 fixture: `byte-distinct-same-source-01`,
unchanged from V1). Reported separately from ordinary binary failures,
exactly as V1 section 8/11 insist -- the production system never claims
to solve conceptual-source identity, so this group's "accuracy" is
internal-consistency-with-content-hash-model only, never epistemic
correctness (section 40).

**Group D -- determinism.** `deterministic_replay_success_count`/`_total`/`_rate`
per group, plus `all_deterministic_replay_ok` overall -- same H2 check as
V1 section 12, now also covering direct-reference-set equality.

## 34. Complete results

Reproduced from `python -m research.wg_bench.v2` at the HEAD this
section was committed against; also independently pinned by
`tests/unit/test_wg_bench_v2.py`'s exact-count assertions (never an
approximate/blended score).

**Group A -- binary-classification (n=11):**

| Method | TP | FP | FN | TN | Accuracy | Precision | Recall | False-positive rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline 0 (path-count-only) | 4 | 7 | 0 | 0 | 0.364 | 0.364 | 1.00 | **1.00** |
| Baseline 1 (path-structure) | 4 | 7 | 0 | 0 | 0.364 | 0.364 | 1.00 | **1.00** |
| Baseline 2 (direct evidence-reference) | 4 | 4 | 0 | 3 | 0.636 | 0.50 | 1.00 | **0.571** |
| Witnessgraph (recursive root-evidence) | 4 | 0 | 0 | 7 | **1.00** | 1.00 | 1.00 | **0.00** |

Baseline 1's confusion matrix is bit-for-bit identical to Baseline 0's
on every one of the 11 binary fixtures
(`tests/unit/test_wg_bench_v2.py::test_binary_group_baseline0_and_baseline1_are_identical`)
-- structural (entity/relationship-id) inspection, with no evidence
reasoning at all, carries exactly zero additional discriminating signal
beyond raw path count on this fixture set. This is itself an answer to
section 27's research question's first half: no, ordinary structural
path inspection does not reveal the relevant distinction.

Baseline 2 correctly resolves the 3 V1-inherited binary fixtures where
sharing is directly, not derivedly, cited (`shared-root-01`,
`identical-root-sets-01`, `path-count-deception-01` -- all 3 contribute
to its `TN=3`), and correctly identifies all 4 genuinely disjoint
fixtures (`TP=4`, `FN=0` -- it never wrongly claims sharing that isn't
there). But it is fooled (`FP=4`) on exactly the 4 new fixtures
specifically engineered to require following `derived_from` past one
level of indirection: `direct-different-shared-root-01`,
`multi-level-lineage-01`, `mixed-direct-derived-01`, and
`high-path-shared-root-01`. Witnessgraph resolves all 4 correctly.

**Group B -- single-path (n=1):** `single-path-01`, no multiplicity, all
four methods report `not_applicable`/`None` -- a well-formed inapplicable
result, not a data point in any false-corroboration count.

**Group C -- partial-overlap (n=2):**

| Method | TP | FP | FN | TN | Accuracy | False-positive rate |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline 0 / Baseline 1 | 0 | 2 | 0 | 0 | 0.00 | **1.00** |
| Baseline 2 / Witnessgraph | 0 | 0 | 0 | 2 | **1.00** | **0.00** |

Both partial-overlap fixtures have ground-truth `root_sets_disjoint =
False` (not *every* pair is disjoint), so Baseline 0/1's "any
multiplicity implies independence" rule is wrong on both; Baseline 2 and
Witnessgraph both correctly report `False` (not fully independent) --
this pair happens not to distinguish Baseline 2 from Witnessgraph,
because the `PARTIAL_MULTI_ROOT` fixture (unlike fixtures A-F above) was
deliberately built with no `NormalizedEvent` indirection, to isolate the
information-loss question below from the recursion question above
(section 30).

Pairwise information-loss findings (`PartialOverlapFindingV2`):

| Fixture | Total pairs | Root-disjoint pairs | Root boolean | Masked pairs | Information-loss rate |
| --- | --- | --- | --- | --- | --- |
| `partial-overlap-01` (V1) | 3 | 2 | `False` | 2 | **66.7%** |
| `partial-multi-root-01` (V2) | 6 | 4 | `False` | 4 | **66.7%** |

Both fixtures independently converge on the same ~67% information-loss
rate despite different chain counts/topologies -- see section 37 (H3).
`direct_disjoint_pairs`/`direct_boolean_verdict` for both fixtures are
identical to the root-based numbers (no indirection in this fixture
class), so Baseline 2's own single boolean loses exactly the same
pairwise information Witnessgraph's does, on these two fixtures.

**Group D -- adversarial (n=1):** `byte-distinct-same-source-01`, all
four methods agree (`TP=1`, ground truth `root_sets_disjoint=True`) --
trivially "correct" at the provenance level by construction (section
16/40), never read as validating anything about real-world/epistemic
independence.

**Determinism:** 15/15 fixtures (100%) produced byte-identical manifest
hashes, byte-identical canonical analysis JSON, and byte-identical
direct/root reference multisets across two independent builds
(`tests/unit/test_wg_bench_v2.py::test_fixture_is_deterministic_across_independent_builds`,
enforced on every CI run). Additionally verified at the whole-run level:
two independent, separate invocations of `python -m research.wg_bench.v2
--out-dir <dir>` from the same repository state produced byte-identical
`results.json` and `results.txt`.

## 35. H1 result

**H1** ("root-evidence overlap analysis reduces false-corroboration
classifications relative to path-count-only reasoning on a ground-truth
benchmark") **remains supported**, and V2's larger fixture set (15 vs.
8) and the 3 additional true-positive/true-negative fixtures make it a
somewhat broader demonstration than V1's -- but section 26 still
applies: Baseline 0's circularity (every binary fixture has path
multiplicity by construction) means this specific comparison is weak
evidence on its own. Section 36 (H1b) is the result that actually
matters.

## 36. H1b result

**H1b** ("recursive root-evidence resolution provides measurable
classification information beyond direct evidence-reference comparison")
**is confirmed, with an exact, fixture-level accounting of where.**
Witnessgraph's binary-group false-positive rate (0.00) is strictly lower
than Baseline 2's (0.571) -- not a tie, and not explainable by Baseline
2 being under-resourced: Baseline 2 correctly handles every V1-inherited
fixture and correctly identifies every genuinely-disjoint case in this
benchmark (`FN=0` for both). The entire gap is concentrated in exactly
the 4 fixtures engineered to require following `derived_from` past a
`NormalizedEvent`: `direct-different-shared-root-01`,
`multi-level-lineage-01`, `mixed-direct-derived-01`,
`high-path-shared-root-01` -- and nowhere else. **This is the answer to
section 27's research question's second half: yes, Witnessgraph's
recursive resolution provides information Baseline 2 cannot recover,
specifically and only when a chain's evidence citation requires
resolving through a `NormalizedEvent` rather than naming a root
`EvidenceItem` directly.**

## 37. H3 result

**H3** ("the current Boolean/null evidence-independence representation
loses information in partial-overlap cases"), retested with two
independent fixtures instead of V1's one: **confirmed at both scales,
quantified.** `partial-overlap-01` (3 chains, V1) masks 2/3 = 66.7% of
pairwise relationships; `partial-multi-root-01` (4 chains, V2, a
different overlap topology -- a 3-chain overlap "run" plus one fully
separate chain, rather than V1's simpler star) independently masks 4/6 =
66.7% as well. The two fixtures were designed with different topologies
specifically to check whether V1's 66.7% was a coincidence of its
particular 3-chain construction; it was not -- the loss rate is a
property of "how many pairs the single top-level boolean's `False` as
soon as *any* pair overlaps" rule discards, not an artifact of one
fixture's shape. `information_loss_rate` (new in V2, section 33) makes
this an exact, reusable, regression-testable number rather than a
one-off observation
(`test_partial_multi_root_masks_four_of_six_disjoint_pairs` pins it).

## 38. Recursive root-evidence value assessment

Directly answering the mission's central question: **the research gap
survives the stronger baseline.** Witnessgraph strictly outperforms
Baseline 2 (0.00 vs. 0.571 false-positive rate on the binary group), and
the gap is not diffuse -- it is exactly, and only, the 4 fixtures
requiring resolution through a `NormalizedEvent`. Baseline 2 is not a
strawman: it correctly solves every V1-inherited fixture and every
genuinely-independent fixture in this benchmark, including at 6x scale
(`high-path-disjoint-root-01`). Its failure is precise and mechanistic,
not incidental: any time a relationship's `derived_from` names a
`NormalizedEvent` rather than an `EvidenceItem` directly, Baseline 2
cannot see past that one id to whether two such events happen to share a
root.

## 39. Partial-overlap findings

See sections 34/37. The Boolean/null representation's information loss
is real, quantified at ~67% in both fixtures tested, and -- per V1
section 13's original caveat, still true in V2 -- the underlying
`PathsEvidenceOverlap.chains` array already carries each chain's own
`root_evidence_ids`, so a consumer willing to compute pairwise overlap
themselves (exactly what `research.wg_bench.v2.metrics._partial_overlap_findings`
does) is not structurally blocked from recovering the full pairwise
structure; the loss is specifically in the single top-level scalar
verdict, not an unrecoverable loss of the underlying data.

## 40. Byte-distinct same-source findings

Unchanged from V1 section 11, now also carrying explicit
`conceptual_source_groups` benchmark metadata (`{"via B", "via C"}` for
`byte-distinct-same-source-01`,
`test_byte_distinct_same_source_records_conceptual_source_group` in V2's
test suite). All four methods agree the two chains are
root-evidence-independent (`TP=1`), correctly per Witnessgraph's own
content-hash provenance model -- and, per this fixture's independently-
declared ground truth, incorrectly at the level of real-world source
identity. Root-evidence disjointness remains, in V2 as in V1, a
provenance property, never a guarantee of epistemic independence -- and
no method in this benchmark, including the two new baselines, claims
otherwise or could detect this case, because none of them (nor
Witnessgraph) inspect anything but content-addressed ids.

## 41. Threats to validity (V2-specific, in addition to V1 section 13)

- **Only one level of indirection is representable.** Section 29
  disclosed this: the current core model supports at most
  `Relationship -> NormalizedEvent -> EvidenceItem`, never deeper event
  chaining. If a future ingest adapter introduced multi-level
  `NormalizedEvent` chaining, this benchmark's `MULTI_LEVEL_LINEAGE`
  fixture would not exercise it, and H1b's result would need
  re-verification at that depth.
- **Baseline 1's null result is itself fixture-set-dependent.** Every
  fixture in this benchmark (V1 and V2) was built with structurally
  distinct intermediate entities per chain by design (a diamond or
  fan-out topology) -- Baseline 1 ties Baseline 0 exactly *because* no
  fixture ever reuses an intermediate entity or relationship id across
  chains. A case graph where two structurally-distinct chains happen to
  revisit a shared intermediate entity (without sharing evidence) is not
  represented here, and could in principle give Baseline 1 a signal V1's
  and V2's fixtures never test.
- **Only 4 fixtures separate Baseline 2 from Witnessgraph.** All 4 are
  hand-authored, by the same analyst, using two closely related
  constructions (a shared root reached via different events, or via
  different provenance depths). An independent fixture author might
  design additional discriminating cases this benchmark does not cover,
  or might find the 4 existing ones less representative of real ingest
  pipelines' actual `derived_from` patterns than intended.
- **Scale fixtures (E/F) only go to 6 chains.** `HIGH_PATH_SHARED_ROOT`/
  `HIGH_PATH_DISJOINT_ROOT` demonstrate the failure/success modes persist
  at 6x, not at realistic case-graph scale (tens to hundreds of chains) --
  see V1 section 13's synthetic-fixture-bias/small-benchmark-size
  threats, which apply here unchanged.
- V1 section 13's other threats (analyst-authored ground truth,
  byte-distinct sampling, semantic equivalence, path-selection/`--limit`
  assumptions, and dependence on Witnessgraph's own provenance model
  definition) all apply identically to V2's fixture set and are not
  repeated here.

## 42. Does the research gap survive the stronger baseline?

**Yes.** This is V2's headline finding, stated directly per the
mission's instruction to report this honestly either way: Baseline 2 --
the strongest non-recursive, direct-evidence-reference baseline this
benchmark could construct while staying strictly within the fairness
rule (section 29) -- ties Witnessgraph on 7 of 11 binary fixtures
(including every fixture where sharing is cited directly) but is
measurably, precisely worse on the 4 fixtures requiring
`NormalizedEvent` resolution. The research gap did not disappear under
the stronger baseline; it narrowed and became exactly localized to one
specific, nameable mechanism (multi-level `derived_from` resolution)
rather than resting on the whole-baseline circularity V1's comparison
alone could not rule out.

## 43. What this experiment does NOT establish

All of V1 section 14's items still apply unchanged (no epistemic-
independence claim, no source-collusion/fabrication detection claim, no
claim about real analyst behavior, no cross-OS determinism claim, no
realistic-scale claim, no claim that the Boolean representation is a
defect requiring a code change). V2 additionally does not establish:

- That Baseline 2, as implemented here, is the *only* possible strong
  non-recursive baseline, or the strongest one a different author might
  design -- see section 41.
- That the 4-fixture gap (section 36/42) generalizes in magnitude (as
  opposed to in kind) to real investigation graphs; this benchmark
  demonstrates the mechanism exists and is reproducible, not its
  real-world frequency.
- Anything about indirection depths beyond one `NormalizedEvent` hop,
  which the current core model does not support constructing (section
  29/41).
- That Baseline 1's null result generalizes beyond fixtures built with
  structurally distinct intermediate entities per chain (section 41).

## 44. Research interpretation

**Is Witnessgraph's current evidence-overlap mechanism itself
research-interesting, or is it primarily a disciplined implementation of
ordinary provenance reasoning?**

**B. MODERATE SIGNAL.** Recursive root resolution measurably outperforms
the strongest realistic non-recursive baseline this benchmark could
construct (sections 36/38/42) -- the gap is real, precise, and
reproducible, not zero. But it is also narrow and mechanistic: it is
confined to exactly one specific step (following `derived_from` through
a `NormalizedEvent` rather than stopping at the first id), not a broad,
qualitatively different capability. An analyst willing to manually
follow one level of indirection by hand, for every relationship, on
every chain, could in principle reproduce Witnessgraph's results on this
benchmark's fixtures -- what Witnessgraph actually contributes is doing
that mechanically, deterministically, and reproducibly (H2, section 34),
at scale (section 30.E), without an analyst needing to remember to do
it, rather than a fundamentally different reasoning capability a
direct-reference baseline could not approximate even in principle. **The
recommended framing going forward is inspectability/reproducibility/
automation of a mechanism a careful analyst could reconstruct by hand,
not algorithmic novelty** -- this is not a case for abandoning the
provenance-reasoning direction (moderate signal, not weak), but it is
also not a case for overclaiming a fundamentally novel algorithmic
contribution (not strong signal). Do not manufacture a claim beyond what
section 36's precise, 4-fixture-localized gap actually supports.

## 45. Recommended next research milestone

Two candidates, in priority order:

1. **Broaden Baseline 2 itself, adversarially, before broadening
   Witnessgraph's claims.** Since section 41 identifies that only 4
   hand-authored fixtures separate Baseline 2 from Witnessgraph, and
   that an independent fixture author might find different or additional
   discriminating cases, the highest-value next step is having someone
   other than this benchmark's author attempt to design fixtures where
   Baseline 2 (or an even stronger non-recursive baseline) matches
   Witnessgraph more broadly -- directly testing whether section 44's
   "MODERATE SIGNAL" verdict is itself robust, before any further
   benchmark work assumes it.
2. **V1 section 15's original recommendation remains valid and is now
   second priority:** extend the determinism check to a small CI
   OS/Python matrix, and broaden the fixture set toward
   `examples/sample-case`-scale topologies (addressing section 41's
   "only 6 chains" and "hand-authored by one analyst" threats
   simultaneously) -- both apply to V1's and V2's fixtures equally and
   remain unimplemented.

Do not extend V2's specific 4-fixture gap into a broader claim about
Witnessgraph's overall research novelty (section 44) without first
attempting milestone 1 above.

# WG-Bench V3: Independent-Adversarial Validation

V3 is exactly the milestone section 45 above recommended: an
independently-designed attempt to break V2's result, not to extend it.
Reproduce with `python -m research.wg_bench.v3`; implementation in
`research/wg_bench/v3/`, tests in `tests/unit/test_wg_bench_v3.py`. No
Witnessgraph production code (`src/witnessgraph/`, `frontend/`) was
modified to build or run V3 -- see section 62.

## 46. V2's limitation

V2 found that Witnessgraph's recursive root-evidence resolution beats
Baseline 2 (direct evidence-reference comparison, no recursion) on
exactly 4 fixtures (section 34), all requiring one `NormalizedEvent`
indirection hop, and section 45 named the obvious weakness: all 4 were
authored by the same person who wrote both the production code under
test and every prior benchmark fixture. A 4-fixture, single-author gap
is not yet strong evidence that the distinction is real and general --
it could be an artifact of what one analyst happened to think to test.

## 47. Purpose of independent-adversarial validation

V3's question, stated in the mission that produced it:

> "Can an independently designed adversarial fixture reproduce the
> apparent value of recursive root-evidence resolution using a simpler
> method, or cause the current Witnessgraph method to fail within its
> stated provenance-level scope?"

The explicit goal is falsification, not confirmation. V3 was built with
a standing instruction not to bias every fixture toward a Witnessgraph
win (section 49), and the result set below keeps that promise: 6 of 12
fixtures are TIES or true-negative/true-positive controls where Baseline
2 performs exactly as well as Witnessgraph (section 51).

## 48. Fixture-generation methodology

Twelve fixtures (`research/wg_bench/v3/fixtures/`), each built from a
topology not reused, only relabeled, from any V1/V2 fixture -- parallel
disjoint-node branches, non-convergent 3-hop paths, single-hop parallel
edges, and (new to V3) genuine N>1-level `NormalizedEvent` chaining and
deliberately dangling `derived_from` ids (`research/wg_bench/v3/graph_builder.py`).
Every fixture's `GroundTruthV2` (V2's own model, reused unmodified) was
written by reasoning about the fixture's intended topology before ever
running it against `analyze_paths_evidence_overlap` -- never generated
by calling that function and copying its output, exactly as V1/V2's
discipline required (section 5/31). `tests/unit/test_wg_bench_v3.py::test_fixture_build_matches_its_own_ground_truth`
independently confirms every fixture's `build()` produces the graph its
ground truth describes, for all 12 fixtures.

## 49. Adversarial categories and design discipline

Ten structural categories from the V3 mission (multi-level lineage,
cross-branch shared/disjoint root, mixed root depth, high-multiplicity
collapse/disjoint, complex partial overlap, redundant representations,
direct-reference decoy/convergence) are each represented by exactly one
fixture, plus two independently-authored adversarial fixtures retesting
the provenance-vs-epistemic-independence boundary from both directions
(section 58). Every fixture's own module docstring states its purpose
and, honestly, its expected outcome for Baseline 2 vs. Witnessgraph --
including the fixtures expected to tie or favor Baseline 2's equivalence
(`cross_branch_shared_root.py`, `cross_branch_disjoint_root.py`,
`high_multiplicity_disjoint.py`, and both adversarial fixtures), written
*before* the benchmark was run, not adjusted afterward to match results.
No fixture was discarded or rewritten because its result was
unfavorable; section 51 reports exactly what every fixture produced.

Nine "attack" assumptions from the mission were probed directly:

| # | Assumption attacked | Fixture(s) | Result |
| --- | --- | --- | --- |
| 1 | Different direct ids imply different evidence | `multi_level_lineage_v3`, `mixed_root_depth`, `direct_reference_decoy`, `redundant_representations` | False -- all 4 fool Baseline 2 |
| 2 | Different derivation branches imply different evidence | `cross_branch_shared_root` | False in principle, but this specific (no-indirection) fixture doesn't exercise it -- both methods agree |
| 3 | Same intermediate evidence implies same root | not separately testable without breaking content-addressing (section 59) | n/a -- see limitation |
| 4 | Recursive lineage always reaches a meaningful root | `multi_level_lineage_v3` (N=2 levels) | Holds -- BFS resolves correctly at N>1 |
| 5 | Boolean independence is sufficient for multi-path cases | `partial_overlap_complex` | False -- confirms H3 at n=4/6 pairs (section 56) |
| 6 | Path multiplicity correlates with corroboration | `high_multiplicity_collapse` | False -- 5 branches, 1 root |
| 7 | Content-addressed identity captures source independence | `same_source_disjoint_root`, `byte_identical_different_source` | False, both directions (section 58) |
| 8 | Root evidence is always semantically independent when ids differ | `same_source_disjoint_root` | False (adversarial, by design -- section 58) |
| 9 | All provenance chains are acyclic and well-formed | investigated directly, not fixture-testable (section 59) | Acyclic by construction; malformed (dangling) is representable and handled gracefully (`direct_reference_convergence`) |

## 50. Ground truth and baseline definitions

V3 reuses V2's data model, evaluation harness, and all four methods
completely unmodified: `research.wg_bench.v2.model.GroundTruthV2`,
`research.wg_bench.v2.evaluation.evaluate_fixture`, Baseline 0
(path-count-only), Baseline 1 (path-structure), Baseline 2 (direct
evidence-reference, no recursion), and Witnessgraph's real, unmodified
`find_all_shortest_paths`/`analyze_paths_evidence_overlap`. This is
deliberate: V3's comparison is only meaningful if it uses the identical
scoring machinery V2 used, so a difference in results reflects the
fixtures, not a redefinition of the methods. The one change made to
shared V2 infrastructure was non-semantic: `research/wg_bench/v2/metrics.py`'s
`BINARY_EXCLUDED_CLASSES` set gained `"PARTIAL_OVERLAP_COMPLEX"` (a
V3-only fixture class) so V3's complex partial-overlap fixture is
grouped with V2's `PARTIAL_OVERLAP`/`PARTIAL_MULTI_ROOT`, not the binary
confusion matrix -- confirmed inert for V2 by rerunning
`python -m research.wg_bench.v2`, whose results (section 34's table)
are byte-for-byte unchanged.

## 51. Complete V3 results

Reproduced from `python -m research.wg_bench.v3`; independently pinned
by `tests/unit/test_wg_bench_v3.py`'s exact-count assertions.

**Binary-classification group (n=9):**

| Method | TP | FP | FN | TN | Accuracy | Precision | Recall | False-positive rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Baseline 0 (path-count-only) | 3 | 6 | 0 | 0 | 0.333 | 0.333 | 1.00 | **1.00** |
| Baseline 1 (path-structure) | 3 | 6 | 0 | 0 | 0.333 | 0.333 | 1.00 | **1.00** |
| Baseline 2 (direct evidence-reference) | 2 | 5 | 1 | 1 | 0.333 | 0.286 | 0.667 | **0.833** |
| Witnessgraph (recursive root-evidence) | 3 | 0 | 0 | 6 | **1.00** | 1.00 | 1.00 | **0.00** |

Witnessgraph's binary confusion matrix is again perfect. Baseline 2's
false-positive rate (0.833) is *worse* on V3's binary group than V2's
(0.571) -- not because V3 is biased against it, but because V3's binary
group is deliberately weighted toward indirection-exercising fixtures
(6 of 9); the true-negative/tie fixtures (`cross_branch_disjoint_root`,
`high_multiplicity_disjoint`) land in `TN`, and Baseline 2 additionally
produces its first-ever **false negative** in this benchmark family
(`FN=1`, `direct_reference_convergence` -- section 53) where it wrongly
calls a genuinely-independent case non-independent, an error direction
neither V1 nor V2 ever observed.

**Partial-overlap group (n=1):** `partial_overlap_complex` -- see
section 56.

**Adversarial group (n=2):** `same_source_disjoint_root`,
`byte_identical_different_source` -- both methods agree with the
(correct, provenance-level) ground truth on both; see section 58.

**Determinism:** 12/12 fixtures (100%) produced byte-identical manifest
hashes and canonical JSON across two independent in-process builds
(`tests/unit/test_wg_bench_v3.py::test_fixture_is_deterministic_across_independent_builds`).
Additionally, two independent, separate process invocations of
`python -m research.wg_bench.v3 --out-dir <dir>` from the same
repository state produced byte-identical `results.json` and
`results.txt` (verified manually; not itself a CI-enforced check, same
as V1/V2's equivalent whole-run verification).

## 52. Discriminator analysis

`research/wg_bench/v3/metrics.py` adds five counts over the 12 fixtures
(computed only where the binary question applies -- all 12 here):

| Metric | Value |
| --- | --- |
| `discriminator_count` (Baseline 2 != Witnessgraph) | 6 |
| `correct_discriminator_count` (of those, Witnessgraph right, Baseline 2 wrong) | 6 |
| `baseline_equivalence_count` (both correct, same verdict) | 6 |
| `adversarial_defeat_count` (Baseline 2 >= Witnessgraph) | 6 |
| `witnessgraph_error_count` (Witnessgraph wrong vs. ground truth, in-scope) | **0** |

Every one of the 6 discriminating fixtures favors Witnessgraph
(`correct_discriminator_count == discriminator_count`); Baseline 2 never
wins outright and Witnessgraph is never wrong in-scope. But exactly half
(6/12) of all binary-applicable fixtures are ties/equivalences by
design -- V3 did not find a case that defeats Witnessgraph, but it also
did not find that Witnessgraph "always wins": on any fixture without
`NormalizedEvent` indirection, Baseline 2 matches it exactly.

## 53. Baseline 2 vs. Witnessgraph: fixture-by-fixture outcome

Every V3 fixture, explicitly, per the mission's requirement not to hide
negative results:

| Fixture | Outcome | Note |
| --- | --- | --- |
| `v3-multi-level-lineage-01` | **Witnessgraph wins** | True N=2-level chaining (section 59) |
| `v3-cross-branch-shared-root-01` | **Tie** (both correct) | No indirection anywhere |
| `v3-cross-branch-disjoint-root-01` | **Tie** (both correct) | No indirection anywhere |
| `v3-mixed-root-depth-01` | **Witnessgraph wins** | 0-vs-1-level depth mismatch |
| `v3-high-multiplicity-collapse-01` | **Witnessgraph wins** | 5 branches, 15 events, 1 root |
| `v3-high-multiplicity-disjoint-01` | **Tie** (both correct) | 5 branches, 5 disjoint roots |
| `v3-partial-overlap-complex-01` | **Tie** (both correct) | No indirection; H3 case, not a B2-vs-WG case (section 56) |
| `v3-redundant-representations-01` | **Witnessgraph wins** | Minimal single-hop case |
| `v3-direct-reference-decoy-01` | **Witnessgraph wins** | Non-convergent 3-hop paths |
| `v3-direct-reference-convergence-01` | **Witnessgraph wins** | Baseline 2's error is a false NEGATIVE here (dangling-id decoy), the only such case in this benchmark family |
| `v3-same-source-disjoint-root-01` | **Tie** (both correct at provenance level; adversarial) | Ground truth is not "ambiguous" -- it is deliberately two-layered: provenance-correct, epistemically limited (section 58) |
| `v3-byte-identical-different-source-01` | **Tie** (both correct at provenance level; adversarial) | Same two-layered structure, opposite direction (section 58) |

No fixture produced an outcome outside Witnessgraph's stated scope in
the sense of an actual wrong answer; the two adversarial fixtures are
correct-but-insufficient (section 58), not incorrect. No fixture was
excluded or rewritten to avoid an unfavorable result.

## 54. H1 reassessment

**H1** ("root-evidence overlap analysis reduces false-corroboration
classifications relative to path-count-only reasoning") **remains
supported**, unchanged from V1/V2 (sections 35, still subject to the
same Baseline-0-circularity caveat from section 26/49 of this document:
every binary fixture across all three benchmark generations was built
with path multiplicity by construction).

## 55. H1b reassessment -- the critical hypothesis

**H1b** ("recursive root-evidence resolution provides measurable
classification information beyond direct evidence-reference comparison")
was V2's finding on 4 self-authored fixtures. V3 does not merely repeat
that claim -- it actively tried to break it (section 47) with 12
independently-constructed, structurally novel fixtures, including 6
explicitly not expected to favor Witnessgraph. Result:
**H1b is confirmed, not merely repeated** -- 6 new, independently
designed discriminating fixtures found, all correctly favoring
Witnessgraph, `witnessgraph_error_count = 0`, and the new discriminating
mechanisms (N=2-level chaining, depth mismatch, non-convergent
topology, single-hop parallel representations, and a dangling-reference
decoy that fools Baseline 2 in the *opposite* error direction from every
other case) are not id-relabelings of V2's 4 fixtures -- they are
genuinely different structural triggers for the same underlying
mechanism (recursive resolution past the first `derived_from` id).
V3 did not find a case where Baseline 2 outright defeats Witnessgraph.
It did, honestly, find that half of all adversarially-constructed
binary fixtures are ties -- the gap is real but still confined to
`NormalizedEvent`-indirection cases specifically, exactly as V2's
section 44 "MODERATE SIGNAL" framing already predicted; V3 raises
confidence in that framing without broadening it.

## 56. H3 reassessment

**H3** ("the Boolean/null result loses pairwise information in
partial-overlap cases") is **reconfirmed at a larger, independently
designed scale**. `partial_overlap_complex` (P1={R1,R2}, P2={R2,R3},
P3={R3,R4}, P4={R5}; direct evidence only, no indirection) has 4 chains
/ 6 pairs, of which 4 (66.7%) are genuinely root-evidence-disjoint, but
the single top-level boolean is `False` (some pair overlaps) and masks
all 4. This is the identical 66.7% rate both V1's 3-chain and V2's
6-chain partial-overlap fixtures already found (section 39's table) --
now confirmed a third, independent time, at n=6 pairs, by a different
author's fixture design. Because this fixture cites evidence directly
(no `NormalizedEvent`), Baseline 2's own boolean loses the exact same
information Witnessgraph's does (`direct_pairs_masked_by_boolean == 4`,
identical to `root_pairs_masked_by_boolean`) -- H3 is a representation
question, orthogonal to the recursive-resolution question H1b asks, and
this fixture was specifically designed to isolate that.

## 57. Recursive root-evidence value: precise conditions

**Where Witnessgraph adds value** (section 53's "Witnessgraph wins"
rows, 6/12 fixtures): exactly, and only, when at least one returned
chain's relationships cite a `derived_from` id that itself requires
resolving through a `NormalizedEvent` (one level, per V2, or more, per
`multi_level_lineage_v3` -- section 59) before reaching the id(s) that
determine whether two chains share evidence, in a topology where two
chains' *unresolved* ids differ but their *resolved* roots coincide (or,
in the convergence case, where an unresolved id coincidentally matches
across chains but resolves to nothing).

**Where it does not** (section 53's "Tie" rows, 6/12 fixtures): any
fixture where every relevant `derived_from` id is already a root
`EvidenceItem` id (no indirection at all) -- there, Baseline 2's direct
reference set and Witnessgraph's root evidence set are the identical
set by construction, and the two methods cannot disagree, regardless of
path count, branch topology, or how many chains are involved
(`high_multiplicity_disjoint` shows this holds at 5 branches, not just
2). Path multiplicity and branch-topology complexity alone -- without
indirection -- given Baseline 2 no additional opportunity to be fooled.

## 58. Source-identity limitation, both directions

V1/V2 established (section 11/40): root-evidence *disjointness* does
not imply epistemic independence (`byte-distinct-same-source-01`,
`v3-same-source-disjoint-root-01` here as an independent retest with a
different narrative -- two re-exported photographs of one physical
scene, not V1's trailing-newline JSON export -- and a different
topology). Both methods agree, correctly, that the two records are
provenance-disjoint; the limitation is entirely outside what either
method claims to answer.

V3 adds the **mirror-image** case, not previously tested:
`v3-byte-identical-different-source-01` shows root-evidence *sharing*
does not imply epistemic non-independence either. Two parallel
relationships cite the literal same `EvidenceItem` (content-addressed
deduplication makes two byte-identical submissions collapse to one
stored record before this analysis ever runs), while the fixture's own
ground truth declares them, as benchmark metadata only, to represent two
independent real-world submissions (e.g. two witnesses whose accounts
happen to be identical). `fully_evidence_independent = False` is the
correct provenance-level answer for both methods; the limitation is that
"shared root" cannot, by construction, distinguish "the same record
cited twice" from "two independent records that happen to be
byte-identical" -- this happens upstream, at ingest-time
content-addressing, before either method's analysis begins. No
production change is implied or suggested; content-addressed
deduplication is deliberate (DESIGN.md principle 1).

Together, these two fixtures show the provenance/epistemic boundary is
symmetric: neither disjoint roots nor shared roots are reliable
epistemic-independence signals on their own, in either direction.

## 59. Malformed/cyclic provenance findings

**Cyclic provenance:** investigated directly against `core.events` and
`core.relationships` (not fixture-testable, since no fixture can
demonstrate the absence of something). Both `NormalizedEvent` and
`Relationship` ids are content hashes of their own identity fields,
including `derived_from` (`NormalizedEvent.identity_hash`,
`Relationship.identity_hash`). A true cycle (`A.derived_from` contains
`B`'s id and `B.derived_from` contains `A`'s id) is **structurally
unconstructible** through the public model: `B`'s id can only be known
after `B` is constructed, so `A` cannot cite it before `B` exists, and
constructing a new object that cites `B` produces a *new*, distinct id,
never retroactively mutating `A`. `correlate.graph._resolve_root_evidence_ids`'s
own docstring already describes this as "cycle-safe by construction,"
and this investigation confirms the stronger claim: cycles are not just
handled safely if they occurred, they cannot occur at all, given
content-addressed ids. This satisfies the mission's section 8
instruction to document a limitation, in the direction of "this attack
surface does not exist," rather than inventing unsupported behavior.

**Malformed (dangling) provenance:** by contrast, this IS constructible
and IS representable through the public model -- `NormalizedEvent.derived_from`
and `Relationship.derived_from` are plain `tuple[str, ...]` fields with
no referential-integrity check at construction time (confirmed by
reading `core/events.py`/`core/relationships.py`'s field validators,
which check only non-emptiness). `research/wg_bench/v3/graph_builder.py`'s
`dangling()` constructs exactly this: a syntactically valid id never
written to the store. `v3-direct-reference-convergence-01` demonstrates
Witnessgraph's actual, already-existing handling is graceful:
`_resolve_root_evidence_ids` treats a dangling id as contributing the
empty set (via `resolve_evidence_ref`'s documented `"not_found"` kind),
not a crash or a fabricated root -- and this graceful handling is
exactly what lets Witnessgraph resolve that fixture correctly while
Baseline 2 is fooled by the shared dangling id (section 53).

**Also newly demonstrated (not anticipated by V2):** V2's own
`multi_level_lineage.py` fixture states that `NormalizedEvent.derived_from`
"cannot itself name another NormalizedEvent under any current ingest
adapter," true for the adapters but not, this investigation found, true
at the data-model level -- nothing in `core.events.NormalizedEvent`
forbids it, and `_resolve_root_evidence_ids`'s BFS (a `visited` set, a
`frontier` list, no depth limit) already handles arbitrary depth.
`v3-multi-level-lineage-01` constructs a genuine
`Relationship -> NormalizedEvent -> NormalizedEvent -> EvidenceItem`
chain (N=2 levels of indirection, not V2's N=1) and confirms
Witnessgraph resolves it correctly. This is not a production bug --
production code behaves exactly as its own docstring already promised
("cycle-safe," implicitly depth-unlimited) -- it is a correction to a
benchmark comment, and a modest strengthening of section 55's H1b
finding: the discriminating mechanism generalizes past exactly one
indirection level.

## 60. Threats to validity (V3-specific, in addition to sections 13/41)

- **Still one author.** V3 was designed adversarially and against a
  standing instruction not to bias fixtures toward Witnessgraph, and 6
  of 12 fixtures did land as ties/negative results -- but V3 was still
  designed by someone with full knowledge of V2's exact 4-fixture gap
  and of `correlate.graph`'s source, not a blind, truly independent
  third party. Section 61 recommends what a genuinely external
  adversarial pass would need.
- **12 fixtures is still small.** Sufficient to demonstrate the
  discriminating mechanism generalizes past V2's original 4 cases and to
  pin it against regression, not sufficient to estimate a reliable
  false-corroboration rate for realistic casework (same caveat as
  section 13's "small benchmark size").
- **The dangling-reference decoy (`direct_reference_convergence`) is a
  synthetic worst case.** Nothing in this repository's current ingest
  adapters is known to produce a dangling `derived_from` id in practice;
  this fixture demonstrates the model *permits* it and Witnessgraph
  *handles* it gracefully, not that it is a realistic failure mode
  analysts will actually encounter.
- **The N=2-level chaining case (`multi_level_lineage_v3`) is similarly
  synthetic** relative to current ingest adapters (section 59) -- a real
  finding about the data model's capability, not a claim that today's
  adapters produce such chains.
- **Discriminator/tie split (6/6) is fixture-composition-dependent.**
  Changing how many "no indirection" vs. "indirection" fixtures V3
  happens to include would shift this exact ratio; it should be read as
  "both outcomes are real and reproducible," not as a claim that
  Witnessgraph wins "half the time" in any general sense.

## 61. Does the research gap survive V3?

**Yes.** Every one of V2's 4-fixture, single-author discriminating
result was matched or exceeded by 6 new, independently-designed,
structurally distinct discriminating fixtures, including a genuinely
new error-direction case (`direct_reference_convergence`'s false
negative) and a genuinely new depth case (`multi_level_lineage_v3`'s
N=2 chaining) that V2 did not anticipate. `witnessgraph_error_count = 0`
across all 12 adversarially-designed fixtures -- no case was found,
despite deliberately trying, where Witnessgraph's actual production
output disagrees with independently-authored ground truth within its
stated provenance-level scope. Baseline 2 was never found to outright
outperform Witnessgraph on any fixture.

But the gap did not *widen* in scope -- it stayed exactly where V2
found it: `NormalizedEvent` indirection, in any of its forms. On every
fixture without indirection, including at 5x path multiplicity and 4x2
pairwise complexity, Baseline 2 matched Witnessgraph exactly. V3
upgrades confidence in V2's section 44 "MODERATE SIGNAL" verdict from
"plausible, needs independent verification" to "verified against an
honest adversarial attempt, not yet defeated" -- it does not upgrade the
verdict itself to STRONG SIGNAL, because the discriminating condition
remains precisely localized, not broad.

## 62. Production code changes

**Zero**, verified with
`git diff d091d5b -- src/ frontend/ core/ correlate/ store/ service/ api/`
(empty). Only `research/wg_bench/v2/metrics.py` (one non-semantic
grouping-set addition, section 50), `research/wg_bench/v3/` (new), and
`tests/unit/test_wg_bench_v3.py` (new) were touched. No production bug
was found (section 59's finding is a correction to a V2 benchmark
comment, not a production defect).

## 63. What V3 does NOT establish

- It does not establish that Baseline 2 can never match Witnessgraph on
  a broader, professionally-constructed non-recursive baseline than this
  benchmark's own Baseline 2 -- only that this specific, already-fairly-
  designed Baseline 2 (section 29) did not, on these 12 new fixtures.
- It does not establish real-world prevalence of `NormalizedEvent`
  indirection, N>1-level chaining, or dangling references in actual
  ingest pipelines (section 60).
- It does not upgrade section 44's provenance-vs-epistemic-independence
  scope boundary (section 58) -- if anything it sharpens it, by showing
  the boundary runs in both directions.
- It does not establish that a genuinely external, third-party
  adversarial author (not this benchmark's own author, however
  disciplined) would fail to find a case this iteration missed (section
  60's first threat, section 64).
- It does not change V1/V2's cross-machine/cross-OS-determinism gap
  (still unimplemented -- section 12/45).

## 64. Recommended next research milestone

**Genuinely external adversarial review**, not another internally-authored
V4. V3 closed the "single-author V2 fixtures" gap by having the same
author try, honestly, to break their own result -- and found the result
held, while also finding it does not broaden. The highest-value next
step is qualitatively different: put `research/wg_bench/v1`, `v2`, and
`v3` (or just `correlate.graph`'s public functions and the V1-V3
result tables) in front of someone with no prior involvement in this
benchmark or the production code, and ask them, unprompted, either to
(a) construct a fixture that defeats Witnessgraph within its stated
scope, or (b) construct a non-recursive baseline that matches
Witnessgraph more broadly than this benchmark's Baseline 2. Only a
result that survives *that* should be treated as more than "not yet
falsified by its own author." Section 45's other candidates (CI
determinism matrix, `examples/sample-case`-scale fixtures) remain valid
but lower priority, unchanged from V2.
