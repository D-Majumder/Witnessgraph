# Witnessgraph v0.4 Design — Explicit Analyst-Declared Source Identity

Status: **design-only. No implementation exists yet.** This document is
the prerequisite design identified as required (NO-GO conclusion) by
`docs/phase4-v0.4-gap-analysis-design.md` §14. Every claim about the
current data model below is grounded in direct inspection of the
repository at published HEAD `c9c9cf1c5cb8f10999864110e7163156c4877d9a`.

**The suggested starting point, `EvidenceItem.source_id: str | None`, is
treated here as a hypothesis to test, not a conclusion.** §2 and §9 find
a materially better-fitting location once the existing `chain_of_custody`
model is inspected directly; the reasoning for departing from the
suggested design is given in full, not asserted.

## 1. Semantics — what a Source represents

Direct inspection rules out committing to any single one of the five
candidate semantics the way this document was asked to consider them:

- *Physical log file* — too narrow: a rotated log (`auth.log`,
  `auth.log.1`) is naturally "one source" across multiple files.
- *Host/system* — too narrow in the other direction: a single host might
  legitimately have two independent evidence streams an analyst wants
  to compare (e.g. its firewall log and its auth log), which are not "one
  source" under this reading.
- *Logical data feed* — closer, but "feed" implies an ongoing,
  infrastructure-level concept Witnessgraph has no other trace of
  anywhere (no scheduler, no live collection, no feed registry).
- *Collection endpoint* — implies a live-collection architecture
  Witnessgraph explicitly excludes (DESIGN.md principle 6, SECURITY.md).
- *Analyst-defined provenance grouping* — this is the one that fits
  without contradiction.

**Chosen semantic: `source_id` is an analyst-declared assertion of common
provenance, with no meaning Witnessgraph itself interprets.** Two
records sharing a `source_id` mean exactly one thing structurally: the
analyst who ingested them asserted they should be treated as
originating from the same evidentiary stream, for whatever reason they
judged relevant (same file, same host, same feed, or any other grouping
they intend). Witnessgraph does not verify, infer, or interpret *why*
two records share a `source_id`, in the same way it does not interpret
what an `Entity.identifiers` value or an `event_type` string "really"
means — it stores and compares the declared value exactly. This is the
narrowest semantic that is simultaneously (a) precise enough to build a
gap detector against and (b) honest about what the system can actually
verify (nothing, beyond string equality).

## 2. Identity form — and the resulting design correction

**`source_id` must be a human-readable, stable string — never
content-derived, never opaque/hash-shaped, and (this is the correction)
never a bare top-level scalar field on `EvidenceItem`.**

