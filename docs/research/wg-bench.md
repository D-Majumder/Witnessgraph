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
