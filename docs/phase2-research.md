# Witnessgraph Phase 2 — Research & Design Report

Status: research/design only. No code written. Not committed (this file is
untracked — see `git status` note at the end).

## 1. Ecosystem comparison

For each tool: workflow solved · evidence/data model · provenance/audit ·
timeline/correlation · hypothesis/inference handling · export/portability
· extension model · overlap with Witnessgraph · where Witnessgraph could
differentiate.

### Timesketch (+ Plaso)

- **Workflow**: collaborative, web-based forensic *timeline* analysis.
  Plaso (`log2timeline`) extracts timestamped events from disk
  images/files into a `.plaso` storage file; Timesketch ingests that (or
  KAPE/Velociraptor/Sysmon/CSV output) into OpenSearch for a team to
  search, tag, and annotate together.
- **Evidence/data model**: a flat, very large timeline of discrete
  "events" (one row per parsed artifact record), indexed for full-text
  search. No first-class notion of an "Entity" distinct from an event's
  fields.
- **Provenance/audit**: real, and non-trivial — the `.plaso` storage file
  records acquisition metadata (parameters, source, preprocessing) and
  `pinfo` lets an analyst inspect it. This is a genuine strength; Plaso's
  provenance story for *parsing* is more mature than Witnessgraph's v0.1
  (which only has three simple adapters).
- **Timeline/correlation**: this is Timesketch's core strength —
  full-text search, saved searches, sketches, tagging, and analyzer
  plugins across millions of events, at a scale Witnessgraph does not
  attempt.
- **Hypothesis/inference**: none as a structured type. Analysts annotate
  events with comments/tags/stars; there is no object representing "a
  claim that must cite evidence," and no distinction is enforced between
  an observed event and an analyst's interpretation of it — both live as
  free-text annotations on the same event.
- **Export/portability/reproducibility**: a case is effectively an
  OpenSearch index plus a Postgres metadata DB — not a single portable,
  hashable artifact. There is no cryptographic manifest that proves two
  copies of a "sketch" are byte-for-byte identical after an export/import
  round trip.
- **Extension model**: Timesketch has an analyzer plugin framework
  (Python, runs against the OpenSearch index); Plaso has a mature parser
  plugin ecosystem for many hundreds of artifact types.
- **Overlap with Witnessgraph**: both ingest heterogeneous forensic
  sources into a normalized timeline.
- **Where Witnessgraph could differentiate**: (a) a single, portable,
  cryptographically-verifiable case file vs. a server-side search index;
  (b) hypothesis as a distinct, evidence-citing object type, not a
  free-text tag; (c) explicit disagreement between conflicting timestamp
  claims (Witnessgraph's `TimeAssertion`) instead of one flattened
  timeline. Witnessgraph should **not** try to compete on parser breadth
  or search-at-scale — Plaso/Timesketch are far ahead there and this
  would not be a real gap, it would be reinventing a solved problem
  worse.

### OpenCTI / MISP

- **Workflow**: cyber threat intelligence (CTI) management — collecting,
  correlating, and sharing indicators/threat actor/campaign knowledge
  across organizations, not primarily single-incident evidence
  investigation.
- **Evidence/data model**: STIX 2.1 objects (OpenCTI) or the MISP
  event/attribute model, both oriented around *indicators and
  relationships between intelligence objects*, not raw, immutable,
  content-addressed evidence blobs from a specific incident.
- **Provenance/audit**: MISP-STIX conversion uses deterministic UUID
  generation for reproducible output, and a fingerprinting system links
  STIX Indicators to Observables to avoid duplicate representations of
  the same fact — a real, specific reproducibility property, but scoped
  to *intelligence-object identity*, not to "this exact case is
  byte-reproducible from this exact evidence."
- **Timeline/correlation**: relationship-graph correlation between
  intelligence objects (actor → malware → campaign → indicator), not a
  chronological event timeline of what happened on a specific host/case.
- **Hypothesis/inference**: STIX has a `confidence` field and
  relationship objects, but nothing structurally equivalent to
  Witnessgraph's `Hypothesis` (an object that *must* cite specific
  evidence and is typed separately from what it claims about).
