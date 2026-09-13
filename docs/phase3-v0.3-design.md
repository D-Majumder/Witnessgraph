# Witnessgraph v0.3 Design — Content-Addressed Derived Objects & Transactional Ingestion

Status: **design-only. No implementation exists yet.** This document is
research and design for a future implementation phase; nothing in this
document has been built, and no source file, test file, schema, or
configuration file has been changed to produce it.

## 1. Problem statement

Two related, previously-documented limitations sit at the center of
Witnessgraph's remaining reproducibility gap:

1. `NormalizedEvent` and `TimeAssertion` ids are randomly generated
   (`uuid.uuid4()` via `new_object_id()`), not derived from the content
   they represent. Re-running ingestion over a source that was already
   (fully or partially) ingested creates **new, duplicate** objects for
   the same underlying observation, rather than converging back to the
   same object.
2. Ingestion is not crash-atomic: each `put_*` call to `SqliteStore` is
   committed individually, so a process killed mid-ingest leaves a
   **genuinely partial** case — some records written, the rest silently
   absent, with no transactional boundary to make that all-or-nothing.

Empirically confirmed against the current repository (`../examples/sample-case/data/events.jsonl`,
ingested twice into the same case via the real library code, nothing
about this test was hypothetical):

```
after run 1: evidence=4 events=4 time_assertions=4
after run 2 (re-ingest same file): evidence=4 events=8 time_assertions=8
```

`EvidenceItem` count stayed at 4 (already content-addressed, already
deduplicated and merged, exactly as designed). `NormalizedEvent` and
`TimeAssertion` counts **doubled**. This is not a hypothetical risk; it
is the current, actual behavior of `witnessgraph ingest` run twice.

A second, previously **undocumented** finding, discovered during this
research pass by direct inspection of `core/provenance.py` and
confirmed empirically:

```
same file, ingested at two different wall-clock times (fresh cases):
manifest hash (t=2026-01-01): 72ffa4b4...
manifest hash (t=2026-03-01): c2288d09...
IDENTICAL? False
```