*Why not content-derived*: a content hash of anything would either (a)
hash the source's own label text, which is just an obfuscated version of
the human-readable string with no added property worth the loss of
readability, or (b) hash something about the evidence's bytes, which
would make `source_id` a second, competing content-address alongside
`EvidenceItem.id` — a direct conflict with the single existing
content-addressing scheme, and semantically backwards besides (two
different real-world sources can and do produce byte-identical content;
conflating "same bytes" with "same source" is exactly the error this
whole prerequisite exists to avoid — it is `EvidenceItem.id`'s job, not
`source_id`'s).

*Why not opaque*: an opaque identifier (a UUID, say) would defeat the
report's job of letting a human recognize which real source a finding is
about — the entire reason this field is being added is so an analyst can
read "host1" in a report, not a UUID they'd have to cross-reference
elsewhere. There is no elsewhere to cross-reference it against (§15: no
new `Source` table is being proposed), so an opaque identifier would be
strictly worse than a human-readable one with no compensating benefit.

**The correction, found by inspecting `core/evidence.py` directly**:
`ProvenanceRecord` (`chain_of_custody`'s element type) already exists
specifically to record *per-ingestion-occasion* facts about one piece of
evidence — it already carries its own `source_locator: str | None`,
already documented as "what lets two ingestions of byte-identical content
from two different sources remain distinguishable in the custody history
rather than colliding" (`EvidenceItem`'s own docstring, and directly
exercised by the existing, passing
`test_duplicate_content_from_different_sources_preserves_both_provenance`
test). A single scalar `EvidenceItem.source_id` field would silently
conflict with this already-designed-for scenario: if two different real
sources happen to produce byte-identical raw bytes (exactly the case that
existing test is built to cover), they collapse into **one**
`EvidenceItem` by content-addressing design, and a single top-level
`source_id` field would force one of the two sources' declared identity
to be silently dropped by the store's existing first-write-wins merge
rule (`SqliteStore.put_evidence`) — precisely the "silently discard
materially different declared metadata" defect this project already had
to fix once, for `NormalizedEvent.entity_ids`, in the v0.3 correction
round. Putting `source_id` on `ProvenanceRecord` instead avoids
reintroducing that exact defect: each custody entry (each ingestion
occasion) carries its own declared `source_id`, exactly parallel to how
it already carries its own `source_locator`.

**Recommended schema change, precisely:**

```python
class ProvenanceRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    actor: str
    action: str
    timestamp: datetime
    source_locator: str | None = None
    source_id: str | None = None   # NEW, additive, analyst-declared
```

`EvidenceItem` itself gains no new field. A convenience, non-persisted
read helper is proposed for ergonomics only:

```python
def declared_source_ids(self) -> frozenset[str]:
    """Distinct, non-None source_id values across this item's custody history."""
    return frozenset(r.source_id for r in self.chain_of_custody if r.source_id is not None)
```

When this returns exactly one value, the evidence item has an
unambiguous declared source. When it returns more than one (the
byte-identical-content-from-two-declared-sources case above), any
consumer (§14: the future gap detector) must treat the item as
**ambiguous and excluded**, never guess which one "wins" — the same
"never treat absence/ambiguity as proof of anything" discipline the
prerequisite's own motivating document opened with.

## 3. Scope

- **Case-local only.** Witnessgraph has no global registry of anything
  (confirmed: every id is either a case-local content hash or a
  case-local random UUID; the SQLite store is always exactly one case
  directory). `source_id` carries no meaning across two different case
  files — "host1" in case A and "host1" in case B are not asserted to be
  related by anything in this design.
- **Not required to be unique within a case** — the opposite is the
  normal case: many `EvidenceItem`s are expected to share one
  `source_id`. Uniqueness is not a validation rule (§8).
- **Optional, always** — an ingestion that declares no `source_id`
  produces `ProvenanceRecord.source_id = None`, a fully valid, permanent
  state, not a transitional one to be "fixed" later.

## 4. Legacy compatibility

- Every `ProvenanceRecord` in every case ingested before this feature
  exists has no `source_id` key in its stored JSON at all. Loading it via
  `ProvenanceRecord.model_validate_json(...)` applies the new field's
  default (`None`) exactly as `ProvenanceManifest.manifest_version`
  already does for pre-v0.3 manifests (docs/phase3-v0.3-design.md §11) —
  this is the same, already-proven additive-field pattern, not a new one.
- **No inferred fallback, ever.** A legacy record with `source_id=None`
  is never backfilled from `source_adapter`, `source_locator`, or
  anything else, automatically or otherwise. This is a hard rule, not a
  default that a future convenience feature might quietly override:
  inferring a source identity after the fact is exactly the "treat
  absence as something it isn't" failure mode this whole design line
  exists to avoid.
- **Gap-analysis eligibility**: a future gap detector (§14) must treat
  `source_id=None` evidence as **excluded from cross-source comparison**,
  reported explicitly (e.g. "N evidence items excluded: no declared
  source"), never silently grouped by `source_adapter` as a fallback —
  that fallback was exactly the design this document's prerequisite
  review rejected.
- **Report representation**: renders as an explicit `(no declared
  source)` placeholder, following the exact existing convention already
  used for `observed_at`/`first_seen`/`last_seen` (`"(not set)"`) and
  `source_locator` (`"(not set)"`) in `report/render.py` — same pattern,
  new field.

## 5. Ingestion API — smallest clean mechanism

**Supplied once per ingest invocation, attached to every resulting
custody record from that invocation.** Not per-adapter-call, not a
separate ingestion "context" object, not a new adapter-protocol
parameter.

Justification: v0.3 already established "one `witnessgraph ingest`
invocation, one source file" as the atomic, natural unit (the same unit
`ingest_source`'s transaction boundary uses). `SourceDescriptor`
(`ingest/base.py`) already exists specifically to describe "one
already-existing evidence source to be ingested" — it is the correct,
already-present home for this, requiring no new concept:

```python
@dataclass(frozen=True)
class SourceDescriptor:
    path: Path
    kind_hint: str | None = None
    source_id: str | None = None   # NEW, additive
```

**No `EvidenceAdapter` protocol change is required** — this is a
materially smaller change than v0.3's raw-bytes 3-tuple extension.
`ingest()`'s signature and yielded-tuple shape are untouched; adapters
already receive the full `SourceDescriptor` as `source` and already read
`source.path`/`source.kind_hint` from it. Each of the three adapters
needs exactly one additional line: pass `source.source_id` through to
`EvidenceItem.create(...)`, which gains one new optional parameter:

```python
@classmethod
def create(cls, *, raw_bytes: bytes, source_adapter: str, adapter_version: str,
           source_locator: str, collected_at: datetime,
           observed_at: datetime | None = None,
           ingest_parameters: dict[str, str] | None = None,
           source_id: str | None = None) -> EvidenceItem:  # NEW param
    ...
    record = ProvenanceRecord(
        actor=f"adapter:{source_adapter}@{adapter_version}",
        action="ingested", timestamp=collected_at,
        source_locator=source_locator,
        source_id=source_id,   # NEW
    )
    ...
```

**CLI surface**: `cli/main.py`'s `ingest` command gains one new,
optional argument, `--source-id`, defaulting to `None`, threaded straight
into `SourceDescriptor(path=source, source_id=source_id)`. No change to
`ingest_source`'s own signature — the value flows entirely through
`SourceDescriptor` and each adapter's already-existing access to it.

This is not implemented by this document — the shapes above are the
target for the eventual code change, stated precisely enough to be
reviewed and estimated, per §16.

## 6. Multiple files / repeated ingestion — exact behavior

- **Same source ingested twice** (same file, same declared `source_id`
  both times): unaffected by this feature beyond carrying the label —
  v0.3's existing idempotent re-ingest behavior (identical
  `NormalizedEvent`/`TimeAssertion` ids, `put_evidence`'s custody merge)
  applies exactly as today; the second custody record's `source_id`
  matches the first, so no new custody entry is even needed if the
  `source_locator` also matches (existing "genuinely new" custody
  dedup logic in `SqliteStore.put_evidence` already compares whole
  `ProvenanceRecord` values, which now includes `source_id` in that
  comparison — an identical resubmission stays a no-op).
- **Same source under a different file path** (the file moved/was
  renamed between two ingestions of the same underlying content, same
  declared `source_id` both times): this is exactly the scenario
  `source_id` exists to support — `source_locator` differs (correctly
  reflecting where the bytes currently live), `source_id` agrees
  (correctly reflecting they're the same logical stream). Two custody
  records accumulate (locators differ, so the existing dedup-by-value
  check treats them as genuinely distinct), both bearing the same
  `source_id`.
- **Two different files from the same declared source** (e.g. rotated
  logs `host1-jan.log`, `host1-feb.log`, both `--source-id host1`): the
  intended, ordinary pattern — many distinct `EvidenceItem`s, one shared
  `source_id` value across their custody records.
- **Two different hosts using the same adapter**: now correctly
  distinguishable (`--source-id host1` vs. `--source-id host2`) — this is
  the exact case `docs/phase4-v0.4-gap-analysis-design.md` §6.4 showed
  was structurally impossible before this prerequisite.
- **One file containing multiple logical sources** (e.g. a merged log
  interleaving several hosts' lines, or records that each self-identify a
  host in their own content): **explicitly not solved by this design.**
  `source_id` operates at whole-`SourceDescriptor` (whole-ingest-call)
  granularity, never at per-record granularity. A single ingest
  invocation assigns exactly one `source_id` (or none) to every record it
  produces, with no mechanism to vary it within one file. An analyst
  ingesting a genuinely mixed file must either pre-split it (outside
  Witnessgraph's scope) or accept that the whole file is declared under
  one label, which may not be accurate for every line in it. A
  content-attribute-based per-record refinement (e.g., trusting an
  ingested `"host"` attribute as a finer-grained identity) was considered
  and is explicitly deferred — it reintroduces the "assume this field
  means source identity" problem `docs/phase4-v0.4-gap-analysis-design.md`
  §6.1 already rejected as an automatic mechanism, and would need its own
  separate, opt-in design (structurally analogous to Phase 2's
  already-deferred entity-linking helper) if ever pursued.
- **Partial/repeated ingestion** (an interrupted `ingest` re-run): v0.3's
  atomicity guarantees a crash rolls back the *entire* invocation
  (including, now, whatever `source_id` that invocation declared), so a
  clean retry with the *same* `--source-id` value converges exactly as
  before. **New footgun this feature introduces, stated plainly**: if an
  analyst retries an interrupted ingest with a *different* `--source-id`
  than the original attempt intended, the retry's records get the new
  label with no warning or cross-check — Witnessgraph has no persisted
  memory of "what source_id was intended for this file" to compare
  against. This is flagged as an unresolved, unmitigated risk in §16, not
  silently designed around.

## 7. Determinism — exact answer, not asserted

**`source_id` participates in none of: `EvidenceItem` identity,
`NormalizedEvent` identity, `TimeAssertion` identity, or manifest
hashing.** This is not a design choice being made here — it is a
structural consequence already proven by the existing code, verified by
direct inspection of each hashing path:

- `EvidenceItem.id`/`raw_content_hash`: enforced by the
  `_id_matches_content_hash` validator to equal
  `sha256_hex(raw_bytes)` — a function of raw bytes only.
  `chain_of_custody` (where `source_id` now lives) is not an input to
  this computation at all, structurally, regardless of what fields
  `ProvenanceRecord` carries.
- `NormalizedEvent.identity_hash`/`TimeAssertion.identity_hash`
  (docs/phase3-v0.3-design.md §7): neither takes `chain_of_custody`,
  `source_id`, or any `EvidenceItem` field beyond `derived_from`/
  `source_evidence_id` (an id reference, not the referenced object's
  content) as input. Unaffected, structurally.
- `compute_manifest()` (`core/provenance.py`): the `evidence_items`
  collection is computed as `{e.id: e.raw_content_hash for e in ...}` —
  it never touches `chain_of_custody` at all (this is the exact,
  already-documented property that lets `with_custody_record` be a
  "legitimate, non-mutating operation that must never change a case's
  reproducibility hash" — `EvidenceItem`'s own docstring). Adding a field
  *inside* `chain_of_custody` cannot affect a computation that never
  reads `chain_of_custody` in the first place.
- **Export/import**: `portable.py` does verbatim zip/unzip with zero JSON
  interpretation (confirmed directly, again, in this pass) — `source_id`
  round-trips byte-for-byte with zero special handling, exactly as
  `source_locator` already does.

**Can analyst-supplied `source_id` introduce nondeterminism?** No, given
identical inputs. `source_id` is a plain, explicitly-supplied string with
no wall-clock or randomness in its assignment — a repeated invocation
with the same `--source-id` value produces the same stored value, every
time. The only way two logically-intended-to-be-identical ingestions
diverge is if an analyst supplies *different* `source_id` values across
them (§6's retry footgun) — this is input variability, not system
nondeterminism: the system's output remains a pure function of its
actual inputs, `source_id` included.

**No `manifest_version` bump is required.** This is a stronger,
better-grounded conclusion than v0.3's own `manifest_version` addition
needed to reach, because that change *did* alter how two collections were
hashed (`normalized_events`/`time_assertions`, `obj.id` vs.
`content_hash_of(obj)`) and therefore needed a version gate
(docs/phase3-v0.3-design.md §11). This change touches a field the
manifest computation never reads at all — there is nothing to gate.

## 8. Validation — explicit rules, no silent normalization

Per instruction, no rule below silently mutates analyst input; every
failure is a hard rejection (`typer.BadParameter`, matching the existing
pattern in `cli/main.py::_resolve_evidence_ref`) at ingestion time, not a
best-effort correction.

- **Empty string**: rejected. "No source declared" must be expressed by
  omitting `--source-id` entirely (`None`), never by passing `""` — this
  keeps "not supplied" and "explicitly supplied as empty" from becoming
  two representations of the same thing.
- **Whitespace-only, or leading/trailing whitespace**: rejected outright,
  not silently trimmed. A string reaching storage is exactly the string
  the analyst typed, with no possibility of two visually-different inputs
  (`"host1"` vs. `"host1 "`) silently colliding into the same stored
  value or silently staying distinct after an invisible trim.
- **Unicode**: permitted in general (no ASCII-only restriction — nothing
  else in the codebase imposes one, e.g. `Hypothesis.statement`,
  `Entity.identifiers` values are unrestricted Unicode). Rendered through
  the existing `_untrusted`/`_neutralize` pipeline (§9), not a new one.
- **Control characters, bidi controls, zero-width characters**: **rejected
  at input time**, stricter than free-text fields like
  `Hypothesis.statement` (which only *neutralizes* these at render time).
  Justification for the stricter rule: `source_id` is used for *exact
  equality*-based grouping, not just display — a zero-width or bidi
  character embedded in one declared `source_id` would make it compare
  unequal to a visually-identical one, while the report's existing
  neutralization would render both as the same visible text, silently
  producing two "different" source groups that a human reviewing the
  report cannot distinguish by looking at it. This is a correctness risk
  specific to identifier-shaped fields, not a general property of free
  text, and is exactly the class of problem `report/render.py`'s
  `_NEUTRALIZE` set already exists to name (bidi controls, zero-width
  characters, C0 controls minus tab/LF) — this design reuses that same
  fixed code-point set as the *rejection* list here, rather than
  inventing a second one.
- **Path-like strings** (e.g. `"logs/host1"`): permitted, never
  interpreted as an actual filesystem path — no `Path()` coercion, no
  existence check, no normalization of separators. Treated exactly like
  `source_locator` is already treated: an opaque display string (§9).
- **Duplicate `source_id` values across records**: not an error — the
  expected, intended, common case.
- **Extremely long IDs**: rejected beyond a fixed maximum length (a
  policy choice, not derived from any existing constraint — proposed at
  256 characters, generous for a human-readable label, explicitly not
  claimed as an objectively correct number, same posture as
  `docs/phase4-v0.4-gap-analysis-design.md` §7's `MIN_GAP_SECONDS`).
- **Case sensitivity**: exact, case-sensitive string comparison —
  `"Host1"` and `"host1"` are different, distinct `source_id` values,
  never folded together. No existing string comparison anywhere in this
  codebase (evidence content hashing, `canonical_json_bytes`, id
  comparisons) performs case-folding; introducing it only for this field
  would be an unjustified, inconsistent special case.
- **Normalization**: none, beyond the hard-rejection rules above. No
  Unicode normalization form is applied (e.g. no NFC/NFKC folding) —
  doing so would let two byte-different-but-canonically-equivalent inputs
  silently become "the same" `source_id`, another unjustified special
  case relative to how every other string field in this codebase is
  handled (compared and hashed exactly as given).

## 9. Security / provenance

`source_id` gets exactly the same treatment `source_locator` already has,
preserving that field's existing opacity contract by direct extension
rather than inventing a parallel one:

- **Never interpreted as a filesystem path or executable reference** — no
  code path constructs a `Path(source_id)`, opens a file named by it, or
  passes it to a shell/subprocess. (Confirmed: no such interpretation
  exists for `source_locator` today, and none is proposed for
  `source_id`.)
- **Never used to construct a query string** — all existing SQLite access
  uses parameterized queries exclusively (`self._conn.execute("... WHERE
  id = ?", (id,))`, confirmed throughout `store/sqlite_store.py`);
  `source_id` participates in no new query construction.
- **Rendered exactly as stored**, through the existing `_untrusted()` →
  `_neutralize()` → `_code_span()` pipeline in `report/render.py` — the
  same pipeline every other analyst/adapter-supplied string already goes
  through, reused unmodified (§8's stricter *input-time* rejection for
  bidi/zero-width/control characters is a belt-and-suspenders addition
  on top of this existing render-time safety net, not a replacement for
  it — a legacy record that somehow already contains such a character,
  pre-dating this validation rule, still renders safely).
- **`source_locator`'s existing "never reparse" contract is unaffected
  and unextended** — `source_id` is a wholly separate field precisely so
  that nothing about it creates pressure to parse or restructure
  `source_locator` in the future.

## 10. Reporting

No redesign of `report/render.py`'s architecture. One new line inside the
existing per-`chain_of_custody`-record block in `_render_evidence_inventory`
(the same loop that already renders `actor`/`action`/`timestamp`/
`source_locator` per record):

```python
source_id_text = (
    _untrusted(record.source_id) if record.source_id is not None else "(no declared source)"
)
lines.append(
    f"    - actor: {_untrusted(record.actor)}, "
    f"action: {_untrusted(record.action)}, "
    f"timestamp: {_format_datetime(record.timestamp)}, "
    f"source_locator: {locator}, "
    f"source_id: {source_id_text}"
)
```

Follows the exact existing `"(not set)"`-style placeholder convention
(here: `"(no declared source)"`, more specific and consistent with §4's
legacy-eligibility wording) already used for `observed_at`, `first_seen`,
`last_seen`, and `source_locator` itself. No new report section, no
change to section ordering, no change to the byte-determinism or
Unicode-neutralization contracts (docs/phase2-v0.2-spec.md) — one
additional, already-safely-rendered field on an already-existing line.

## 11. Manifest / export / import

- **Case manifest**: not represented, and must not be — §7 establishes
  this is a structural consequence of `chain_of_custody` already being
  outside the manifest's evidence-item contribution, not a new exclusion
  rule being invented for this field.
- **Exported portable case**: `portable.py`'s zip packaging is
  content-agnostic (confirmed, again, by direct reading) — `source_id`
  is included automatically, byte-for-byte, as part of the `case.db` file
  it already copies verbatim. No change to `export_case`/`import_case`.
  needed.
- **Imported cases**: identical guarantee — an imported case's reports
  and manifest hash must be byte-identical to the original, and are,
  because nothing about import interprets or rewrites JSON payloads
  (§16 requires a regression test proving this explicitly for
  `source_id` specifically, not just inferring it from the general
  argument).

## 12. Migration / versioning

Direct inspection of `store/sqlite_store.py::_SCHEMA` (unchanged since
v0.1): all five tables are `CREATE TABLE IF NOT EXISTS <name> (id TEXT
PRIMARY KEY, data TEXT NOT NULL)`. The SQL layer has zero awareness of
which Pydantic fields exist inside the opaque `data` JSON blob — exactly
the same finding docs/phase3-v0.3-design.md §13 already made for
`manifest_version`, reused here without modification:

- **No SQL DDL change required.**
- **No manifest_version bump required** (§7 — stronger than v0.3's own
  case, since this change doesn't touch any hashed computation at all).
- **Pydantic model change**: one additive field on `ProvenanceRecord`
  (`source_id: str | None = None`) — old JSON blobs missing the key parse
  successfully via the Pydantic default, exactly as `manifest_version`'s
  addition already proved works for this codebase's storage shape.
- **No migration script or data-rewrite pass** over any existing case is
  needed or proposed.

## 13. Adversarial tests

1. **Two JSONL files, same adapter, different `source_id`s**: ingest both
   with distinct `--source-id` values into one case; assert every
   resulting `EvidenceItem`'s `declared_source_ids()` correctly reflects
   its own file's declared value, and the two sets are disjoint.
2. **Same `source_id` across repeated ingestion**: re-ingest the same
   file with the same `--source-id` twice; assert idempotence (no
   duplicate custody records, `declared_source_ids()` unchanged) —
   extends v0.3's existing re-ingest-idempotence tests, not a new
   mechanism.
3. **Different `source_id`s with identical evidence bytes**: construct
   two ingestions producing byte-identical raw content under two
   different declared `--source-id` values; assert the single resulting
   `EvidenceItem`'s `declared_source_ids()` returns **both** values
   (ambiguous, per §2), and that a consumer treating ambiguity as
   "excluded" behaves correctly against this exact record.
4. **Legacy evidence with `None`**: load a case built without this
   feature (a `ProvenanceRecord` JSON blob genuinely lacking the key, not
   merely `source_id: null`); assert it parses, `record.source_id is
   None`, and `declared_source_ids()` returns an empty set.
5. **Export/import preservation**: export a case containing declared
   `source_id` values, import it, assert the restored case's
   `chain_of_custody` records — `source_id` included — are byte-identical
   to the original, and the manifest hash is unchanged (§11).
6. **Deterministic reports**: render the same case's report twice, assert
   byte-identical output including the new `source_id:` line
   (mirrors the existing `test_render_report_is_deterministic_across_repeated_calls`
   pattern).
7. **Unicode / source-label rendering**: a `source_id` containing
   ordinary non-ASCII text (e.g. `"héôte-1"`) renders verbatim through
   `_untrusted`; assert it is *not* rejected by §8's validation (only
   control/bidi/zero-width characters are rejected, not Unicode
   generally).
8. **Duplicate / invalid `source_id`s**: assert many records legitimately
   sharing one `source_id` is accepted (not an error, §8); assert an
   empty string, a whitespace-only string, and a string exceeding the
   length limit are each rejected with a clear error at the CLI layer,
   not silently coerced.
9. **`source_id` differing only by case**: `"Host1"` vs. `"host1"` ingested
   as two separate declarations; assert they are treated as two distinct,
   non-colliding source identities (§8's case-sensitivity rule).
10. **`source_id` containing a path-like string**: `--source-id
    "logs/host1"`; assert it is accepted, stored and rendered verbatim,
    and never passed to any filesystem API (§9) — e.g. assert ingestion
    succeeds identically whether or not a path with that literal name
    exists on disk.
11. **`source_id` containing control/bidi characters**: assert each of
    the fixed code points already enumerated in
    `report/render.py::_NEUTRALIZE` (bidi controls, zero-width
    characters, C0 controls excluding tab/LF) is **rejected at input
    time** when present in a `--source-id` value, per §8's stricter rule
    (distinct from how these characters are merely neutralized, not
    rejected, in free-text fields like `Hypothesis.statement`).

## 14. Gap-detector boundary — what changes, what doesn't

**Becomes possible**: a future gap detector's `source_of(evidence_item)`
resolver (`docs/phase4-v0.4-gap-analysis-design.md` §7) can be
implemented honestly as
`evidence_item.declared_source_ids()`, treating a single unambiguous
value as the resolved source and an empty or multi-valued result as
"excluded, not eligible for cross-source comparison" — finally allowing
two hosts' logs ingested through the same adapter to be correctly
distinguished, resolving exactly the adversarial example that produced
the prior NO-GO.

**Remains impossible, even after this milestone**:
- **Automatic/inferred source identity.** Witnessgraph still cannot
  detect on its own that two files belong to different hosts — an
  analyst must say so explicitly, every time.
- **Per-record (sub-file) source granularity.** A single ingest
  invocation still assigns one `source_id` (or none) to every record it
  produces; a genuinely mixed-source file remains mis-attributable as a
  whole (§6).
- **Verifying that a declared `source_id` is accurate.** This is, and
  remains, an unverifiable, analyst-trust-based input — structurally
  identical in kind to `Hypothesis.inferred_by` or any `Entity.identifiers`
  value already in the system.
- **Cross-case source correlation.** `source_id` is case-local only
  (§3) — "host1" in one case file carries no asserted relationship to
  "host1" in a different case file.

## 15. Minimality — what this design deliberately does not add

- **No new `Source` table or top-level model.** `source_id` is one
  additive `str | None` field on the already-existing `ProvenanceRecord`
  — consistent with the project's single established storage shape
  (opaque JSON blob per row, confirmed unchanged since v0.1, §12). A
  dedicated `Source` entity/table was considered (this is, in effect,
  Alternative C from the prior gap-analysis document) and rejected here
  in its *table/registry* form specifically — this document proposes
  Alternative C's underlying idea (a real, analyst-declared identity) in
  the smallest form that idea can take, not the largest.
- **No graph database, new adapters, web UI, AI, network API, or
  multi-user support** — none of this design's reasoning depends on any
  of them, and direct inspection of every touch point (`ProvenanceRecord`,
  `SourceDescriptor`, three adapters' one-line additions, one CLI flag,
  one report line) confirms none is required.

## 16. Go / no-go

**CONDITIONAL GO.**

**Exact condition**: sign-off on placing `source_id` on `ProvenanceRecord`
rather than as a top-level `EvidenceItem.source_id` field (§2) — this is
a deliberate, justified departure from the design direction named in the
task that introduced this document, not an open unknown. Every other
finding in this document (determinism, migration, validation, security,
reporting) follows mechanically once that one placement decision is
accepted. If a top-level `EvidenceItem.source_id` field is required
instead for reasons outside this document's analysis, §2's
multiple-declared-sources edge case must be re-addressed explicitly
before implementation, not silently dropped.

**Exact files that would need modification** (not touched by this
document):
- `src/witnessgraph/core/evidence.py` — add `ProvenanceRecord.source_id`,
  add `EvidenceItem.create(...)`'s new `source_id` parameter, add
  `declared_source_ids()`.
- `src/witnessgraph/ingest/base.py` — add `SourceDescriptor.source_id`.
- `src/witnessgraph/ingest/adapters/jsonl_adapter.py`,
  `csv_timeline_adapter.py`, `syslog_adapter.py` — one line each, passing
  `source.source_id` through to `EvidenceItem.create(...)`.
- `src/witnessgraph/cli/main.py` — one new `--source-id` option on the
  `ingest` command.
- `src/witnessgraph/report/render.py` — one new line in
  `_render_evidence_inventory`'s per-custody-record block.

**Exact tests required**: all 11 in §13, plus a regression pass
confirming every existing test (159 as of the reviewed v0.3 HEAD)
continues to pass unmodified — this is purely additive, so no existing
test's expected output should change (the report golden fixture,
`tests/integration/fixtures/sample_case_report.md`, *would* need
regeneration only if the golden case's own construction is updated to
declare a `source_id` — if it is not, its expected `source_id: (no
declared source)` line is new, additive output requiring the fixture to
be regenerated for that reason, not because anything already in it
changes).

**Unresolved design questions**, not blocking but requiring explicit
future attention:
- The §6 "retry with a different `--source-id`" footgun has no proposed
  mitigation in this document — flagged, not designed around, per the
  instruction not to add infrastructure (e.g. a persisted
  "intended source_id" ledger) without direct evidence it's needed.
- Whether a future, explicitly opt-in, per-record source-identity
  refinement (trusting a declared content attribute, analogous to Phase
  2's deferred entity-linking helper) is ever worth building for the
  "one file, multiple logical sources" case (§6) is left open, not
  decided here.
- The exact maximum length for `source_id` (§8, proposed 256) and the
  exact rejected code-point set (§8, proposed: reuse
  `report/render.py::_NEUTRALIZE`'s set) are stated as concrete
  proposals, not empirically validated numbers — same epistemic status
  as `docs/phase4-v0.4-gap-analysis-design.md`'s threshold caveats.

## Critical self-check (performed before finalizing)

Re-read against the exact four failure modes this document was asked to
rule out:

- **Content-derived?** No — §2 explicitly rejects this, and the
  recommended field is a plain analyst-supplied string with no hash
  computation anywhere in its path.
- **Inferred from `source_locator`?** No — §4 states this as a hard rule
  ("no inferred fallback, ever"), and §9 explicitly keeps `source_id` a
  wholly separate field precisely so no future pressure exists to parse
  `source_locator` for it.
- **Inferred from adapter type?** No — nothing in this design reads
  `source_adapter` to populate or default `source_id`; the two fields are
  independent, and a `source_id` is required to be explicitly supplied by
  a human (§5), never derived from which adapter happened to parse the
  record.
- **Dependent on wall-clock ingestion time?** No — `source_id` is never
  compared against, derived from, or defaulted to `collected_at` or any
  other timestamp anywhere in this document; §7 explicitly confirms the
  only way two intended-to-be-identical ingestions could disagree is
  human input variability (the retry footgun), not any property of
  ingestion timing.