- **Export/portability/reproducibility**: strong for *sharing threat
  intel* (STIX/TAXII is the industry standard for this) — genuinely
  ahead of Witnessgraph in interoperability with other CTI tooling. Not
  designed for "reproduce this specific incident investigation from
  scratch."
- **Extension model**: both have mature connector/import-export
  ecosystems (OpenCTI connectors, MISP modules).
- **Overlap with Witnessgraph**: both care about evidence hashing and
  reproducible identifiers to some degree.
- **Where Witnessgraph could differentiate**: Witnessgraph is
  incident/case-centric (one investigation, one portable file) rather
  than intelligence-sharing-centric (a shared, growing knowledge base
  across orgs). These are different problems; Witnessgraph should not
  try to be a CTI platform. A plausible, honest differentiator: STIX
  bundles can *cite* sources but nothing forces every claim to be
  evidence-backed the way Witnessgraph's `Hypothesis` validator does.

### TheHive / Cortex

- **Workflow**: SOC case management — alerts become cases, cases have
  tasks and observables, Cortex runs ~150 analyzers (VirusTotal, MISP
  lookups, sandbox detonation, etc.) against observables and feeds
  verdicts back.
- **Evidence/data model**: "observables" (IP, domain, hash, email, URL,
  file) attached to a case, each with a TLP marking and an `is-IOC` flag.
  Very close in spirit to an "Entity," but not immutable/content-addressed
  in the way Witnessgraph's `EvidenceItem` is.
- **Provenance/audit**: case/task/observable history is tracked in
  Elasticsearch, but there is no published cryptographic-manifest
  reproducibility guarantee comparable to Witnessgraph's `replay`.
- **Timeline/correlation**: case-centric task/observable tracking, not a
  dedicated multi-source timestamp-correlation engine (that's Timesketch's
  job, and organizations often run both).
- **Hypothesis/inference**: Cortex analyzer "verdicts" (malicious/clean)
  feed case severity — this is automated *inference*, but it is not
  represented as a citable, evidence-linked claim object; it is a
  taxonomy tag attached to an observable.
- **Export/portability/reproducibility**: case data lives in
  Elasticsearch; no single portable, hashable case-file format was found
  in the documentation.
- **Extension model**: Cortex's analyzer/responder plugin architecture is
  mature and directly comparable in spirit to Witnessgraph's
  `EvidenceAdapter` protocol, just for a different stage of the workflow
  (enrichment/response vs. ingestion/normalization).
- **Overlap with Witnessgraph**: both have a pluggable "run something
  against this piece of evidence" extension point.
- **Where Witnessgraph could differentiate**: TheHive/Cortex is
  fundamentally a SOC triage/response workflow tool (with live
  enrichment lookups against external services) — that is explicitly
  out of scope for Witnessgraph (no network calls). The honest
  differentiator is narrower: Witnessgraph's evidence objects are
  immutable and content-addressed from the moment of ingestion, and its
  case format is a single file with a verifiable hash, vs. TheHive's
  live, server-backed case database.

### Velociraptor

- **Workflow**: live endpoint visibility, remote forensic artifact
  collection, and threat hunting via VQL (Velociraptor Query Language)
  queries pushed to deployed endpoint agents.
- **Evidence/data model**: YAML-defined "artifacts" packaging VQL queries
  that collect structured rows (registry hives, MFT, prefetch, process
  memory, etc.) from a live or dead endpoint.
- **Provenance/audit**: documented "automated evidence preservation with
  chain-of-custody metadata" and on-host join/chaining between artifacts
  — a real, mature provenance story for *collection*, arguably stronger
  than Witnessgraph's v0.1 in this dimension since it's purpose-built for
  live acquisition.
