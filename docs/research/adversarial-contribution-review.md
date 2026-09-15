# Adversarial Contribution Review

Status: research evaluation only. No production code was modified to
produce this document. Reviewed at HEAD `c0754a6926a167ca473be3d8c8095c70f59bb51a`
(804 tests passing, `ruff`/`mypy --strict` clean at time of review).

**Update:** the experiment this document's §20 recommended has since
been built and run — see `docs/research/wg-bench.md` (WG-Bench) and
`research/wg_bench/`. Its results confirm this document's own §5/§17
findings empirically (an adversarial byte-distinct-same-source fixture
does produce a mechanically "independent" verdict that does not hold up
epistemically) and confirm §11's proposed research gap is real and
measurable (root-evidence overlap analysis achieves a 0% false-
corroboration rate against a 100% rate for path-count-only reasoning on
WG-Bench's binary-classification fixture group). The rest of this
document is left unchanged below; it reflects the state of the project
*before* that experiment existed, which is what it was written to
assess.

This is a deliberately skeptical, external-reviewer-style read of whether
Witnessgraph currently represents a meaningful technical/research
contribution, or a well-engineered software system without one. Where the
two are in tension, this document sides with the more skeptical reading
and says so explicitly.

## 1. Core research abstraction

Witnessgraph's technical content, read across `core/`, `correlate/`, and
`store/`, decomposes into a small number of well-known building blocks
applied with unusual consistency:

- content-addressed, immutable evidence (`EvidenceItem.id ==
  raw_content_hash`) — the Git-object / IPFS pattern applied to forensic
  case data;
- deterministic canonical-JSON hashing for every derived object
  (`core/ids.py`) so identity is a pure function of content, not
  insertion order or wall-clock time;
- a type-level (Pydantic validator) enforcement that an inference object
  (`Hypothesis`) cannot be constructed without citing at least one
  observation object, and that observation objects (`EvidenceItem`,
  `NormalizedEvent`, `Entity`, `Relationship`, `TimeAssertion`) can never
  themselves encode a bare, uncited claim;
- textbook bounded/deterministic BFS-based graph traversal over an
  in-memory adjacency built from `Entity`/`Relationship` rows.

None of these four ingredients is, by itself, a research contribution —
each has direct, decades-old precedent (content addressing, canonical
serialization, typed observation/inference separation as in Analysis of
Competing Hypotheses' evidence/hypothesis matrix, and BFS/shortest-path
enumeration). What is somewhat distinctive is that the *whole case*, not
just individual files, is captured under one recomputable manifest, and
that the observation/inference separation is enforced by the type system
at construction time rather than left to convention or UI discipline —
most comparable DFIR tools (see §10) enforce this, if at all, only in the
UI layer or not at all. That is an engineering-discipline achievement,
not a new abstraction, algorithm, or formalism. The honest label for the
system as a whole is **well-engineered provenance and case-integrity
tooling**, not a new theoretical or algorithmic construct.

The one place this document identifies actual, if narrow, research
framing potential is `correlate.graph.analyze_paths_evidence_overlap`
(§5, §11) — a specific, previously-unformalized-in-tooling distinction
between *structural* path multiplicity and *evidentiary* independence.

## 2. Provenance model

What content-addressed lineage actually provides, mechanically:

- deduplication: byte-identical evidence ingested twice (even from
  different declared sources) collapses to one `EvidenceItem`, with
  custody history merged, not overwritten (`EvidenceItem.declared_source_ids`,
  `SqliteStore.put_evidence`);
- idempotent, crash-safe ingestion: re-running an interrupted `ingest`
  converges rather than duplicates, because every derived id
  (`NormalizedEvent`, `TimeAssertion`, `Relationship`) is itself a
  content hash of identity-relevant fields, not a random UUID (`Entity`
  is the one exception — see §17);
- a case-wide `ProvenanceManifest`: a sorted hash-of-hashes over six
  collections, independent of insertion order and wall-clock ingest
  time, recomputable by anyone holding the case directory
  (`replay`/`verify`).

What is technically interesting: applying this discipline uniformly to
*every* derived object type in a structured case model (not just raw
files, and not just a tool's own output as in DEX — see §10) and making
the full ingest → correlate → export → import → replay loop an actually
tested, round-trip-verified property (`test_export_import_roundtrip.py`,
`test_report_export_import_roundtrip.py`, plus `hypothesis`-based
property tests for serialization/provenance determinism). This is solid,
verifiable systems engineering.

What is ordinary provenance engineering, not a contribution: SHA-256
content addressing, canonical JSON, and a Merkle-style hash-of-hashes are
standard techniques with mature prior art far outside forensics (Git,
IPFS, numerous append-only log designs). Nothing about *how* Witnessgraph
computes or verifies its manifest is new; what is somewhat differentiated
is *what* it is computed over (a full structured investigation model
including relationships and time assertions, not just files or a tool's
processing steps).

## 3. Evidence-backed relationships

A conventional property graph (Neo4j, NetworkX, a hand-rolled adjacency
list) can carry a `derived_from` property on any node or edge purely by
convention — nothing stops an application from adding it, and nothing
enforces that it is ever populated correctly. Witnessgraph's
`Entity`/`Relationship` Pydantic validators refuse to construct the
object at all without a non-empty `derived_from` tuple. That is
*enforcement at construction*, not a new graph-theoretic primitive: it
moves a convention most tools leave to application discipline into the
data model itself.

This is real, but narrower than it sounds once compared against actual
DFIR knowledge-graph research (§10): systems like the Digital Forensic
Knowledge Graph (DFKG) and FEAR build ontology-typed graphs with formal
entity/relation classes, enabling class-based reasoning (e.g., "this
relation type implies this other fact"). Witnessgraph's `entity_type`
and `relationship_type` are free-form, uninterpreted strings — there is
no ontology, no inference rules, no reasoning over relation semantics.
What Witnessgraph formalizes that a conventional graph does not is
narrowly **lineage enforcement**, not relationship semantics or
reasoning. It is, in that specific dimension, *less* expressive than
several academic evidence-graph systems it should be compared against,
not more.

## 4. Graph path multiplicity

`find_all_shortest_paths` (bidirectional BFS to prune to the
shortest-path DAG, then bounded DFS enumeration up to `--limit`) is a
standard restricted form of k-shortest-paths enumeration (restricted to
paths tied for minimum length). This is textbook graph algorithm
engineering — correctly bounded, deterministic, and cycle-safe, but not
research-significant as an algorithm. Nothing here is new relative to
standard graph theory or existing graph-database query capabilities
(e.g., Neo4j's own shortest-path/allShortestPaths procedures do
essentially the same thing).

## 5. Evidence overlap — precisely what is and is not established

`analyze_paths_evidence_overlap` (over the result of
`find_all_shortest_paths`) precisely establishes:

- for the specific, bounded set of chains actually returned (tied for
  shortest length, capped at `--limit`), whether their relationships'
  `derived_from` references resolve — through zero or one hop of
  `NormalizedEvent.derived_from` — to root `EvidenceItem` ids that are
  disjoint across chains;
- a binary/ternary verdict (`true`/`false`/`null` for <2 chains) plus the
  explicit list of shared root evidence ids.

It precisely does **not** establish:

- that a connection is real, causal, or forensically significant —
  explicitly disclaimed in the module and CLI docs;
- evidence independence in any sense beyond byte-level content-hash
  distinctness of the *raw ingested bytes*. Two logically independent
  systems whose logs were concatenated by a human into one file, then
  ingested as one `EvidenceItem`, are indistinguishable from one
  genuinely singular source. Conversely, the same physical event
  captured twice with any byte-level difference (re-export, metadata
  change, re-encoding) is treated as independent evidence, even though a
  domain expert might reasonably call it the same underlying record;
- graded/statistical corroboration strength — the check is boolean per
  evidence id, not weighted by how much of a chain's support is shared
  versus disjoint (three chains where two share one evidence id and the
  third is fully disjoint collapse to the same `fully_evidence_independent:
  false` as three chains that are all mutually dependent on one item);
- anything about chains beyond `--limit`/`truncated` — the verdict
  describes only what was actually returned, never the full graph;
- source reliability, tampering, collusion, or fabrication — this is a
  structural-reference check, not a trust or authenticity assessment.

This is a real, precise, narrow structural fact. It is not evidence
independence in the epistemic sense a DFIR report would need to defend
in court or peer review.

## 6. Temporal reasoning

`TimeAssertion.disagrees_with` (interval-overlap test parameterized by a
fixed table of named-precision tolerances) and the gap-bracketing
algorithm in `correlate/gaps.py` (widened-interval coverage tracking with
a running-maximum-end pointer) are both ordinary interval-arithmetic
techniques — directly comparable to interval scheduling, log-monitoring
gap detection, and coverage analysis used routinely outside forensics.
Neither algorithm is new.

What is not ordinary is the epistemic discipline around them: contradictions
are never adjudicated (no "most trusted source" logic anywhere in the
codebase — confirmed by reading `correlate/contradictions.py` and
`correlate/gaps.py` in full), and absence-of-evidence findings carry
explicit, tested exclusion counters (`excluded_no_time_assertion`,
`excluded_no_declared_source`, `excluded_ambiguous_source`,
`excluded_unrefined_fallback_with_refined_sibling`) so that evidence
silently excluded from analysis is still visibly accounted for. That is
good documentation and interface design, not a temporal-reasoning
contribution. The model itself contributes nothing beyond an ordinary
event timeline with error bars.

## 7. Contradictions and gaps: analytical model or reporting feature?

Structurally, both are filters over already-computed pairwise/interval
relationships — not a semantic or probabilistic model. There is no
ranking by materiality, no clustering of related contradictions, no
propagation (e.g., "this contradiction implies these three downstream
claims are also suspect"), and no formal consistency-checking machinery
(contrast with SAT/ASP-based inconsistency detection used in some
knowledge-base research, or Bayesian evidence-fusion approaches).
Despite careful terminology ("structural finding," never "conclusion"),
these are UI/reporting features with well-chosen semantics, not an
analytical model in the sense a researcher would recognize one. That
does not make them low-value — a disciplined, honestly-scoped reporting
feature is worth having — but the review must not inflate "detects
structural disagreement between two explicit numbers" into "temporal
reasoning" or "contradiction analysis" as a research claim.

## 8. Hypotheses/findings separation

The three-way structural split — mechanical computation
(`TimeContradiction`/`GapFinding`, pure functions, never persisted),
tracked findings (`TrackedGapFinding`/`TrackedTimeContradiction`,
persisted, content-addressed to the finding's anchor fields, with an
analyst-annotation workflow that is explicitly incapable of ever
becoming authoritative over the anchor), and hypotheses (`Hypothesis`,
always evidence-cited, never computed automatically) — is the closest
thing in the codebase to a defensible research framing candidate. It is
an unusually strict version of a pattern intelligence-analysis tooling
(ACH) and some CTI platforms (OpenCTI's `confidence` field, per the
project's own `phase2-research.md`) implement more loosely. The
`TrackedGapFinding`/`TrackedTimeContradiction` docstrings show real
design tension was worked through here (identity churn on evidence
change, no adjudication status, no "resolved" state).

Its research significance is unproven, not established: there is no
evidence in this repository that this separation changes any measurable
analyst outcome (fewer false conclusions, faster review, better
inter-analyst agreement). As implemented, it is a well-justified
*architectural pattern*, not yet a validated *research finding*. Treating
it as the latter without an experiment (§13) would be overclaiming.

## 9. Reproducibility

Deterministic ids, canonical JSON, the six-collection manifest, and
export/import/replay are genuinely implemented and genuinely tested —
this is not aspirational. The tested claim is specific: *given an
unmodified Witnessgraph case directory, its manifest hash is a pure
function of its structured content, independently recomputable, and
survives an export/import round trip.* That claim is defensible today.

What it does not support: the broader, contested "reproducible digital
forensics" claim in the DFRWS/scientific-methodology sense (independent
analysts, using possibly different tools, arriving at the same
interpretation of the same raw evidence — see the "Role of
Reproducibility in Science and Digital Forensics" literature found in
§10's search). Witnessgraph reproduces its own *data structures*
byte-for-byte; it says nothing about whether the *investigation
conclusions* (hypotheses) two analysts would independently form from the
same raw evidence converge, nor about reproducibility across independent
re-implementations, nor across machine/OS/Python-version boundaries
(never tested — see §19). "Reproducible" here is precise and defensible
at the object-serialization level and would be overclaiming at the
scientific-methodology level.

## 10. Prior art

Targeted search (not a superficial competitor list — see citations)
surfaces genuinely overlapping technical work Witnessgraph must be
positioned against, not merely a list of adjacent tools:

- **DEX — "Digital evidence provenance supporting reproducibility and
  comparison"** (Levine & Liberatore, DFRWS 2009, *Digital Investigation*
  vol. 6). This is the closest single prior-art match to Witnessgraph's
  headline claim. DEX proposes a canonical, tool-independent description
  of the *process* provenance of a piece of derived forensic evidence
  (which tools/transformations produced it from a raw image), explicitly
  to support reproduction by a different tool and comparison across two
  investigations of the same raw evidence. **Overlap**: "provenance for
  reproducibility and comparison in digital forensics" as a research
  pairing is *not novel* — it predates Witnessgraph by 15+ years.
  **Difference**: DEX is about tool-chain/process provenance for a
  derived artifact (rerun this transformation, get the same output);
  Witnessgraph is about object-level, case-wide structural provenance
  (this case's entire graph of entities/relationships/hypotheses hashes
  identically). These are different granularities of the same idea, not
  the same contribution restated — but Witnessgraph cannot claim to be
  first to combine "provenance" and "reproducibility" in forensics.
- **Digital Forensic Knowledge Graph (DFKG)** (IEEE, "Visualizing and
  Reasoning about Presentable Digital Forensic Evidence with Knowledge
  Graphs," 2022) and **FEAR** (ACM DFDS 2025, "A Novel Framework for
  Representing Digital Forensic Artifacts in Knowledge Graphs"). Both
  build ontology-typed evidence/entity/relationship graphs for
  visualization and reasoning about a criminal case's timeline and
  evidence. **Overlap**: entity/relationship/timeline graph structure
  over forensic evidence is the same basic shape as Witnessgraph's
  `Entity`/`Relationship`/timeline. **Difference**: these systems invest
  in ontological typing and reasoning (semantic classes, inference over
  relation types) that Witnessgraph deliberately does not have (free-text
  types); Witnessgraph invests instead in cryptographic
  provenance/reproducibility and evidence-independence checking that
  these papers do not appear to formalize.
- **"A Unified Knowledge Graph to Permit Interoperability of
  Heterogeneous Digital Evidence"** (2024, arXiv:2402.13746). Targets
  cross-tool/cross-format interoperability of heterogeneous evidence via
  a unified graph — overlaps with Witnessgraph's adapter-based ingestion
  into a normalized event/entity model, but is oriented at format
  interoperability across existing forensic tools, not provenance
  hashing or evidence-independence analysis.
- **SoK: Timeline-based event reconstruction for digital forensics**
  (2025, ScienceDirect). A systematization-of-knowledge covering
  ontology-based and correlation-based timeline reconstruction
  approaches, explicitly noting the field's use of ontologies to "infer
  new facts and identify correlations between events." Witnessgraph's
  `TimeAssertion`/contradiction/gap layer is a much narrower, more
  conservative instance of this same family (structural, non-inferential
  correlation only) — it explicitly refuses the inference step this SoK
  describes other systems attempting.
- **Analysis of Competing Hypotheses (ACH)** (Heuer, CIA methodology,
  1970s; various software implementations since). ACH's evidence ×
  hypothesis consistency matrix is the direct intellectual ancestor of
  Witnessgraph's evidence-cited `Hypothesis` type — the same underlying
  discipline (never let a conclusion float free of the evidence it rests
  on), implemented as an enforced data-model constraint instead of an
  analyst-filled matrix. Witnessgraph does not cite or position itself
  against this lineage; it should.
- **W3C PROV**. A generic, domain-agnostic provenance data model (entity/
  activity/agent, `wasGeneratedBy`/`used`/`wasAttributedTo`) with prior
  applications sketched in forensic and IoT contexts. Witnessgraph's
  provenance model is a bespoke, narrower re-implementation of
  essentially the same generic idea (entities generated by/derived from
  other entities), not built on or interoperable with PROV. This is a
  legitimate design choice (PROV is heavyweight for this scope) but means
  Witnessgraph cannot claim its provenance model is itself a new
  contribution to provenance modeling generally — the general problem is
  already standardized.
- **Corroboration/independence doctrine in evidence law and intelligence
  analysis**. The general principle that corroboration requires
  independence, and that apparent corroboration from correlated/colluding
  sources is a known failure mode ("false corroboration"), is a
  well-established idea in legal and intelligence-analysis literature.
  Witnessgraph's evidence-independence check is a first *mechanized,
  graph-native* check for this specific failure mode inside a forensic
  relationship graph — this is the most defensible candidate for
  "narrow, real gap" (see §11), precisely because the underlying concern
  is old and well recognized, but a computable check for it inside an
  evidence *graph* (as opposed to an evidence *list* or witness
  testimony) does not appear formalized in the surveyed forensic
  graph/knowledge-graph literature.

## 11. Narrowest defensible research gap

None of the surveyed systems combine: (a) a computable, first-class
check for whether multiple *structurally* distinct corroborating paths
in an evidence graph are also *evidentially* independent (disjoint root
evidence), exposed as a queryable, bounded, deterministic result, with
(b) a case-wide cryptographic reproducibility guarantee over that same
structured graph. DFKG/FEAR/Unified-KG papers build the graph and reason
over it ontologically, but do not appear to formalize an
evidence-independence check on corroborating paths. DEX formalizes
provenance/reproducibility, but at the tool-chain level, with no graph of
entities/relationships to check path-level corroboration against at all.

**The narrowest defensible research gap Witnessgraph could address:**
*Existing forensic evidence-graph tooling conflates "multiple
relationship paths support this connection" with "multiple independent
pieces of evidence support this connection." No surveyed system computes
and exposes the distinction as a first-class, graph-native, deterministic
check.* This is narrow (it is one function,
`analyze_paths_evidence_overlap`, and one CLI flag), which is exactly
what makes it defensible — it does not require defending the whole
system as a research contribution, only this one specific, precisely
statable claim, which the current implementation already computes
correctly but has never been evaluated against ground truth.

## 12. Falsifiable hypotheses

- **H1 (false-corroboration detection).** On a benchmark of synthetic
  cases with designed ground truth (some entity-pairs connected by
  genuinely evidence-disjoint shortest-path chains, others by
  structurally-distinct chains that are secretly derived from the same
  root `EvidenceItem`), Witnessgraph's `--explain` evidence-independence
  verdict correctly classifies "evidence-independent vs. not" with
  measurably higher accuracy than a baseline that only counts structurally
  distinct chains (i.e., `graph paths` without `--explain`). Falsified if
  accuracy is statistically indistinguishable from the baseline, or if
  the check's false-positive rate (claiming independence when evidence
  is actually shared through an un-modeled channel, e.g. two files with
  duplicated-but-not-byte-identical content) is high enough to be
  misleading in practice.
- **H2 (deterministic replay across environments).** Given identical raw
  evidence files, independently ingesting into a fresh case on ≥2
  distinct machine/OS/Python-minor-version combinations and then running
  `export` → `import` → `replay` produces byte-identical manifest hashes
  in 100% of trials across N synthetic cases. Falsified by any mismatch
  not attributable to a deliberately introduced difference in input.
  (Today this is tested only within a single environment/run; cross-
  environment determinism is asserted by design but not measured.)
- **H3 (graded corroboration is lost).** For corroboration scenarios
  with partial evidence overlap (e.g., 3 tied-shortest chains, 2 sharing
  one root evidence id and 1 fully disjoint), the current boolean
  `fully_evidence_independent` metric is indistinguishable from a
  scenario where all 3 chains share evidence, when scored against a
  ground-truth ranking of "how much independent support actually
  exists." Falsified if analysts/scripts consistently treat the two
  scenarios identically in practice (i.e., if the loss of granularity
  turns out not to matter for downstream judgments) — this hypothesis is
  explicitly a challenge to the current design, not a promotion of it.

## 13. Experimental design

**Experiment 1 (H1 — false-corroboration detection).**
- *Inputs*: N (e.g., 30–50) synthetic multi-source cases built with the
  existing `jsonl`/`csv_timeline`/`syslog` adapters, each containing at
  least one entity pair connected by 2+ tied-shortest relationship
  chains, with a designed ground-truth label per pair: `independent`
  (chains' relationships cite different `EvidenceItem`s) or
  `shared-root` (chains' relationships ultimately trace, through
  `NormalizedEvent.derived_from`, to the same `EvidenceItem`, e.g. one
  ingested record that happened to establish two relationships).
- *Baseline*: `graph paths` (no `--explain`) — i.e., treating the number
  of structurally distinct tied-shortest chains alone as the
  corroboration signal.
- *Independent variable*: whether the judge (an automated script, since
  no human-subjects analyst study is in scope here) is given the
  `--explain`/evidence-independence output or only the raw path count.
- *Dependent variable*: classification accuracy against the ground-truth
  label (`independent`/`shared-root`) per entity pair.
- *Controls*: identical graph topology and hop count across matched
  independent/shared-root pairs, so topology cannot explain a
  performance difference.
- *Expected observation*: the evidence-independence-informed judge
  reaches ~100% accuracy on this benchmark (the check is a deterministic
  function of the same ground truth used to construct the fixtures — it
  should be correct by construction); the path-count-only baseline
  necessarily cannot distinguish the two classes at all, since it has no
  access to evidence identity. This experiment's actual research value is
  not "does the code work" (it should, trivially, given the ground truth
  was built to match its own logic) but *characterizing the boundary
  cases it cannot see* — see the falsifying result below.
- *Possible falsifying result*: construct adversarial fixtures where two
  `EvidenceItem`s are byte-distinct but represent the same real-world
  record (e.g., the same log line re-exported with a trailing newline
  difference, or copy-pasted into two files) — if the tool reports
  `fully_evidence_independent: true` for such a pair, this falsifies any
  claim that the check detects *real-world* evidentiary independence
  rather than *byte-level* distinctness, which is the precise limitation
  §5 and §17 already predict and which the experiment should confirm
  empirically rather than only by code inspection.

**Experiment 2 (H2 — deterministic replay across environments).**
- *Inputs*: the same N synthetic cases.
- *Baseline*: none required; the property under test is internal
  consistency, not comparison against another tool.
- *Independent variable*: the machine/OS/Python-version combination used
  to ingest and export.
- *Dependent variable*: whether the recomputed manifest hash after
  import matches the originally recorded one (`witnessgraph verify`).
- *Controls*: identical raw input files and identical CLI invocation
  sequence across environments.
- *Expected observation*: 100% match rate, given `core.ids.canonical_json_bytes`'s
  explicit UTC-normalization and sorted-key design is intended to make
  exactly this true.
- *Possible falsifying result*: a mismatch traceable to a
  platform-dependent behavior not currently pinned down in tests — e.g.
  filesystem path separators leaking into a `source_locator` string, or
  floating-point precision differences in `tolerance_seconds()` arithmetic
  across platforms. If found, this would be a real, previously-unverified
  correctness gap in the reproducibility claim, not a mere inconvenience.

## 14. Benchmark

A practical, in-repository benchmark ("WG-Bench") requires no proprietary
forensic suites:

1. A new fixture directory (e.g. `tests/fixtures/benchmark/case-*/`),
   each containing synthetic raw evidence files for the existing three
   adapters plus a hand-authored `expected.json` ground-truth answer key
   per case, recording: expected entities/relationships (by
   deterministic id, since `Relationship.id` and most other ids are
   content-derived and therefore predictable ahead of time), which
   entity-pairs are evidence-independent vs. shared-root by design, which
   `TimeAssertion` pairs should contradict, and which coverage gaps
   should be reported at a fixed `--min-gap-seconds`.
2. A benchmark runner script that drives the existing CLI/service layer
   end-to-end per fixture case and diffs actual output
   (`graph paths --explain --format json`, `contradictions --format
   json`, `gaps --format json`) against `expected.json`, computing
   precision/recall per capability rather than a single pass/fail.
3. This is buildable entirely from what already exists (adapters, CLI,
   `--format json` output for every analytical capability, per the
   README's "no exception" JSON-output guarantee) — it requires new test
   fixtures and a runner script, not new production capability.

## 15. Metrics

- **Provenance completeness** — % of derived objects in a case (every
  `NormalizedEvent`/`Entity`/`Relationship`/`TimeAssertion`) whose
  lineage chain resolves, with zero dangling references, all the way to
  a root `EvidenceItem`. Measured directly and cheaply by walking the
  store with the existing `resolve_evidence_ref`/`_resolve_root_evidence_ids`
  functions over every object in a case, not by survey or sampling.
- **Lineage reconstruction accuracy** — on WG-Bench fixtures, % of
  entities/relationships whose actual `derived_from` set exactly matches
  the fixture's ground-truth intended lineage. Measured by exact-set
  comparison against `expected.json`; catches wiring bugs (an adapter or
  CLI command citing the wrong evidence id), not analytical quality.
- **Reasoning reproducibility** — % of WG-Bench cases for which two
  independent pipeline runs (fresh case directories, same raw inputs)
  produce byte-identical `contradictions`/`gaps`/`graph paths --explain`
  JSON output, not merely an identical manifest hash. Measured by a
  scripted two-run diff; this is a stronger and more directly useful
  check than the manifest hash alone, since it verifies the *analytical
  outputs* an analyst actually reads, not only the underlying data.
- **False corroboration rate** — on the shared-root-labeled entity pairs
  in WG-Bench, the fraction correctly flagged `fully_evidence_independent:
  false` (recall), and on the independent-labeled pairs, the fraction
  incorrectly flagged `false` (false-positive rate). This is the
  sharpest, most feature-specific metric proposed here and should be the
  headline number of any experiment run against this document's Gap/H1.
- **Deterministic replay success** — % of (case, environment) pairs in
  an N-case × M-environment matrix (§13, Experiment 2) whose manifest
  hash matches after export/import. Measured via `witnessgraph verify`'s
  own `MATCH`/`MISMATCH` verdict, run in CI across a small OS/Python
  matrix rather than only Ubuntu/3.11 as today.
- **Explicitly not recommended without a real user study**: "analyst
  interpretation error" and "query/result equivalence" as free-floating
  metrics. Neither is measurable from this repository alone; claiming
  either without an actual human-subjects study would be exactly the
  kind of vague, unfalsifiable claim this review was asked to avoid.

## 16. Strongest possible one-paragraph research contribution statement

> Witnessgraph demonstrates that a forensic evidence graph can be
> constructed so that every derived claim — a normalized event, an
> entity, a directed relationship, a time assertion, or a
> mechanically-computed coverage or contradiction finding — carries
> enforced, machine-checkable lineage back to immutable, content-addressed
> raw evidence, with the entire structured case (not merely its raw
> files) captured under one independently recomputable cryptographic
> manifest that survives export/import; built on this substrate, it
> implements a specific, previously-unformalized-in-tooling structural
> distinction between path multiplicity (multiple structurally distinct
> relationship chains connecting two entities) and evidentiary
> independence (whether those chains' provenance ultimately traces to
> disjoint root evidence), giving a mechanically-checkable, bounded,
> deterministic signal for a long-recognized but under-tooled failure
> mode — false corroboration arising from a shared underlying source —
> inside a forensic relationship graph, a check that the surveyed prior
> art in forensic knowledge graphs and evidence-provenance systems does
> not appear to compute.

## 17. Weakest point an expert DFIR reviewer would attack

**Every trust boundary in this system is the analyst's own honesty and
care, with zero independent verification, and the "evidence
independence" guarantee is only as strong as byte-level content-hash
distinctness of whatever was ingested.** Concretely:

- `source_id` (the entire basis of gap analysis) is a free-text,
  analyst-declared label with no verification against physical reality;
  the README's own "Known limitations" section already concedes that
  `source_id` collisions silently mask real gaps.
- `EvidenceItem` identity is the hash of raw bytes, not of semantic
  content — the same real-world record can be split into two
  byte-distinct evidence items (re-export, re-encoding, or a human
  splitting one file into two) and be reported as "evidence-independent"
  corroboration, which is precisely the false-corroboration failure mode
  this system's headline feature (§5, §11) claims to guard against. The
  guarantee therefore has a gap at exactly the point a sophisticated or
  even just careless analyst would most need it to hold.
- `Entity` identity is a random UUID with no automatic or fuzzy
  resolution (explicitly out of scope) — two entities that are the same
  real-world thing, entered separately, are permanently and silently
  distinct entities, which can fragment a graph and produce spuriously
  "disjoint" or spuriously "connected" results depending on how an
  analyst happened to enter data.
- There is no clock-skew correction anywhere (conceded directly in the
  README), which undermines both contradiction detection and gap
  analysis in exactly the multi-source scenarios the tool is pitched at.

A reviewer's summary line would be: *this is a well-built bookkeeping
and audit layer over analyst-declared facts, not a forensic reasoning
advance — its guarantees are real but shallow, holding at the
data-structure level while leaving every forensically hard problem
(source reliability, entity resolution, clock skew, semantic evidence
identity) explicitly and knowingly unaddressed.* That is a legitimate,
disclosed design scope (the project's own docs concede most of this
directly), but it means the "research contribution" framing needs to be
scoped exactly as narrowly as §11 does, not stretched to cover the whole
system.

## 18. What NOT to claim

- Do **not** claim Witnessgraph "improves investigations," "makes
  forensics more explainable," or reduces analyst error — none of this
  is tested or measured anywhere in the repository.
- Do **not** claim novelty for "provenance + reproducibility" as a
  pairing in digital forensics — DEX (2009) precedes this by over 15
  years, at a different (tool-chain) granularity.
- Do **not** claim the evidence-graph model is more expressive,
  ontologically richer, or more capable of reasoning than existing
  forensic knowledge-graph research (DFKG, FEAR) — it is deliberately
  simpler (free-text types, no ontology, no inference).
- Do **not** claim the evidence-independence check detects source
  collusion, evidence fabrication, re-encoded duplicate sources, or
  anything about physical/institutional independence — it checks
  byte-level content-hash distinctness only.
- Do **not** claim gap/contradiction thresholds
  (`min_gap_seconds`, per-precision tolerance seconds) are empirically
  validated or tuned — the codebase's own docstrings explicitly disclaim
  them as policy choices, not derived from data.
- Do **not** claim the reproducibility guarantee extends to analyst
  reasoning or hypothesis *content* being reproducible — only that
  hypothesis *objects* round-trip byte-identically; two analysts given
  the same evidence are not shown, or claimed, to reach the same
  hypotheses.
- Do **not** claim novelty for the tied-shortest-path enumeration
  algorithm itself — it is a standard, correctly-bounded application of
  known graph algorithms.
- Do **not** claim cross-machine/cross-OS/cross-Python-version
  determinism has been verified — it is asserted by design and untested
  outside a single CI environment (Ubuntu, Python 3.11) today.

## 19. Required engineering changes to run a meaningful experiment

Only what is needed to execute §13/§14, nothing invented beyond it:

- A benchmark fixture set (new files under `tests/fixtures/benchmark/` or
  `examples/`): synthetic raw evidence plus a ground-truth `expected.json`
  per case, in the same synthetic-data style `SECURITY.md` already
  requires for existing fixtures. This is data, not a code change to
  `src/`.
- A benchmark runner script (e.g. `scripts/wg_bench.py`, or a new
  `tests/` module) that drives the existing CLI/service layer end-to-end
  per fixture and diffs actual JSON output against `expected.json`,
  reporting precision/recall per capability. This uses only existing,
  already-shipped `--format json` output — no new API surface.
- A CI matrix extension (OS × Python-minor-version) to actually measure
  Experiment 2's cross-environment determinism claim, reusing GitHub
  Actions' existing `strategy.matrix` feature — a CI configuration
  change, not a source-code change.

No changes to `core/`, `correlate/`, `store/`, `service/`, `api/`, or
`frontend/` are required to run either proposed experiment; both operate
entirely through already-shipped, already-tested public surfaces.

## 20. Recommended next milestone

**A. Research experiment.**

Justification: the codebase is functionally complete and stable for this
purpose (804 passing tests; the v0.1 core object model has been locked
and unchanged since its introduction; every feature since has been
additive) — there is no missing engine capability blocking the proposed
experiments, since `graph paths --explain` and
`analyze_paths_evidence_overlap` (the object of study) already exist and
are already exposed as JSON. UI hardening is explicitly out of scope for
this review and not research-relevant regardless. An architecture change
would be premature and unjustified: it would mean investing further
engineering effort into a feature (§5, §11) whose actual research value
has not yet been empirically demonstrated on any ground-truth benchmark.
The single highest-value next step is building the WG-Bench harness and
fixtures (§14, §19) and running Experiment 1 (§13) — a real research
contribution claim requires evidence that the evidence-independence
mechanism produces useful, correctly-bounded signal (and evidence of
*where exactly it breaks*, per the falsifying-result design in §13),
and that evidence does not exist yet. This is also the cheapest possible
next step (test fixtures and a runner script, no production code), which
further favors doing it before committing to any additional engine
capability or architecture investment whose justification currently
rests on an unverified premise.