`compute_manifest()` hashes the **entire serialized object** for
`NormalizedEvent`/`Entity`/`TimeAssertion`/`Hypothesis` (via
`content_hash_of()`), and `NormalizedEvent.created_at` /
`TimeAssertion.created_at` are set to the ingest-time wall clock
(`datetime.now(UTC)`, passed in as `collected_at` from
`cli/main.py`'s `ingest` command). Two otherwise-identical ingestions
of the same file, run at two different times, currently produce two
different manifest hashes for logically identical cases. This is a more
fundamental reproducibility defect than the duplication issue and must
be addressed by the same design, or the "reproducible ingestion" goal
is not actually met even after fixing duplication.

## 2. Current architecture findings

Derived directly from the repository (not from memory of prior
sessions):

- **`EvidenceItem`** (`core/evidence.py`): `id == raw_content_hash =
  sha256_hex(raw_bytes)`. Content-addressed by construction via
  `EvidenceItem.create(...)`. `chain_of_custody` is explicitly excluded
  from identity and from the manifest (manifest uses `e.raw_content_hash`
  directly, not a full-object hash — see `core/provenance.py`).
  `SqliteStore.put_evidence` merges: on an id collision, it keeps the
  first-known `source_locator`/`collected_at`, and appends only
  genuinely new custody records (by value). This exact pattern is
  already tested (`tests/unit/test_store.py::test_duplicate_content_from_different_sources_preserves_both_provenance`,
  `test_reingesting_same_source_does_not_duplicate_custody`).
- **`NormalizedEvent`** (`core/events.py`): `id: str =
  Field(default_factory=new_object_id)` — a fresh random UUID on every
  construction. `derived_from` (non-empty, validated) references the
  `EvidenceItem` id(s) it came from. `created_at` is passed in from the
  caller — in practice, always the ingest-time wall clock
  (`ingest/pipeline.py`'s `ingest_source` passes its own `collected_at`
  argument straight through). `entity_ids` defaults to an empty tuple
  and is never populated by any adapter or CLI command in v0.1/v0.2 —
  there is no code path that mutates it after construction.
- **`TimeAssertion`** (`core/time_model.py`): `id` is also
  `new_object_id()`-random. `subject_event_id`, `value`, `precision`,
  `source_evidence_id`, `asserted_by` are all deterministic functions of
  the evidence being normalized; `created_at` is set to
  `evidence.collected_at` (`ingest/pipeline.py::_derive_time_assertion`)
  — the same ingest-time wall clock, again.
- **`Entity`** (`core/entities.py`) and **`Hypothesis`**
  (`core/hypothesis.py`): both `new_object_id()`-random ids. Neither is
  produced automatically by any adapter; both require an explicit,
  human-triggered CLI call (`entities create`, `hypothesis propose`).
  v0.2's specification explicitly ruled out automatic entity linking.
- **SQLite schema** (`store/sqlite_store.py`): five tables, all
  `CREATE TABLE IF NOT EXISTS <name> (id TEXT PRIMARY KEY, data TEXT NOT NULL)`.
  The **table DDL carries no information about the Pydantic model's
  fields** — the entire object is opaque JSON in the `data` column.
  This matters directly for §13/§16 below.
- **Transactions**: `sqlite3.connect()` is opened with the driver's
  default isolation level. Every `put_evidence`/`put_normalized_event`/
  `put_entity`/`put_time_assertion`/`put_hypothesis` call issues its own
  `execute()` followed immediately by its own `commit()`. There is no
  `BEGIN`/transaction boundary spanning more than one row write anywhere
  in the codebase. This is exactly what `SECURITY.md`'s documented
  "ingestion is not crash-atomic" limitation describes, and it is the
  literal, direct cause of the atomicity gap — confirmed by reading the
  code, not inferred.
- **`put_normalized_event`/`put_time_assertion`/`put_entity`/
  `put_hypothesis`** all use `INSERT OR REPLACE INTO ... VALUES (?, ?)`.
  Because ids are currently random, a collision is never expected to
  occur except for `Hypothesis`'s intentional status-update pattern
  (`with_status()` reuses the same id) — `INSERT OR REPLACE` is
  effectively "insert new row" in every other case today.
- **`compute_manifest()`** (`core/provenance.py`): for `EvidenceItem`,
  the per-item contribution is `e.raw_content_hash` (== `e.id`) — the
  *only* type where the manifest doesn't hash the full object. For the
  other four types, it is `content_hash_of(obj)` = SHA-256 of the
  object's *entire* canonical JSON dump, `created_at` included.
- **`replay_and_verify`** (`replay/replay.py`): recomputes the manifest
  from the live evidence graph and compares it to the recorded one.
  Unaffected by object *count* except through the manifest hash; a
  duplicated `NormalizedEvent` changes the manifest (a new id enters the
  `normalized_events` collection hash), so `replay`/`verify` would
  correctly report the duplication as a manifest change — but nothing
  currently *prevents* the duplication from happening in the first
  place.
- **`export_case`/`import_case`** (`portable.py`): package/restore the
  whole case directory (SQLite file + blobs) verbatim; they do not
  interpret or migrate the JSON payloads inside `data` columns at all —
  confirmed by reading the full module (10 lines of actual logic, no
  schema-awareness whatsoever).
- **`witnessgraph report`/`verify`** (`report/render.py`, `cli/main.py`,
  v0.2): read-only projections over `Store` + `ProvenanceManifest`. A
  duplicated `NormalizedEvent` from a re-run ingest would today render
  as two separate, indistinguishable-looking Timeline entries in the
  report — a second, concrete symptom of the same root cause, on top of
  the manifest-hash effect already noted.
- **`SourceDescriptor`** (`ingest/base.py`): `path: Path`,
  `kind_hint: str | None`. No offset, no cursor, no "already processed
  up to line N" concept exists anywhere in the ingestion path today.
- **`FileBlobStore` is never written to during ingestion — newly
  discovered, confirmed by direct inspection.** `Case.__init__`
  constructs `self.blobs = FileBlobStore(root / "blobs")`, and
  `FileBlobStore.put()` is fully implemented and unit-tested
  (`tests/unit/test_store.py`), but **`ingest_source()` never calls
  `case.blobs.put(...)` anywhere** — confirmed by reading the complete
  `ingest/pipeline.py` (56 lines) and grepping the entire `src/` tree
  for `blobs.put`/`blobs.get`/`blobs.has`: the only call sites are in
  unit tests exercising `FileBlobStore` in isolation. `EvidenceItem.id`/
  `raw_content_hash` are computed from `raw_bytes` for hashing purposes
  only; the raw bytes themselves are **not persisted anywhere** by the
  actual ingest path today. This directly contradicts `DESIGN.md`
  principle 1 ("Blob storage... never overwrites an existing file at a
  content address" — implying blobs are populated) and `SECURITY.md`
  ("that file's contents will be stored verbatim in the case's blob
  store"), both of which describe a behavior the code does not
  currently exhibit. This is a real, previously-undocumented gap
  between documentation and implementation, not a design concern this
  document invented — see §3 item 5 and the new decision point in
  §6.7.

## 3. Current failure modes (concrete, not hypothetical)

1. Re-running `witnessgraph ingest <case> <adapter> <source>` on a
   source already (fully or partially) ingested **duplicates every
   `NormalizedEvent` and `TimeAssertion`** derived from that source —
   empirically confirmed above. `EvidenceItem` does not duplicate.
2. A process killed between two `put_*` calls during a single ingest
   leaves a case containing some, but not all, of that source's records
   — no way to distinguish "this case is complete" from "this case was
   interrupted" except by re-running ingestion and manually reasoning
   about what might now be duplicated (compounding failure mode #1).
3. **Newly found**: re-ingesting the *same, unmodified* source at two
   different wall-clock times produces two different manifest hashes
   for two otherwise-identical cases, because `created_at` (ingest-time
   wall clock, not evidence content) is currently hashed as part of
   `NormalizedEvent`/`TimeAssertion` identity in the manifest.
4. A duplicated `NormalizedEvent` is invisible to a human reading
   `witnessgraph report` — it renders as a second, textually-identical
   Timeline entry with a different random id, with nothing in the
   report calling out that it is a duplicate rather than a second,
   independent observation.
5. **Newly found**: no case built by `witnessgraph ingest` today
   actually contains a durable, independently-hash-verifiable copy of
   its raw evidence bytes — only the `EvidenceItem` metadata record
   (including the claimed `raw_content_hash`) is persisted. A case
   directory's `blobs/` subdirectory is created (`FileBlobStore.__init__`
   makes the directory) but is never populated by ingestion. This means
   `EvidenceItem.raw_content_hash` is currently an unverifiable claim
   from the store's point of view — there is no stored blob to
   recompute the hash from and confirm it matches. This is materially
   relevant to "reproducible from evidence, not... opaque conclusions"
   (`README.md`'s own thesis statement) and is addressed as an explicit
   decision point in §6.7, not silently folded into the identity/
   atomicity work without your sign-off.

## 4. Definitions (kept deliberately distinct, per the review's own instruction not to collapse them)

- **Byte-identical raw evidence**: two ingestions of the same physical
  bytes produce the same `EvidenceItem.id` (SHA-256 of the bytes).
  Already true, unaffected by this design.
- **Deterministic normalized representation**: for a fixed
  `(raw evidence bytes, adapter, adapter_version)`, an adapter's
  `ingest()` must always produce the same `(event_type, attributes)`
  pair. Already true of the three built-in adapters (no adapter reads
  wall-clock time, randomness, or external state to decide these
  fields) — v0.3 makes this an explicit, load-bearing, testable
  invariant rather than an incidental property.
- **Deterministic IDs**: a derived object's id is a pure function of a
  defined subset of its own fields ("identity fields"), independent of
  *when* or *how many times* it was derived. **Not yet true** for
  `NormalizedEvent`/`TimeAssertion` — this is what v0.3 adds.
- **Deterministic ordering**: the order objects are rendered in
  (`witnessgraph report`) or compared in (manifest collection hashing)
  does not depend on insertion order. Already true (v0.2's explicit
  sorting; v0.1's collection-hash sorting by id) and unaffected by this
  design.
- **Deterministic derived assertions**: a `TimeAssertion`'s `value`/
  `precision` are a pure function of the evidence it was derived from.
  Already true (`_derive_time_assertion` has no randomness or
  wall-clock dependence in its *value*-deriving logic; only its
  `created_at` field is wall-clock-derived).
- **Deterministic reports**: `witnessgraph report` renders the same
  bytes for the same store state (v0.2, unaffected). What v0.3 changes
  is *what store state re-ingestion produces* — today, re-ingestion
  grows the store's `NormalizedEvent`/`TimeAssertion` collections
  without bound; after v0.3, it converges to a fixed point.

**"Reproducible ingestion" (precise definition adopted for v0.3):**
ingesting the same `(source bytes, adapter, adapter_version)` into a
case, any number of times, in any interleaving with itself, converges
to the same set of `EvidenceItem`/`NormalizedEvent`/`TimeAssertion`
*ids and content* in that case, and to the same manifest-hash
contribution from that source's records — independent of how many
times ingestion ran, whether a prior attempt was interrupted, or what
wall-clock time any attempt occurred at.

## 5. Alternatives considered

**A. Do nothing / documentation-only fix.** Keep random ids, just
document more prominently that re-ingest is unsafe. Rejected: the
problem statement explicitly asks for a real fix; a documentation-only
change does not advance "reproducible from evidence" in any measurable
way, and the empirical duplication is a real, current defect a user
will hit the first time they re-run a command after an interruption.

**B. Application-level deduplication pass** (a `witnessgraph dedupe`
command that finds and merges look-alike `NormalizedEvent`s after the
fact). Rejected: this treats a *design* defect as a *cleanup* problem,
requires inventing a similarity/equality heuristic (exactly the kind of
fuzzy-matching Witnessgraph has deliberately avoided — see v0.2's
explicit rejection of automatic entity linking), and does nothing for
the crash-atomicity half of the problem. It is also strictly more
complex than fixing identity at the source.

**C. Explicit resumable ingestion with checkpoints/offsets**
(`SourceDescriptor` gains a byte/line offset; adapters can resume
mid-file; a checkpoint table records progress). Rejected for v0.3: this
is a materially larger, stateful subsystem (new schema, new adapter
protocol surface, new failure modes of its own — e.g. a stale/corrupt
checkpoint) built to solve a problem that content-addressed ids +
per-ingest transactions already solve more simply: if re-running the
*entire* ingest from the start is safe and idempotent (which C alone
does not guarantee, but D below does), there is no need to resume from
a partial point — you just re-run the whole thing. Given Witnessgraph's
stated scale (a handful of already-collected log files per case, per
the v0.2 research), redoing the parsing work for an already-ingested
file is a cost measured in milliseconds-to-seconds, not a real
operational burden. Building checkpointing to avoid that cost would be
solving a performance problem the project doesn't have, at the expense
of a much larger surface area — directly the kind of "resumability
because it sounds useful" the review warns against.

**D. Content-addressed `NormalizedEvent`/`TimeAssertion` ids +
per-ingest-invocation SQLite transactions (chosen).** Makes id
collisions on re-derivation of the *same* logical object structurally
expected and safe (an `INSERT OR IGNORE`-shaped no-op, not a conflict
to resolve), and makes a single `witnessgraph ingest` invocation
all-or-nothing at the database level. Together, these two changes make
"just re-run the failed/interrupted command" the complete, correct
recovery procedure, with no new stateful subsystem. This is the
smallest change that fully closes both documented gaps.

**E. Full event-sourcing / append-only log architecture** (store every
ingest as an immutable event in a log, derive current state by replay).
Rejected as disproportionate: Witnessgraph already has an
append/merge-only custody model for `EvidenceItem`, and the "replay"
name is already used for the *manifest*-verification operation — a full
event-sourcing rewrite of the storage layer would be a genuine
architectural rewrite, not the "smallest robust" fix the brief asks
for, and would risk the exact "generic platform" dilution the product
principle explicitly warns against.

## 6. Recommended v0.3 architecture

1. **Content-address `NormalizedEvent` and `TimeAssertion`.** Give both
   a `.create(...)` classmethod (mirroring `EvidenceItem.create`) that
   computes `id` as a domain-separated SHA-256 hash of a fixed,
   documented subset of the object's own fields (§7) — explicitly
   *excluding* `created_at`. Direct, bare construction with an
   arbitrary `id` remains possible (as it is for every model today) for
   tests and edge cases, but every real ingest/pipeline code path uses
   `.create(...)`.
2. **Make derived-object storage idempotent, not merely
   collision-tolerant.** `SqliteStore.put_normalized_event` and
   `put_time_assertion` change from unconditional `INSERT OR REPLACE` to
   "insert if absent, otherwise no-op" (`INSERT OR IGNORE`, or an
   explicit existence check) — because content-addressing guarantees
   that an id collision implies byte-identical content, there is
   nothing to merge or reconcile; the second write is a safe, cheap
   no-op. `EvidenceItem`'s existing merge-custody behavior,
   `Entity`/`Hypothesis`'s existing upsert behavior, and the SQL table
   DDL are all **unchanged**.
3. **Wrap each `ingest_source(...)` call in one SQLite transaction.**
   `SqliteStore` gains an explicit transaction boundary (`BEGIN` at the
   start of `ingest_source`, `COMMIT` on success, `ROLLBACK` on any
   exception) spanning every `put_evidence`/`put_normalized_event`/
   `put_time_assertion` call the adapter's records produce. One
   `witnessgraph ingest` invocation becomes all-or-nothing: on a crash
   partway through, SQLite's own rollback guarantees the case reverts
   to its exact pre-ingest state (nothing partially written), so
   "re-run the same ingest command" is always safe and always sufficient
   — no separate resumability mechanism is added (Alternative C,
   rejected).
4. **Change `compute_manifest()`'s per-item contribution for
   `NormalizedEvent`/`TimeAssertion` from `content_hash_of(obj)` (full
   object hash, `created_at` included) to `obj.id` directly** — exactly
   mirroring how `EvidenceItem`'s contribution is already `e.id`
   (`raw_content_hash`), not a full-object hash. Since `obj.id` is now
   itself the content hash of the identity-relevant fields, this both
   (a) fixes the create-at-different-times manifest instability found
   in §1, and (b) is a smaller diff than adding new exclusion logic to
   `content_hash_of()`. `Entity` and `Hypothesis` are **not**
   content-addressed in this design (§6.6) and keep their current
   `content_hash_of(obj)` manifest contribution unchanged.
5. **Add a `manifest_version` field to `ProvenanceManifest`** so that a
   manifest computed under the new (v0.3) algorithm is never silently
   compared against one computed under the old (v0.1/v0.2) algorithm —
   see §11.

Nothing else changes. No new adapters, no new CLI commands beyond what
is strictly needed to expose this (none are strictly needed — the
existing `ingest`/`replay`/`verify`/`report` commands all keep their
current interface), no checkpoint/offset tracking, no schema-level
(SQL DDL) migration (§13).

### 6.6 Why `Entity` and `Hypothesis` are explicitly excluded from this change

The documented problem (§1) names only `NormalizedEvent` and
`TimeAssertion`. Neither `Entity` nor `Hypothesis` is produced
automatically by ingestion — both require an explicit, human-triggered
CLI action, so "re-running ingestion duplicates them" is not a real
failure mode for either type today. More importantly, content-addressing
`Hypothesis` would be actively wrong: two hypotheses that happen to
share the same `statement`/evidence references are not necessarily "the
same claim" — an analyst re-proposing a hypothesis in a later session,
or a second analyst independently arriving at the same wording, is a
meaningful, distinct event worth its own id and its own `created_at`.
Content-addressing `Entity` would edge toward automatic entity
resolution (deciding two `entities create` calls with identical
`identifiers` are "the same entity"), which v0.2's specification
explicitly and deliberately ruled out as scope creep. Both are left
exactly as they are.

### 6.7 Decision point: should v0.3 also wire up blob-store persistence?

§2/§3 item 5 found that `case.blobs.put(...)` is never called anywhere
in the current ingest path, contradicting `DESIGN.md`/`SECURITY.md`'s
description of blob storage. This was not part of the two named
problems in the task brief, so it is called out explicitly rather than
silently folded in or silently ignored:

- **Argument for including it in v0.3**: it is the other half of the
  same question this document already has to answer precisely — "define
  the atomic unit of ingestion" and "identify every currently separate
  persistence operation" (§8/§B) are not fully and honestly answerable
  without acknowledging that a *third* persistence operation (the blob
  write) is supposed to exist per the project's own documentation and
  currently does not. Leaving it out means the crash-atomicity design
  would describe atomicity only for metadata that doesn't yet durably
  reference real bytes.
- **Argument for treating it as a separate, later fix**: the task brief
  named exactly two problems (identity/idempotency, crash atomicity),
  both already substantial; wiring up blob persistence is additive
  functionality (a new call site in `ingest_source`, plus a policy for
  how it interacts with the transaction boundary — see §8's ordering
  rule) that could reasonably be its own small, separately-reviewed
  change, keeping this document's diff minimal and focused.

**Recommendation: include it, narrowly**, because it is not additive
*scope* so much as it is a precondition for the crash-atomicity design
being truthful about what "atomic" actually covers — but this is
flagged here explicitly so you can veto it and have it split out before
implementation begins. If included, §8's transaction-ordering rule
(write the blob first, since blob writes are self-idempotent and
content-addressed, then run the SQLite transaction) is the specific
mechanism; no new adapter behavior, no new CLI surface, and no schema
change are needed to add the one missing `case.blobs.put(raw_bytes)`
call inside `ingest_source`.

## 7. Identity / canonicalization specification

**Domain separation.** Every content-addressed id is computed as
`sha256_hex(canonical_json_bytes({"_type": "<TypeName>", **identity_fields}))`,
using the existing `witnessgraph.core.ids.canonical_json_bytes` function
unchanged. The `_type` tag is mandatory and prevents a `NormalizedEvent`
and a `TimeAssertion` (or any other type) that happen to canonicalize to
similar-looking field sets from ever colliding in the same id-space —
the same technique Git uses for its object store (`blob`/`tree`/`commit`/
`tag` headers prefixed before hashing content) and a standard practice
in content-addressed systems generally.

**`NormalizedEvent` identity fields:**
```
{
  "_type": "NormalizedEvent",
  "event_type": event_type,
  "attributes": attributes,       # dict, canonical_json_bytes already sorts keys
  "derived_from": derived_from,   # tuple, as constructed -- NOT re-sorted (see below)
}
```
Excluded from identity: `created_at` (ingest-time wall clock, not
observational content — see §1/§4), `entity_ids` (never populated by
any current code path; excluding it means a *future* entity-linking
feature could annotate an existing `NormalizedEvent` with entity
associations without changing its identity, which is a desirable
property even though entity linking itself remains out of scope here).

**`TimeAssertion` identity fields:**
```
{
  "_type": "TimeAssertion",
  "subject_event_id": subject_event_id,   # a NormalizedEvent id -- itself now content-derived
  "value": value,
  "precision": precision.value,
  "source_evidence_id": source_evidence_id,
  "asserted_by": asserted_by,
}
```
Excluded: `created_at` (same reasoning as `NormalizedEvent`).

**Does provenance participate in identity? No, for either type** —
mirroring `EvidenceItem`, where `chain_of_custody` is excluded from both
identity and the manifest. Provenance (here, just `created_at`, since
neither type currently has anything richer) is retained as an ordinary,
displayed field but never enters the hash.

**How logically identical observations from different sources behave:**
if two *different* `EvidenceItem`s (already themselves distinguished by
content-address, since their raw bytes differ) produce a
`NormalizedEvent` with the same `event_type`/`attributes`, their
`derived_from` values differ (different evidence ids), so their
`NormalizedEvent` identities **also differ** — they remain two distinct,
separately-tracked observations. Identity is defined relative to
evidentiary lineage, not merely to superficial field values. Only when
`derived_from` is *also* identical (which, given `EvidenceItem`'s
existing content-addressing, means the *same* underlying evidence bytes
were involved — whether from one re-run or from two files that
happened to contain byte-identical lines, which already collapse to one
`EvidenceItem` today) do two derivations collapse into one
`NormalizedEvent`. This is the direct resolution to the "perfect
reproducibility vs. preserving distinct forensic observations" tension
the review asks to be made explicit (see §20's closing discussion).

**Collision/domain-separation strategy:** the `_type` tag (above) is the
whole strategy. SHA-256 with a type-tagged canonical input has no known
practical collision risk at Witnessgraph's scale or threat model;
inventing a bespoke collision-resistance scheme beyond "use SHA-256 like
`EvidenceItem` already does" would be unjustified complexity.

**Explicitly deferred, not silently decided:** `derived_from`'s *order*
is not normalized (not sorted) before hashing. Every current adapter
produces a single-element `derived_from` tuple, so this has no observed
effect today; a hypothetical future feature that merges multiple
evidence items into one `NormalizedEvent` in non-deterministic order
could produce two different ids for what a human would consider "the
same" merged event. This is flagged as an open question (§18), not
resolved here, because resolving it now (deciding whether order is
semantically significant) is unnecessary for the stated v0.3 goal and
premature without a concrete multi-evidence-merge use case to design
against.

## 8. Ingestion transaction model

- **Scope**: one SQLite transaction per `ingest_source(case, adapter,
  source, ...)` call — i.e., per `witnessgraph ingest <case> <adapter>
  <source>` CLI invocation. This is the natural unit: it is what a user
  actually runs and re-runs, and adapters already process one source
  file per call.
- **Commit point**: after the adapter's generator is fully exhausted and
  every yielded `(EvidenceItem, NormalizedEvent | None)` pair (and any
  derived `TimeAssertion`) has been written, `ingest_source` commits
  once. `Case.record_manifest()` (already called by the CLI's `ingest`
  command right after `ingest_source` returns) remains a separate,
  immediately-following step — it writes `manifest.json` as a plain
  file, not a SQLite row, so it is not part of the SQL transaction, but
  it only runs at all if `ingest_source` returned successfully.
- **Rollback semantics**: any exception raised while iterating the
  adapter or writing a record — including the process being killed,
  which SQLite's own crash-recovery (rollback journal / WAL) handles on
  next open without any Witnessgraph-specific code — leaves the case
  exactly as it was before the `ingest` call started. No partial
  evidence, no partial normalized events, no partial time assertions
  from that invocation survive.
- **Uniqueness constraints**: unchanged at the SQL level (`id TEXT
  PRIMARY KEY` on all five tables, already present). The *application*
  behavior on a primary-key collision changes for
  `normalized_events`/`time_assertions` only (§6.2): from "replace" to
  "ignore, already present."
- **Is existing data ever overwritten?** No, for any of the five types,
  under this design — `EvidenceItem` already never overwrites (merges);
  `NormalizedEvent`/`TimeAssertion` move from "always replace" to "never
  overwrite, sometimes no-op"; `Entity`/`Hypothesis` keep their current,
  intentional upsert-by-id behavior (used only for `Hypothesis`'s
  deliberate status-change flow), unchanged.
- **Provenance/custody merge behavior**: unchanged for `EvidenceItem`
  (already merges custody records). `NormalizedEvent`/`TimeAssertion` do
  **not** gain a custody-like growable provenance list in this design
  (§6.6's sibling reasoning: identity content is guaranteed identical on
  a collision, so there is nothing to merge; tracking *how many times* or
  *when* an object was re-derived beyond its original `created_at` is
  explicitly deferred, §18).
- **Multi-file ingestion** (ingesting several sources into one case)
  remains several separate CLI invocations, each independently atomic.
  Ingesting file A then file B, where the process crashes during B,
  leaves A fully committed and B fully absent — a well-defined,
  recoverable state (re-run `ingest` for B; A is untouched and, if
  re-run too, a safe no-op).
- **Blob-store ordering (only if §6.7 is approved)**: the blob store
  (filesystem) and the SQLite database are two different storage
  substrates — no single transaction can span both, so "atomic across
  both" is not achievable in the way a single SQL transaction is
  atomic. The ordering rule that makes this safe without a distributed
  transaction: **write the blob first, via `case.blobs.put(raw_bytes)`,
  before starting or as the first step inside the SQLite transaction for
  that record.** `FileBlobStore.put()` is already self-idempotent
  (content-addressed, stage-to-temp-then-atomic-rename, a no-op if the
  target already exists — see `store/sqlite_store.py`'s `FileBlobStore`
  class, unchanged by this design). If the process crashes *after* the
  blob write but *before* the SQLite transaction commits, the result is
  an orphaned-but-harmless blob file on disk with no metadata row
  pointing at it yet — safe to leave (it will simply be re-written,
  harmlessly, as a no-op, the next time that same evidence is ingested)
  or, later, garbage-collected by a separate, optional tool (not part of
  this design). The reverse ordering (SQL first) is explicitly rejected:
  it would allow an `EvidenceItem` metadata row to exist whose
  `raw_content_hash` has no corresponding stored blob if a crash happens
  between the two writes — a real integrity gap, not just an orphaned
  file.

## 9. Crash/recovery model

- **During ingest**: covered entirely by §8's transaction scope. No
  Witnessgraph-specific recovery code is needed; SQLite's transactional
  guarantees are sufficient once the transaction boundary is correctly
  placed.
- **Recovery procedure for a user**: re-run the exact same `witnessgraph
  ingest <case> <adapter> <source>` command that was interrupted. This
  is now unconditionally safe (idempotent) rather than the
  currently-documented "discard the partial case directory and start
  over" (`SECURITY.md`'s current guidance, which this design makes
  obsolete for the ingest path specifically).
- **Corrupted `case.db`** (the v0.2 concern — a header-valid-but-
  internally-corrupted or garbage file): **out of scope for v0.3.**
  v0.2 already added clean, non-traceback failure handling for this in
  `report`/`verify`/`replay`/`import`; v0.3 does not change or extend
  that, and does not attempt to make a corrupted SQLite file
  recoverable (that is a filesystem/storage-integrity problem, not an
  ingestion-transaction problem).
- **Not in scope**: resuming a single adapter's parse of one very large
  file from a mid-file offset. Rejected in §5 (Alternative C) as
  disproportionate to the stated problem.
- **Blob/SQLite consistency after a crash (only if §6.7 is approved)**:
  per §8's ordering rule, the only reachable post-crash state is either
  (a) neither the blob nor the metadata row exists (crash before the
  blob write — full rollback, safe), or (b) the blob exists but the
  metadata row does not yet (crash between the blob write and the SQL
  commit — safe, orphaned file, re-ingest is still a correct no-op/
  retry). The state "metadata row exists but blob does not" is
  structurally unreachable under this ordering, which is the entire
  point of choosing it.

## 10. Provenance model

Unchanged in kind from v0.1/v0.2, extended in exactly one place:

- `EvidenceItem.chain_of_custody`: unchanged, still the only growable
  per-object provenance list in the system.
- `NormalizedEvent`/`TimeAssertion`: still carry `created_at`
  (informational, non-identity, first-write-wins on a content
  collision — there is nothing to reconcile since a collision means
  identical identity-relevant content, but the *stored* `created_at` is
  whichever value was present at the row's original insert, and a
  later re-derivation attempt with a different `created_at` is simply
  discarded by the "insert if absent" policy, exactly as `EvidenceItem`
  already discards a second attempt's `source_locator`/`collected_at`
  in favor of the first).
- No new provenance fields are added anywhere in this design (§6.6,
  §8's "explicitly deferred" note). If a future need arises to track
  *every* derivation event for `NormalizedEvent`/`TimeAssertion` (not
  just the first), that is a separate, additive design decision — this
  document deliberately does not pre-build it speculatively.

## 11. Portable-case compatibility policy (design only, not implemented here)

Because `compute_manifest()`'s algorithm changes for `NormalizedEvent`/
`TimeAssertion` (§6.4), a manifest recorded by a v0.1/v0.2 case is **not**
recomputable to the same hash under the v0.3 algorithm, even though
nothing about the underlying evidence or observations changed. Policy:

1. `ProvenanceManifest` gains a `manifest_version: int` field (default
   `1` for the current, pre-v0.3 algorithm; `2` for the v0.3 algorithm
   described here). This is additive to the model; existing
   `manifest.json` files lacking the field are read as version `1` via
   a Pydantic default, not rejected.
2. `witnessgraph replay`/`verify` compare a recomputed manifest to a
   recorded one **only when both share the same `manifest_version`**.
   A version mismatch is reported as a distinct, explicit outcome —
   `"manifest algorithm version differs (recorded: v1, recomputed: v2) —
   not comparable"` — never silently treated as MATCH or MISMATCH. This
   mirrors how content-addressed systems generally handle a hash-scheme
   upgrade (e.g. Git's SHA-1→SHA-256 repository format transition, or a
   Certificate Transparency log's explicit version field) rather than
   comparing incompatible hashes as if they meant the same thing.
3. **v0.1/v0.2 `.wgcase` archives remain fully importable and readable**
   under v0.3 — `import_case`/`export_case` do not interpret the JSON
   payloads at all (§2's finding), so nothing about opening an old case
   changes. Its *existing* `NormalizedEvent`/`TimeAssertion` rows keep
   their old, random ids permanently — v0.3 does not retroactively
   rewrite ids in an imported case (that would require every id
   reference elsewhere — `derived_from`, `subject_event_id`,
   `EvidenceRef`, `TimeAssertion.subject_event_id` — to be rewritten in
   lockstep, a genuinely riskier operation than leaving old data as-is).
4. **`witnessgraph ingest` run against an *old*, imported case**
   (adding new records to a case that still contains v0.1/v0.2-era
   random-id objects) is explicitly supported and safe: new records get
   v0.3 content-addressed ids; old records keep their old ids; nothing
   requires them to be uniform. `report`/`verify` continue to work over
   a case with a mix of old- and new-style ids without any special
   casing, because nothing about rendering or manifest computation
   depends on an id's *origin*, only on `obj.id` and `obj`'s other
   fields.
5. Whether to eventually offer an **opt-in, explicit** "recompute ids
   for this legacy case" migration command is left as an open question
   for a later release (§18) — it is not required for v0.3's stated
   goal (new ingestion becomes idempotent and atomic) and is
   substantially riskier than the above, since it touches every
   cross-reference in a case.

**This section is policy only.** No manifest version field, no
comparison-gating logic, and no migration command are implemented as
part of this design document.

## 12. Security considerations

- **Malicious duplicate/collision attempts**: SHA-256 with a
  domain-separating `_type` tag gives no practical way for an attacker
  to engineer two semantically-different observations that hash to the
  same `NormalizedEvent`/`TimeAssertion` id (this is the same
  collision-resistance level `EvidenceItem` already relies on).
- **Hash-domain separation**: addressed explicitly in §7 (`_type` tag)
  — without it, a crafted `NormalizedEvent` and `TimeAssertion` whose
  other fields happened to canonicalize identically could theoretically
  collide across types; domain separation removes this class entirely.
- **Provenance confusion**: unaffected by this design beyond what's
  already true — `NormalizedEvent`/`TimeAssertion` still don't claim any
  stronger custody guarantee than `EvidenceItem` already provides for
  the underlying bytes; nothing here weakens or strengthens that.
- **Tampered source offsets**: not applicable — this design introduces
  no offset/checkpoint concept (§5, Alternative C rejected), so there is
  no offset value to tamper with.
- **Replay ambiguity**: directly *reduced* by this design — today, a
  duplicated `NormalizedEvent` silently changes the manifest hash with
  no indication of *why*; after this change, re-ingestion is idempotent,
  so the "why did the manifest change" question only ever has genuine,
  content-driven answers. The `manifest_version` gate (§11) removes a
  different ambiguity: comparing hashes computed under different
  algorithms as if they were commensurable.
- **SQLite corruption**: unrelated to this design; v0.2's existing
  `sqlite3.DatabaseError` handling in `report`/`verify`/`replay`/`import`
  is unaffected and unchanged.
- **Partial transaction recovery**: this design's core security-relevant
  property — a killed process during ingest can no longer leave a case
  in an ambiguous "some of source X is here, some isn't" state; SQLite's
  transaction rollback guarantees full reversion, which is a strictly
  *stronger*, more auditable property than today's per-row-commit
  behavior.
- **Path/source-locator handling**: unaffected — `source_locator`
  remains an opaque, informational string (per v0.2's design), not
  something this identity change touches or reinterprets.

## 13. Required schema changes

Two distinct notions of "schema" are relevant here, and inspection shows
they are affected very differently:

- **SQLite table DDL** (`store/sqlite_store.py`'s `_SCHEMA`): **no
  change required.** Every table is already `(id TEXT PRIMARY KEY, data
  TEXT NOT NULL)` — the SQL layer has no awareness of which Pydantic
  fields exist inside `data`, so changing how an id is *computed*, or
  adding a new field with a default to a model, requires zero DDL
  migration. This is a direct, load-bearing finding from reading the
  actual schema, not an assumption.
- **Pydantic model schema** (the JSON shape inside `data`): one
  additive field, `manifest_version: int = 1`, on `ProvenanceManifest`
  only (§11). `NormalizedEvent`/`TimeAssertion`/`EvidenceItem`/`Entity`/
  `Hypothesis` gain **no new fields** in this design. Existing rows'
  JSON blobs remain valid and parse unchanged under the new model
  version (Pydantic applies the field default on load for old
  `manifest.json` files/rows that predate it).

No SQLite migration script, `ALTER TABLE`, or data-rewrite pass over
existing rows is required by this design.

## 14. Required code changes (design only — not applied)

- `core/events.py`: add `NormalizedEvent.create(...)` classmethod
  computing a content-derived `id`; keep the existing constructor
  available for direct/test use exactly as `EvidenceItem` does today.
- `core/time_model.py`: same pattern, `TimeAssertion.create(...)`.
- `core/provenance.py`: change `compute_manifest()`'s
  `normalized_events`/`time_assertions` collection-hash inputs from
  `content_hash_of(obj)` to `obj.id`; add `manifest_version` to
  `ProvenanceManifest` and stamp the current algorithm version when
  computing.
- `store/sqlite_store.py`: change `put_normalized_event`/
  `put_time_assertion` from `INSERT OR REPLACE` to an
  insert-if-absent pattern (`INSERT OR IGNORE`, or an explicit
  `get_*` check first); wrap `ingest_source`'s writes in one
  transaction (this likely means adding a transaction-scoped method or
  context manager to `SqliteStore`/`Case`, e.g. `Case.transaction()`,
  rather than changing per-`put_*` commit behavior globally — `entities
  create`/`hypothesis propose` etc. can keep their existing
  single-statement-per-command commit pattern, since they are not the
  documented problem).
- `ingest/pipeline.py`: use the new `.create(...)` constructors; open
  the transaction at the top of `ingest_source` and commit/rollback
  around the loop.
- `replay/replay.py`: no change to its own logic, but its behavior
  changes qualitatively once `compute_manifest()` changes underneath it
  (a version-mismatch outcome becomes possible — needs a small update
  to `ReplayResult`/its CLI rendering to surface "not comparable" rather
  than mis-reporting MATCH/MISMATCH across versions).
- `cli/main.py`: `replay`/`verify` need to render the new "not
  comparable" outcome distinctly from MATCH/MISMATCH.
- `report/render.py`: the Integrity Summary section should mention
  `manifest_version` alongside the hash, so a human reading a report
  from a mixed-version case understands why a comparison might be
  "not comparable" rather than assuming a bug.
- `ingest/pipeline.py` (only if §6.7 is approved): add exactly one call,
  `case.blobs.put(raw_bytes)`, per evidence record, ordered before that
  record's SQLite writes per §8's ordering rule. `store/sqlite_store.py`'s
  `FileBlobStore` itself needs no change — it is already correct and
  already unit-tested.

## 15. Required test strategy (design only — not applied)

- Golden regression test reproducing exactly the empirical check in §1
  (`ingest` the same fixture twice, assert `NormalizedEvent`/
  `TimeAssertion` counts stay at their post-first-ingest value, not
  double).
- `EvidenceItem` behavior unchanged: existing
  `test_duplicate_content_from_different_sources_preserves_both_provenance`/
  `test_reingesting_same_source_does_not_duplicate_custody` continue to
  pass unmodified.
- `NormalizedEvent.create(...)`/`TimeAssertion.create(...)` id
  determinism: same identity-field inputs → same id, across repeated
  calls and across two independently-constructed objects.
- `created_at` exclusion: two calls to `.create(...)` with identical
  identity fields but different `created_at` values produce the *same*
  id.
- Domain separation: a `NormalizedEvent` and a `TimeAssertion`
  constructed so their non-`_type` fields would canonicalize
  identically (a deliberately adversarial test) produce *different*
  ids.
- Distinct-observation preservation: two `NormalizedEvent`s derived from
  two different `EvidenceItem`s, with identical `event_type`/
  `attributes`, get different ids (the "identity vs. lineage" property
  central to §7).
- Transaction atomicity: simulate an adapter that raises partway through
  yielding records; assert the case contains **zero** new evidence/
  events/assertions afterward (full rollback), not a partial set.
- Manifest-version gating: a v1-tagged recorded manifest compared
  against a v2-recomputed one reports the new "not comparable" outcome,
  never MATCH or MISMATCH.
- Manifest stability across ingest time: re-run the exact §1 empirical
  check (same file, two different `collected_at` wall-clock values, two
  fresh cases) and assert the manifest hashes are now **identical** —
  the regression test for finding #3.
- Existing 114 (78 v0.1 + 36 v0.2) tests, and the entire `tests/`
  directory generally, continue to pass — in particular
  `tests/unit/test_provenance_hash.py` and
  `tests/integration/test_golden_sample_case.py`, which touch manifest
  computation and full-pipeline ingestion respectively and must be
  re-examined (not necessarily modified) against the new algorithm.
- **Property-based tests** (the project already depends on `hypothesis`
  — see `tests/unit/test_serialization_determinism.py` — so this reuses
  an existing tool, not a new one):
  - For arbitrary `event_type`/`attributes` dict values (bounded-size
    strings/dicts, mirroring the existing
    `test_canonical_json_is_order_independent_property` strategy shape),
    constructing a `NormalizedEvent` twice with the same inputs always
    yields the same id, and constructing it with any single field
    changed always yields a different id (a general identity-determinism
    property, not just fixed example cases).
  - For arbitrary insertion orders of the same fixed object set into a
    store, `compute_manifest()`'s `normalized_events`/`time_assertions`
    collection hash is order-independent (extending the existing
    `test_manifest_hash_independent_of_insertion_order` pattern from
    `tests/unit/test_provenance_hash.py` to the new algorithm).
- **Crash/failure-injection tests**: a store or adapter double rigged to
  raise on the Nth yielded record, for N ranging over every position in
  a multi-record source; assert that for every N, the case afterward
  contains either all-N-1-previously-committed-invocations' data (if
  this is a second `ingest` call after a first one succeeded) or nothing
  from the failing invocation (rollback) — never a partial slice of the
  failing invocation's own records.
- **Compatibility tests**: open an unmodified v0.1/v0.2-era case fixture
  (containing only random-UUID `NormalizedEvent`/`TimeAssertion` ids and
  a `manifest_version`-less `manifest.json`) under the new code; assert
  it still loads, `report`/`verify`/`replay` still run against it
  without error, and a *new* ingest into that same case produces
  content-addressed ids for the new records while the old records keep
  their old ids untouched (§11).
- **Reproducibility tests**: the full §1 empirical scenario as a
  permanent regression test (documented above), plus an export → import
  → re-ingest-the-same-source-again round trip asserting the manifest
  hash and object counts are identical to the pre-export state.
- **Blob-consistency tests (only if §6.7 is approved)**: after a
  successful ingest, every `EvidenceItem.raw_content_hash` in the store
  has a corresponding blob in `case.blobs` whose bytes hash to that same
  value (`case.blobs.get(h)` succeeds and `sha256_hex(...)` matches);
  a simulated crash immediately after a blob write but before its
  SQLite commit leaves an orphaned blob and zero corresponding metadata
  rows (per §9), and a subsequent retry of the same ingest still
  succeeds and is still a correct no-op for that record.

## 16. Migration/upgrade strategy

- **No data migration is required or proposed for existing cases** —
  per §11/§13, old cases remain fully readable, importable, and usable;
  their existing objects simply keep their pre-v0.3 ids and contribute
  to manifests under `manifest_version=1` semantics.
- **No automatic in-place upgrade** of an old case's ids is proposed.
  An explicit, opt-in "recompute this case's ids under the new scheme"
  command is left as a future, separate design (§18) — v0.3 does not
  build it.
- **Rollout is purely forward-looking**: from the moment v0.3 ships,
  every *new* `ingest` invocation (against a new or an old case)
  produces content-addressed, idempotent `NormalizedEvent`/
  `TimeAssertion` records and runs inside a per-invocation transaction.
  Nothing about existing data needs to change for this to be true.

## 17. Explicit non-goals

Everything the task's NON-GOALS section lists (AI, web UI, graph
database, multi-user collaboration, live endpoint collection, network
scanning, exploitation, credential collection, malware functionality,
adapter-breadth-for-its-own-sake, cloud/SaaS, auth/user-management,
plugin marketplace) — none of these are touched, and none are implied
by anything in this design. Additionally, specific to this design:

- No resumable/checkpointed ingestion (§5, Alternative C).
- No content-addressing of `Entity` or `Hypothesis` (§6.6).
- No automatic entity resolution of any kind (unchanged from v0.2).
- No growable, multi-derivation provenance list for `NormalizedEvent`/
  `TimeAssertion` (§10) — deferred, not built speculatively.
- No SQL schema/DDL migration (§13 — none is needed).
- No automatic rewriting of ids in existing/imported cases (§11/§16).
- No change to `report`'s determinism contract, byte-level guarantees,
  or Unicode-neutralization behavior from v0.2 — this design is
  entirely about the ingestion/identity/manifest layer underneath it.

## 18. Open questions (not resolved by this document)

1. Should `derived_from`'s order participate in identity, or should it
   be canonicalized (e.g., sorted) before hashing? Deferred (§7) —
   no current adapter produces multi-element `derived_from`, so there is
   no concrete case to design against yet.
2. Should a future, opt-in "recompute legacy case ids" migration command
   exist, and if so, how does it safely rewrite every cross-reference
   (`derived_from`, `subject_event_id`, `EvidenceRef.id`) in lockstep
   without corrupting an existing case? Left for a later release.
3. Should `NormalizedEvent`/`TimeAssertion` eventually gain a
   growable, `chain_of_custody`-like multi-derivation provenance list
   (tracking every ingest run that re-derived them, not just the
   first)? Deferred (§10) pending a concrete need.
4. Exactly how should `Case`/`SqliteStore` expose the new transaction
   boundary as an API (a context manager on `Case`? a parameter to
   `ingest_source`? a method on `SqliteStore`?) — a real implementation
   detail worth a short, separate design pass at implementation time,
   not resolved here since multiple reasonable shapes exist and none of
   the alternatives changes this document's architectural conclusions.
5. Should the CLI's `ingest` command report "processed N records, M
   newly stored" rather than today's single "ingested N" count, now
   that a "processed but already present" outcome is possible? A small,
   worthwhile UX nicety, not required for correctness — left as an
   implementation-time judgment call.

## 19. Acceptance criteria

- Re-ingesting the same, unmodified source into the same case any
  number of times leaves `EvidenceItem`/`NormalizedEvent`/
  `TimeAssertion` counts unchanged after the first successful ingest.
- Re-ingesting the same, unmodified source at two different wall-clock
  times, into two otherwise-identical fresh cases, produces identical
  manifest hashes.
- A simulated crash partway through one `ingest_source` call leaves the
  case in exactly its pre-ingest state (verified by a rollback test),
  not a partial one.
- Two `NormalizedEvent`s derived from two different `EvidenceItem`s with
  identical `event_type`/`attributes` remain distinct objects with
  distinct ids.
- A `NormalizedEvent` and a `TimeAssertion` whose non-type-tagged fields
  would canonicalize identically produce different ids (domain
  separation holds).
- All pre-existing v0.1 tests (78) and v0.2 tests (36) continue to pass
  unmodified except where this document explicitly calls out a
  necessary, reviewed change (manifest/replay-related tests noted in
  §15).
- `ruff check .` and `mypy --strict src tests` remain clean.
- No SQL DDL change is present in the diff implementing this design.
- Existing v0.1/v0.2 `.wgcase` archives remain importable and
  reportable without modification.

## 20. Why this is a meaningful next step, not generic feature expansion

Every prior phase of Witnessgraph has been building toward one claim:
that an investigation's conclusions can be independently reconstructed
from its evidence, not taken on trust. v0.1 made that claim true for a
*single, uninterrupted* run of the tool. v0.2 made the *human-readable
presentation* of that claim itself deterministic and auditable. What
remained open — and what this document's own empirical check confirms
is a real, present defect, not a theoretical one — is that the claim
quietly stops being true the moment a real analyst does what real
analysts actually do: re-run a command after an interruption, or
re-ingest a source a second time to be sure. A tool whose core promise
is reproducibility cannot have that promise depend on the user never
needing to retry anything. Fixing this is not "adding a feature" in the
sense the NON-GOALS section is worried about — it does not grow
Witnessgraph's surface area (no new adapters, no new commands, no new
UI), it does not add analytical cleverness, and it does not touch the
report/verify layer's own contract. It closes the specific, named gap
between "reproducible in principle" and "reproducible in the actual,
interrupted, re-run conditions of real fieldwork" — which is exactly
the thesis, not an expansion of it.

**Trade-off made explicit, as required:** this design resolves the
"perfect reproducibility vs. preserving distinct forensic observations"
tension by making identity a function of *evidentiary lineage*
(`derived_from`), not merely of superficial content. The cost is that
two structurally-identical-looking events from *different* evidence
remain separate objects even though a naive "just hash the visible
fields" scheme would have merged them (arguably "more reproducible" in
a narrow sense) — this is a deliberate choice in favor of the
evidence-first thesis over a marginally simpler hashing rule, and is the
single most important design decision in this document.

## 21. Explicit decision log

Every major design choice in this document, stated as decision /
rationale / alternatives considered / why rejected, per item E of the
review brief:

1. **Content-address `NormalizedEvent` and `TimeAssertion`.**
   *Rationale*: reuses `EvidenceItem`'s already-proven pattern; makes
   re-derivation of the same observation structurally a no-op instead
   of a duplicate (§1's empirical finding). *Alternatives*: do nothing
   (§5.A), application-level dedup pass (§5.B), full event-sourcing
   rewrite (§5.E). *Rejected because*: (A) leaves a confirmed, live
   defect unfixed; (B) treats a design defect as a cleanup problem and
   requires inventing a similarity heuristic Witnessgraph has
   deliberately avoided elsewhere (v0.2's entity-linking exclusion);
   (E) a disproportionate rewrite of the storage layer for a narrower
   problem.
2. **Exclude `created_at` from identity for both types.**
   *Rationale*: mirrors `EvidenceItem` (which excludes
   `chain_of_custody`/is identified purely by content bytes); required
   for id determinism, since `created_at` is ingest-wall-clock-derived,
   not observational content (§1, §4). *Alternatives*: include it (the
   naive "hash the whole object" approach already in
   `content_hash_of()`). *Rejected because*: empirically proven to make
   re-ingestion at a different time change the id/manifest hash for
   identical content (§1's second empirical finding) — the opposite of
   the reproducibility goal.
3. **Domain-separate with a `_type` tag before hashing.**
   *Rationale*: standard content-addressing practice (Git's object-type
   prefix); prevents cross-type id collisions. *Alternatives*: no
   domain separation. *Rejected because*: leaves a theoretical but
   avoidable collision class open for zero cost to close.
4. **Anchor identity to `derived_from` (evidentiary lineage), not just
   superficial field values.**
   *Rationale*: resolves the "perfect reproducibility vs. preserving
   distinct forensic observations" tension explicitly (§7, §20) — two
   observations from different evidence stay distinct even if their
   interpreted fields look identical. *Alternatives*: hash only
   `event_type`/`attributes` (content-only, lineage-blind).
   *Rejected because*: would silently merge two independently-collected
   pieces of evidence that happen to normalize identically — directly
   contrary to the evidence-first thesis (§1's core principle).
5. **Do not content-address `Entity`/`Hypothesis`.**
   *Rationale*: neither is produced automatically by ingestion, so the
   named duplication problem doesn't apply to them; content-addressing
   `Hypothesis` would treat two independently-authored, coincidentally-
   identical claims as "the same," which is wrong; content-addressing
   `Entity` edges toward automatic entity resolution. *Alternatives*:
   apply the same treatment uniformly to all five types for consistency.
   *Rejected because*: "consistency" here would mean importing bugs
   (false merging) into two types that don't have the problem being
   fixed (§6.6).
6. **Insert-if-absent, no growable multi-derivation provenance list for
   `NormalizedEvent`/`TimeAssertion`.**
   *Rationale*: content-addressing guarantees a collision means
   identical identity-relevant content, so there is nothing to merge;
   smallest-sufficient fix for the named problem. *Alternatives*: a
   `chain_of_custody`-like growable list tracking every re-derivation.
   *Rejected because*: not required to fix the stated problem, adds a
   new field (schema surface) and complexity for a benefit (multi-
   derivation history) nobody has asked for yet — deferred (§18) rather
   than speculatively built.
7. **Per-`ingest_source`-invocation SQLite transaction scope.**
   *Rationale*: matches the actual unit a user runs and re-runs; SQLite
   already provides the rollback guarantee for free once the boundary
   is placed correctly. *Alternatives*: per-record transactions (today's
   behavior — already shown insufficient), one global transaction across
   multiple files/invocations, or explicit checkpointing (§5.C).
   *Rejected because*: per-record is the documented defect itself;
   spanning multiple CLI invocations in one transaction doesn't match
   how the tool is actually used (each `ingest` call is a separate
   process); checkpointing solves a resumability problem the project
   doesn't have at its stated scale.
8. **`compute_manifest()` uses `obj.id` directly for the two
   content-addressed types, instead of `content_hash_of(obj)`.**
   *Rationale*: smallest diff that both fixes the manifest
   time-instability (§1) and stays consistent with `EvidenceItem`'s
   existing pattern. *Alternatives*: keep `content_hash_of(obj)` but add
   field-exclusion logic to it. *Rejected because*: more code, another
   place to keep the exclusion list in sync, for the same result.
9. **Add `manifest_version` rather than silently changing the hash
   algorithm in place.**
   *Rationale*: prevents a v1-computed and v2-computed manifest from
   ever being silently compared as if commensurable (§11) — mirrors how
   content-addressed systems generally handle a hash-scheme version
   bump. *Alternatives*: don't version it; treat any mismatch as
   MISMATCH (as today's code would, blindly). *Rejected because*: a
   MISMATCH verdict on an untampered but differently-versioned case
   would be a false, misleading integrity failure, not an honest
   "not comparable."
10. **No SQL DDL migration.**
    *Rationale*: directly verified — the schema is opaque `(id, data)`
    JSON-blob tables; nothing about id-computation or additive Pydantic
    fields requires a `CREATE`/`ALTER TABLE` change (§13). *Alternatives*:
    none seriously considered; this is a finding, not a choice.
11. **No automatic rewriting of ids in existing/imported cases.**
    *Rationale*: old and new-style ids can coexist safely since nothing
    depends on an id's *origin* (§11); rewriting every cross-reference
    in an existing case in lockstep is materially riskier than leaving
    it alone. *Alternatives*: an automatic migration on first open of an
    old case. *Rejected because*: silently rewriting a published,
    possibly-already-shared case's object ids on open is exactly the
    kind of surprising, hard-to-reverse behavior this project's
    local-first/no-silent-mutation ethos avoids; left as an explicit,
    opt-in, future command if ever needed (§18).
12. **(Conditional, §6.7) Wire up the missing blob-store write, ordered
    before the SQLite transaction.**
    *Rationale*: newly discovered gap directly adjacent to "define the
    atomic unit of ingestion"; blob-first ordering makes the only
    reachable crash states safe (§8, §9). *Alternatives*: SQL-first
    ordering; leave blob-store unwired entirely (status quo).
    *Rejected because*: SQL-first admits a real integrity gap (metadata
    claiming a hash with no backing blob); leaving it unwired perpetuates
    a documented-but-false claim in `DESIGN.md`/`SECURITY.md`. This item
    remains yours to veto or split out before implementation (§6.7).

## 22. Explicit mapping to the review brief (A–F)

An index, not new content, so every lettered/bulleted question in the
brief is traceably answered somewhere above:

- **A. Identity/idempotency** — §7 (identity fields, canonicalization,
  domain separation, lineage-anchoring), §6.6 (scope boundary: why not
  `Entity`/`Hypothesis`), §8 (duplicate-ingestion/replay behavior via
  insert-if-absent), §11 (backward compatibility, schema/version
  migration policy, treatment of existing UUID-based objects), §13
  (schema changes — none at the SQL level), §21 items 1–6 and 9–11.
- **B. Crash atomicity** — §8 (atomic unit, every persistence
  operation, transaction boundaries, uniqueness/overwrite/merge
  semantics, blob-store ordering), §9 (recovery behavior, what's safely
  retried, out-of-scope corruption handling), §2/§3 item 5 and §6.7
  (the newly-found blob-store gap and its resolution), §21 items 7 and
  12.
- **C. Scope** — §17 (explicit non-goals, restating and confirming the
  brief's exclusion list), §6 (nothing else changes), §6.6 (why
  `Entity`/`Hypothesis` are out), §5 (why checkpointing/resumability and
  event-sourcing were rejected as disproportionate).
- **D. Implementation plan** — §14 (production files), §15 (tests,
  including property-based, crash/failure-injection, compatibility, and
  reproducibility tests), §13 (schema/version implications), §16
  (migration strategy).
- **E. Explicit decisions** — §21 (this document's full decision log,
  decision/rationale/alternatives/rejection for every major choice), and
  §5 for the three architecture-level alternatives considered in full
  narrative form.
- **F. Security/reproducibility** — §12 (content-addressed evidence,
  provenance, replay ambiguity, partial-transaction recovery,
  path/source-locator handling), §11 (export/import compatibility), §4
  (the five kept-distinct reproducibility definitions, including
  deterministic reporting's relationship to this work), §10 (chain of
  custody, unchanged), §8/§9 (case manifest integrity under the new
  transaction/blob model).

---

## DESIGN STATUS: READY FOR IMPLEMENTATION

The architecture is small, additive, requires no SQL migration, reuses
an already-proven pattern (`EvidenceItem`'s content-addressing and
merge behavior) rather than inventing a new one, and every claim in
this document is grounded in direct inspection of the current
repository plus three live empirical/inspection findings against the
actual codebase (the duplication defect, the ingest-time manifest
instability, and the unwired blob store). The five open questions in
§18 are genuinely deferrable — none of them blocks a correct, minimal
v0.3 implementation of §6's five points.

**One item is not "deferrable" in the same sense and needs your explicit
sign-off before implementation, separately from general plan approval:
§6.7's recommendation to also wire up the missing `case.blobs.put(...)`
call.** It is recommended (folded into §8's transaction design either
way it's decided), but it was not one of the two named problems in the
task brief, so implementation should not proceed on that specific piece
without an explicit yes/no from you — everything else in this document
can proceed on a single approval.

## Implementation roadmap (concise — not executed)

1. `NormalizedEvent.create(...)` / `TimeAssertion.create(...)` +
   identity-field unit tests (§15), including the domain-separation and
   `created_at`-exclusion tests, before touching any calling code.
2. `SqliteStore` insert-if-absent behavior for the two affected tables +
   store-level idempotency tests.
3. `Case`/`SqliteStore` transaction boundary API + a rollback test
   (simulated mid-ingest failure).
4. `ingest/pipeline.py` wired to use `.create(...)` and the new
   transaction boundary; the §1 empirical regression test becomes a
   real, committed test at this point.
5. `ProvenanceManifest.manifest_version` + `compute_manifest()`'s
   `obj.id`-based contribution for the two types; the manifest-hash
   time-independence regression test.
6. `replay`/`verify`/`report` updated to surface a version-mismatch
   outcome distinctly; their existing tests re-run and, where
   necessary, extended (not silently broken).
7. Full-suite regression pass (existing 114 + new tests), `ruff`,
   `mypy --strict`.
8. `SECURITY.md`/`DESIGN.md` documentation pass reflecting the new
   crash-recovery story (replacing "discard the partial case directory"
   guidance for the ingest path) — a separate, explicit step requiring
   its own authorization, not bundled into the code change silently.

Steps 1–7 are implementation; step 8 is documentation. None of these
steps are executed as part of this design document.