- **Timeline/correlation**: supports on-host correlation via chained VQL
  artifacts, not a dedicated cross-case timeline UI (that's typically
  handed off to Timesketch downstream).
- **Hypothesis/inference**: none as a structured object — VQL results are
  raw collected data for a human or downstream tool to interpret.
- **Export/portability/reproducibility**: VQL queries and artifact
  definitions are versionable/shareable YAML (genuinely reproducible *as
  a collection procedure*), but the collected *results* are not packaged
  into Witnessgraph's kind of single-hash-verifiable portable case file.
- **Extension model**: the YAML artifact system is explicitly designed
  for community-contributed, self-documenting collection procedures —
  a strong, mature plugin ecosystem.
- **Overlap with Witnessgraph**: near zero at the collection layer —
  Velociraptor *actively collects* from live endpoints, which
  Witnessgraph's DESIGN.md/SECURITY.md explicitly and deliberately
  excludes.
- **Where Witnessgraph could differentiate**: none at the collection
  layer (out of scope by design). A legitimate downstream role:
  Witnessgraph could one day *ingest* Velociraptor's exported artifact
  results as evidence (a future adapter), the same way Timesketch
  ingests Velociraptor output today — that is a v0.3+ idea, not Phase 2.

### Other relevant tools (briefly)

- **STIX/TAXII** (as a format, not a platform): a shared serialization
  MISP/OpenCTI both speak. Not a competitor to Witnessgraph; a plausible
  future *export target* for interoperability, not a Phase 2 concern.
- **Cartography**: builds an infrastructure/asset relationship graph
  (cloud accounts, IAM, network) into Neo4j for attack-surface analysis.
  Different problem (asset graphing, not case-based evidence
  investigation) and explicitly the kind of graph-database dependency
  Witnessgraph's v0.1 DESIGN.md rules out — no meaningful overlap.
- **GRR Rapid Response**: similar live-agent model to Velociraptor
  (Google-originated); same "out of scope, live collection" reasoning
  applies.
- **Autopsy/Sleuth Kit**: disk-image-centric forensic examination
  (file carving, artifact parsing from an image) — a different layer
  (raw image → artifacts) than Witnessgraph, which starts one step later
  (already-extracted evidence files → case). No meaningful overlap to
  claim.

### Honest summary of the gap

No tool surveyed combines all of: (1) a single, portable, offline case
file, (2) a cryptographically verifiable reproducibility guarantee for
that *whole case* (not just individual object identifiers), and (3) a
structural, enforced type-level separation between observed evidence and
analyst inference. Plaso/Velociraptor have strong provenance *for
collection*. MISP-STIX has strong reproducibility *for intelligence
object identity*. None of them make "can this specific investigation
be independently reconstructed and verified, evidence and reasoning
kept visibly separate" the central, enforced property of the format
itself. This is a real, narrow, honestly-earned gap — not the general
DFIR workflow, which several of these tools already do better than
Witnessgraph ever should try to.

## 2. Three candidate Witnessgraph workflows

### Candidate A — "Portable incident case with independently reproducible conclusions"

1. **Real researcher problem**: a DFIR analyst wants to hand off (or
   publish, e.g. in a writeup/CTF/vendor report) a small incident's
   evidence *and* their reasoning in one artifact that a second party can
   independently verify was not altered and can re-derive the same
   conclusions from the same evidence.
2. **Inputs**: a handful of already-collected log files (auth logs,
   process logs, a CSV timeline export from some other tool) — no live
   collection.
3. **Evidence transformations**: ingest via existing JSONL/CSV/syslog
   adapters → normalized events → (new in Phase 2) entity extraction
   linking events to hosts/users/processes → timeline.
4. **Entities/events/timestamps**: hosts, users, processes; logon,
   process-start, network-connect events; `TimeAssertion`s per event,
   including surfacing any that disagree.
5. **Hypothesis/inference workflow**: analyst proposes 1+ hypotheses
   citing specific evidence, supports/contradicts them as investigation
   proceeds — this already works in v0.1.
6. **Contradiction/missing-evidence behavior**: existing structural
   `TimeAssertion` contradiction detection; a new "evidence coverage gap"
   report (e.g. a time range with no evidence at all) would be new work.
7. **Provenance guarantees**: already proven in v0.1 — content-addressed
   evidence, reproducible manifest hash, verified export/import/replay.
8. **Reproducibility test**: export the case, hand the `.wgcase` file to
   a second person/machine, they run `witnessgraph replay` and get the
   identical manifest hash — **already works today**, end to end.
9. **Expected researcher output**: a `.wgcase` file plus a human-readable
   summary (new: a `witnessgraph report` command rendering the timeline +
   hypotheses + contradictions as Markdown/HTML for sharing).
10. **Existing tools that already solve it**: none solve the "verifiably
    reproducible case handoff" property; Timesketch/TheHive solve the
    "collaborative investigation" part better today.
11. **What Witnessgraph uniquely adds**: the reproducibility guarantee
    itself, demonstrated end-to-end on a realistic (if small) multi-source
    case, plus a human-readable rendering of the evidence/inference
    separation.
12. **Implementation complexity**: **low-to-medium**. Mostly a new
    read-only `report` command over existing data, plus optional
    lightweight entity-extraction helpers. No new storage, no schema
    changes required for the core loop (though a small one is proposed
    below for entity/event linking quality).
13. **Security/privacy risks**: none new — still local-only, no network
    calls; the `report` output could leak sensitive evidence content into
    a shared file, which needs the same disclosure `SECURITY.md` already
    gives for `.wgcase` exports.

### Candidate B — "Multi-source contradiction and gap detection for a single incident"

1. **Real researcher problem**: when merging logs from several
   independently-clocked/independently-collected sources (e.g. a
   firewall log and a host log for the same incident), analysts need to
   know *where the sources disagree or where coverage is missing*, not
   just get a merged timeline that silently picks one version of events.
2. **Inputs**: 2+ log sources covering overlapping time windows for the
   same incident, with realistic clock skew/log-rotation-induced gaps.
3. **Evidence transformations**: ingest each source → normalized events →
   `TimeAssertion`s per event → contradiction detection across the full
   set (already exists) → **new**: a "coverage gap" detector that flags
   time windows where one source has events and another expected-to-
   overlap source has none.
4. **Entities/events/timestamps**: same shape as Candidate A but the
   emphasis is entirely on the `TimeAssertion` layer and cross-source
   disagreement, not on entity/hypothesis richness.
5. **Hypothesis/inference workflow**: secondary in this candidate —
   contradictions/gaps are the primary output, hypotheses are optional.
6. **Contradiction/missing-evidence behavior**: this **is** the
   candidate's core deliverable — needs a genuinely new "gap" detector
   (not just the existing pairwise time-disagreement check).
7. **Provenance guarantees**: same as v0.1, unchanged.
8. **Reproducibility test**: same contradiction/gap report must be
   byte-identical across independent runs on the same case (this is
   actually a slightly *weaker* test than Candidate A's, since gap/
   contradiction reports are derived, not the manifest hash itself,
   unless the report's own content is added to the manifest).
9. **Expected researcher output**: a structured
   contradictions-and-gaps report.
10. **Existing tools that already solve it**: Timesketch's
    saved-search/tagging workflow can approximate this manually, but
    does not have a structural, automatic "no evidence exists in this
    window from source X" detector as a first-class feature, as far as
    could be confirmed from documentation.
11. **What Witnessgraph uniquely adds**: genuinely useful, narrow, and
    novel — but it is a smaller, more specialized slice of value than
    Candidate A, and by itself doesn't demonstrate the reproducibility
    thesis as directly (the interesting output here is analytical, not
    provenance-centric).
12. **Implementation complexity**: **medium** — the gap detector needs
    real design work (what counts as "expected overlap" between two
    sources is not obvious and risks false positives/negatives that
    would need careful, conservative heuristics to avoid overclaiming).
13. **Security/privacy risks**: none new beyond Candidate A.

### Candidate C — "Case comparison / diffing between two investigation states"

1. **Real researcher problem**: an analyst wants to know exactly what
   changed between two versions of the same case (e.g. before and after
   a second analyst added evidence or revised a hypothesis) — useful for
   peer review, or for detecting if a case file was tampered with beyond
   simple hash mismatch (i.e., *what* changed, not just *that* something
   changed).
2. **Inputs**: two `.wgcase` exports of what's nominally "the same"
   investigation at different points in time.
3. **Evidence transformations**: import both, diff their manifests
   object-by-object (which evidence/events/entities/hypotheses are
   added/removed/changed).
4. **Entities/events/timestamps**: all object types, diffed by id.
5. **Hypothesis/inference workflow**: diffing would highlight hypothesis
   status changes (proposed → supported) as a first-class diffable
   thing — a genuinely nice property given hypotheses are typed
   distinctly already.
6. **Contradiction/missing-evidence behavior**: not this candidate's
   focus.
7. **Provenance guarantees**: directly exercises and demonstrates the
   manifest's structure (a diff *is* a manifest comparison), which is a
   nice showcase of the existing hashing work, but doesn't add a new
   provenance guarantee itself.
8. **Reproducibility test**: diffing two identical cases must report zero
   differences; diffing a case against an intentionally-modified copy
   must report exactly the modified objects.
9. **Expected researcher output**: a structured diff report.
10. **Existing tools that already solve it**: nothing directly comparable
    was found — this is a genuinely underexplored niche, but also a
    genuinely niche one; it's most useful in a multi-analyst or
    peer-review setting Witnessgraph doesn't otherwise support yet
    (no multi-user features exist or are planned for v0.2).
11. **What Witnessgraph uniquely adds**: a real capability, but it's
    solving a *process* problem (peer review / change tracking) more than
    a *core investigation* problem, and its value is muted until
    Witnessgraph has some multi-analyst or multi-session story, which is
    explicitly not planned yet.
12. **Implementation complexity**: **low-to-medium** technically (mostly
    set comparison over two manifests), but its value proposition is the
    weakest of the three right now given the single-analyst, v0.1-only
    context.
13. **Security/privacy risks**: none new.

## 3. Recommended workflow

**Candidate A — "Portable incident case with independently reproducible
conclusions."**

Checked against all six of the user's explicit constraints:

- **Builds directly on existing v0.1 architecture**: yes — it is
  substantially the *existing* ingest → timeline → hypothesis → export →
  import → replay pipeline, already fully implemented and proven, plus
  one new read-only rendering command and one small, additive data-model
  improvement (below).
- **Requires minimal new infrastructure**: yes — no new storage backend,
  no new service, no new external dependency beyond what a Markdown/HTML
  renderer needs (the standard library is sufficient).
- **Useful without AI**: yes — entirely mechanical rendering of
  already-structured, human-authored data.
- **Avoids live collection/network scanning/exploitation**: yes,
  trivially — it's a read/render step over an existing local case.
- **Demonstrates the evidence/provenance thesis clearly**: yes, this is
  the candidate most directly *about* the thesis — "hand someone a case
  and they can verify it and see your reasoning" is the closest possible
  restatement of "investigations should be reproducible from evidence."
- **Produces something researchers could actually inspect/share/
  reproduce**: yes, directly — a shareable case file plus a
  human-readable report, with a concrete, testable reproducibility
  claim.

Candidate B is a strong secondary and genuinely differentiated, but its
core deliverable (a well-designed gap detector) is riskier and less
proven than Candidate A's mostly-already-working pipeline, and it
demonstrates the *analytical* value more than the *reproducibility*
thesis specifically. Candidate C is real but currently low-value given
the single-analyst v0.1 context — better revisited once there's a
multi-session/multi-analyst story to make it matter.

## 4. NormalizedEvent/TimeAssertion re-ingest duplication — blocking or follow-up?

**Decision: does NOT block Phase 2. Treat as a separate, tracked
follow-up.**

Justification: Candidate A's workflow is a **fresh-case workflow** —
`init` → `ingest` (once, cleanly, per source) → `hypothesis` → `export`
→ `import` → `replay`/`report`. It does not involve re-running an
interrupted ingest against a partially-populated case, which is exactly
and only the scenario the known limitation affects (per `SECURITY.md`:
"if an ingest is interrupted, the safest recovery today is to discard
the partial case directory and start over from an empty one"). As long
as the Phase 2 example/demo case is built the documented safe way (clean
ingest runs, not resumed ones), the limitation is inert for this
workflow. It should remain visibly tracked (already is, in
`SECURITY.md`) and should be fixed before any future workflow that
specifically involves incremental/resumable ingestion — which is not
what Candidate A needs.

## 5. Proposed v0.2 scope

- A new **`witnessgraph report <case>`** CLI command: renders a case's
  timeline, entities, hypotheses (with their cited evidence and
  status), and any detected contradictions as a single, self-contained
  Markdown document (an HTML variant is a nice-to-have, not required).
  No AI, no summarization — pure, deterministic templating over
  already-structured data, so the report itself remains something whose
  content is fully explained by the case's own manifest.
- A small **entity-linking convenience layer**: today entities must be
  created and linked to evidence manually via the CLI/library. Add a
  thin, opt-in helper (not automatic, not ML-based) that lets an analyst
  declare "these attribute values across these normalized events refer
  to the same entity" more easily than hand-writing `derived_from` lists
  — e.g. a `witnessgraph entities link-by-attribute <case> <event_type>
  <attribute>` command that creates/updates one `Entity` per distinct
  attribute value it finds, with full lineage back to the specific
  events. This remains deterministic, auditable, and explicitly
  human-triggered (an analyst decides which attribute means "same
  entity"), so it doesn't cross into "automatic entity resolution,"
  which is out of scope.
- **Worked example v2**: extend `examples/sample-case/` (or add a
  second, slightly richer example) demonstrating the full Candidate A
  loop including the new `report` output, still fully synthetic.
- A one-line addition to the provenance manifest computation (or a
  documented decision *not* to include it) about whether the rendered
  report's content is itself covered by the manifest hash — needs an
  explicit design decision (see open questions) before implementation.

## 6. Explicit non-goals for v0.2

- No AI/LLM involvement anywhere, including in the new `report` command
  — it is a deterministic template, not a summarizer.
- No automatic/ML-based entity resolution — the new linking helper is
  explicitly a human-declared operation.
- No web UI or server — `report` output is a static file.
- No graph database.
- No live evidence collection, network calls, or scanning of any kind.
- No multi-user/auth/collaboration features (this rules out Candidate C
  for now, as noted above).
- No fix to the NormalizedEvent/TimeAssertion re-ingest duplication issue
  in this milestone (tracked separately, per section 4).
- No new adapters beyond what's needed to make the v0.2 example
  realistic (i.e., don't scope-creep into a fourth ingestion format
  unless the example genuinely needs it).

## 7. Architecture changes required

Minimal. The `report` command is a new, thin module (e.g.
`src/witnessgraph/report/`) that only *reads* from the existing `Store`
protocol — no interface changes needed there. The entity-linking helper
is a new function in `src/witnessgraph/ingest/` or a new
`src/witnessgraph/entities/` module, again only using existing
`Store`/`Case` read/write operations. No changes to `Store`/`BlobStore`
protocols, no changes to the CLI's overall structure beyond adding two
new subcommands (`report`, `entities link-by-attribute`).

## 8. Data-model changes required

One small, additive, backward-compatible change worth considering (not
strictly required, but improves Candidate A's output quality):
`Entity` currently has no explicit "kind" beyond what's implied by its
`identifiers` dict — for a good `report` output it would help to have a
lightweight, optional `display_label` or reuse of an existing
`entity_type`-equivalent field (needs checking the exact current
`Entity` shape before deciding — this is a design detail to resolve
during implementation, not now). No changes to `EvidenceItem`,
`NormalizedEvent`, `Hypothesis`, or `TimeAssertion` are needed for
Candidate A.

## 9. Test strategy

- Golden-output test for `witnessgraph report`: run it against the
  existing (or an extended) synthetic sample case, commit the expected
  Markdown output as a fixture, assert byte-identical output — this
  mirrors the project's existing golden-sample-case testing pattern.
- Determinism test: run `report` twice against the same case, assert
  identical output (no wall-clock-dependent content like "generated at
  <now>" unless explicitly and separately parameterized out of the
  diffable portion).
- Unit tests for the entity-linking helper: given normalized events with
  a shared attribute value, assert exactly one `Entity` is created with
  correct `derived_from` lineage to all matching events; assert it is a
  no-op (or correctly extends lineage, not duplicates) on a second run
  over the same input — this explicitly must not reintroduce a
  duplication bug of the same shape as the known NormalizedEvent/
  TimeAssertion issue.
- End-to-end reproducibility test extended to cover the full Candidate A
  loop including `report`: ingest → entities (new helper) → hypothesis →
  export → import → `report` on both copies → assert identical report
  content, not just identical manifest hash.

## 10. Acceptance criteria

- `witnessgraph report <case>` runs against the v0.2 example case and
  produces a Markdown document a human can read and understand without
  needing the CLI, showing: evidence sources, timeline, entities,
  hypotheses with their cited evidence and status, and any detected
  contradictions.
- The report's content is provably deterministic (test in section 9
  passes).
- Export → import → `report` on the imported copy produces identical
  report output to the original (demonstrating the reproducibility
  thesis end-to-end, not just at the manifest-hash level).
- The new entity-linking helper is fully covered by unit tests including
  a no-duplication-on-rerun test.
- All existing v0.1 tests (78) continue to pass; `ruff`/`mypy --strict`
  remain clean.
- No new runtime dependency beyond the Python standard library, unless a
  templating library is judged clearly worth it (to be decided at
  implementation time, not assumed now).

## 11. Risks / open questions

- **Should the report's rendered content be covered by the provenance
  manifest hash?** Two defensible positions: (a) no, the manifest covers
  the case's *data*, not a derived rendering of it, so the report can
  regenerate deterministically from a manifest-verified case without
  itself being hashed into that manifest; (b) yes, if the report is
  meant to be the artifact a third party actually reads and trusts, its
  exact content should be independently verifiable too. Recommend (a)
  for v0.2 — keep the manifest scoped to source-of-truth data, and rely
  on the *determinism test* (not manifest inclusion) to prove the report
  is faithful — but this is a real design decision to make explicitly
  before implementation, not silently default into.
- **Entity-linking helper scope creep risk**: "let an analyst declare
  matching attributes" is easy to describe but the exact CLI ergonomics
  (fuzzy matching? case sensitivity? multiple attributes at once?) could
  balloon; the v0.2 implementation should stay deliberately narrow
  (exact-match on one attribute at a time) and explicitly defer anything
  fancier.
- **Report format bikeshedding**: Markdown vs. HTML vs. both — recommend
  Markdown-only for v0.2 (renders fine on GitHub/most viewers, trivially
  diffable, no new dependency), explicitly defer HTML.
- **The ecosystem research here is necessarily a point-in-time snapshot**
  (tool capabilities, especially in the fast-moving CTI-platform space,
  change) — worth a lightweight re-check before any public positioning
  of Witnessgraph against these tools, not just before writing code.
