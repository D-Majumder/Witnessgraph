# Witnessgraph v0.2 Specification — Deterministic Investigation Report & Reproducibility Workflow

Status: **design-only specification. No implementation exists yet.** This
document is the authority for what v0.2 builds; `docs/phase2-research.md`
is prior research/rationale that informed this decision but does not
override it where the two differ (see "Deviations from the research
document" below).

## 0. Deviations from `docs/phase2-research.md`

The research document's Candidate A recommendation is followed, with one
explicit scope reduction decided after that research was written:

- **Entity linking is removed from v0.2 entirely.** The research
  document's §5 proposed an opt-in `entities link-by-attribute` helper.
  That helper is **not** part of this specification, in any form, to
  keep v0.2's surface area small and to avoid scope creep into anything
  resembling entity resolution. v0.2 presents whatever `Entity` records
  already exist in a case; it adds no way to create or merge them beyond
  the existing `witnessgraph entities create` command.
- Everything else in this document is a refinement, not a reversal, of
  the research document's Candidate A: a deterministic report over the
  existing evidence graph, plus explicit reproducibility verification.

## 1. Purpose and thesis

Witnessgraph's thesis, unchanged from v0.1 (`README.md`, `DESIGN.md`):

> Cybersecurity investigations should be reproducible from evidence, not
> dependent on opaque conclusions.

v0.2's purpose is to make that thesis *visible and checkable* by a human
who was not the original analyst: given a case directory (or a
`.wgcase` archive), produce a single, deterministic, human-readable
document showing exactly what evidence exists, what was derived from it,
what an analyst concluded, and how any of that can be independently
re-verified — without adding any new kind of evidence, inference, or
storage.

## 2. Problem statement

v0.1 already has everything needed to *prove* a case is unaltered
(`witnessgraph replay`) and everything needed to *store* evidence,
events, entities, time assertions, and hypotheses correctly. What it
lacks is a way for a human to *read* a case's investigative content
without either querying the CLI command-by-command
(`timeline`, `entities list`, `hypothesis list`, `contradictions`) and
manually reassembling the picture, or writing ad hoc code against the
`Store` protocol. There is also no defined contract for what "the same
case produces the same report" means, which matters because the whole
point of the exercise is a reproducibility claim, not just a rendering
convenience.

## 3. What v0.2 adds to the existing v0.1 system

Exactly two new commands, both additive and read-only with respect to
the existing data model. **Resolved decision (see §20, item 2):**
`report`, `verify`, and `replay` are three distinct capabilities with
non-overlapping responsibilities; none replaces another.

1. A **`witnessgraph report <case_dir>`** command that renders a case's
   full investigative content — evidence inventory, timeline, entities,
   hypotheses, contradictions, and integrity/provenance status — as a
   single deterministic Markdown document. **Responsibility: a
   deterministic, human-readable *projection* of the case.** It performs
   no verification of its own beyond stating the last-known manifest
   status (§5, item 7); it never recomputes or judges reproducibility.
2. A **`witnessgraph verify <case_dir>`** command that performs
   reproducibility verification as a first-class, scriptable, exit-code-
   driven operation, suitable for use in a handoff/peer-review workflow
   and in tests. **Responsibility: confirm the case's integrity and
   reproducibility** — is the recorded manifest still correct, and
   (optionally) does the report still regenerate deterministically. It
   is the human/workflow-facing entry point for "is this case trustworthy
   right now."

The pre-existing `witnessgraph replay` command is **unchanged** and
keeps its own distinct responsibility: **reproduction of the
investigation's derivation steps** — recomputing the provenance manifest
directly from the evidence graph (evidence content hashes plus the
canonical content hash of every derived object) and reporting whether
that recomputation matches what was last recorded. `replay` is the
low-level cryptographic primitive that answers "if I redo the manifest
derivation from scratch, do I get the same number"; `verify` is built on
top of that same primitive (see §6) but exists as a separate,
workflow-oriented command because its audience and its full scope
(optionally including the report) differ from `replay`'s narrower,
single-purpose role. See §6 for the precise, non-overlapping definition
of each command's contract.

Nothing else changes. No new adapters, no entity linking, no schema
changes, no new persisted object types, no AI, no network calls, no web
server.

## 4. User workflow

```
witnessgraph init ./case
witnessgraph ingest ./case jsonl ./events.jsonl
witnessgraph ingest ./case syslog ./auth.syslog
witnessgraph entities create ./case host --derived-from <event_id> --id hostname=web01
witnessgraph timeline ./case                     # existing, unchanged
witnessgraph contradictions ./case               # existing, unchanged
witnessgraph hypothesis propose ./case "..." --evidence <id>
witnessgraph hypothesis support ./case <hyp_id> --evidence <id>
witnessgraph report ./case                       # NEW: deterministic Markdown to stdout
witnessgraph report ./case --output case-report.md   # NEW: same deterministic content, to a file
witnessgraph replay ./case                       # existing, unchanged: recompute manifest, check it
witnessgraph export ./case ./case.wgcase
witnessgraph import ./case.wgcase ./case-restored
witnessgraph verify ./case-restored              # NEW: reproducibility check (manifest,
                                                  #  optionally report regeneration too)
witnessgraph report ./case-restored --output restored-report.md
diff case-report.md restored-report.md           # must be byte-identical
```

This is the same `init → ingest → inspect → hypothesis → export/import →
verify` loop the project already documents; v0.2 adds `report` at the
"inspect" and hand-off points and adds `verify` as the workflow-level
reproducibility-check step, alongside — not instead of — the existing
`replay`.

## 5. Precise report semantics

`witnessgraph report <case_dir>` reads a case (via `Case.open`, exactly
like every other read-only CLI command) and writes a single Markdown
document to stdout (or to a file via `--output`, see §6) containing, in
this fixed order:

1. **Header**: case directory name (not absolute path — see §13),
   recorded manifest hash if present, and a note on whether the report
   itself is covered by that hash (it is not — see §8).
2. **Evidence inventory**: one entry per `EvidenceItem`
   (`store.list_evidence()`), sorted by `id` (the content hash — see
   §7), showing `id`, `source_adapter`, `adapter_version`,
   `source_locator`, `raw_size_bytes`, `collected_at`, `observed_at`
   (if set), and the full `chain_of_custody` (each `ProvenanceRecord`'s
   `actor`, `action`, `timestamp`, `source_locator`).
3. **Timeline**: one entry per `NormalizedEvent`
   (`store.list_normalized_events()`), sorted by the same key as the
   existing `timeline` CLI command (earliest associated `TimeAssertion`
   value, falling back to `created_at`), each showing `event_type`,
   `attributes`, `entity_ids`, `derived_from`, and **every**
   `TimeAssertion` for that event (not just the earliest) — `value`,
   `precision`, `asserted_by`, `source_evidence_id` — so that disagreeing
   assertions are visibly presented side by side rather than collapsed,
   per DESIGN.md principle 3.
4. **Entities**: one entry per `Entity` (`store.list_entities()`), sorted
   by `id`, showing `entity_type`, `identifiers`, `first_seen`/
   `last_seen`, and `derived_from`. No linking, merging, or inference is
   performed — this is a direct, read-only projection of what already
   exists (per the explicit removal in §0).
5. **Hypotheses**: one entry per `Hypothesis`
   (`store.list_hypotheses()`), sorted by `id`, showing `statement`,
   `status`, `inferred_by`, `created_at`, and its `supporting_evidence`
   and `contradicting_evidence` lists (each `EvidenceRef`'s `kind` and
   `id`) rendered under clearly separate headings so a reader cannot
   mistake supporting for contradicting evidence.
6. **Contradictions**: the output of
   `detect_time_contradictions(store)`, sorted by
   `(subject_event_id, assertion_a.id, assertion_b.id)`, each entry
   showing the two disagreeing `TimeAssertion`s and the event they both
   describe.
7. **Integrity summary**: the recomputed `ProvenanceManifest`
   (`case.compute_manifest()`), its `manifest_hash`, and — if
   `manifest.json` exists — whether it matches the recorded manifest
   (i.e., the same check `replay`/`verify` perform), so the report
   always states its own case's verification status rather than
   requiring a separate command run to know if the case is intact.
   **Corrected after adversarial review (MAJOR 1; see §21):** a MATCH
   verdict here must not be presented as covering the entire report.
   This section must explicitly state, in plain language, which fields
   displayed elsewhere in the report are **not** covered by
   `manifest_hash` — namely, on `EvidenceItem`: `collected_at`,
   `source_locator`, `source_adapter`, `adapter_version`,
   `ingest_parameters`, `observed_at`, and the full `chain_of_custody`
   (§8's table lists the complete, authoritative scope). Only
   `EvidenceItem.raw_content_hash` (evidence bytes) and the full
   canonical content of every `NormalizedEvent`, `Entity`,
   `TimeAssertion`, and `Hypothesis` are manifest-covered. This
   disclosure is not optional decoration — it is a required part of the
   Integrity Summary's content, not left to an implementer's
   discretion.

Every section is present even when empty (e.g. "Entities: (none)"), so
report structure is identical across cases regardless of content —
important for the determinism and diffability of the output.

## 6. Proposed CLI interface

**Resolved decision (see §20, item 2):** `report`, `verify`, and
`replay` are three distinct commands with non-overlapping
responsibilities. `verify` is implemented by calling the same
`replay_and_verify` logic `replay` already uses — sharing an internal
function is not the same as one command replacing another — but the two
commands serve different audiences and different scopes, spelled out
below. None of the three is removed, renamed, or made redundant by this
specification.

### `witnessgraph report <case_dir> [--output PATH] [--format markdown]`

**Responsibility: deterministic, human-readable projection of the
case.** Performs no verification of its own.

**Resolved decision (see §20, item 3):** the command writes
deterministic Markdown to **stdout by default**; an explicit
`--output PATH` writes the **same deterministic content** to a file
instead. The two modes must never diverge in content — only in
destination:

- `case_dir` (argument, required): path to an existing case directory
  (same semantics as every other command's `case_dir` — must contain
  `case.db`, per `Case.open`).
- **Default mode (no `--output`)**: the full Markdown document (§5) is
  written to stdout, and stdout only — nothing else (no progress text,
  no banner) is written there, so `witnessgraph report ./case >
  file.md` and piping to `diff`/other tools works without extraneous
  content polluting the file. Every determinism guarantee in §7 applies
  to exactly these bytes.
- **`--output PATH` mode**: the identical UTF-8-encoded, LF-only byte
  sequence (§7) that would have gone to stdout is instead written to
  `PATH` via a binary-safe write (never a platform text-mode API that
  could translate newlines) — the file's bytes and the stdout-mode bytes
  for the same case state must be byte-for-byte identical, on Windows,
  Linux, and macOS alike (§7, BLOCKER 2 resolution). This is what makes
  the workflow in §4 (`diff case-report.md restored-report.md`) a
  meaningful reproducibility test: it only proves anything because both
  invocations go through the exact same rendering and byte-writing path
  and differ only in where the result lands. If `PATH` already exists,
  `report` fails before writing anything (does not truncate or partially
  overwrite it) — consistent with `export_case`'s existing
  `FileExistsError` behavior on `output_path.exists()`. On success, a
  short confirmation (e.g. `wrote report to <PATH>`) may be printed to
  stdout in `--output` mode only, since stdout is not the report's
  destination in that mode; this confirmation line is explicitly **not**
  part of the deterministic report content and must never appear when
  writing to stdout directly.
- `--format markdown` (option, optional, default and — for v0.2 — only
  legal value): reserved for a possible future `html`/`json` variant;
  passing anything else is a usage error (`typer.BadParameter`), not a
  silent fallback. Only `markdown` is implemented in v0.2, matching the
  research document's explicit recommendation in its §11 to defer HTML.
- **Exit codes**: `0` on success. Non-zero (`typer.Exit(1)`, matching the
  existing `FileNotFoundError`-surfacing pattern of `Case.open`) if
  `case_dir` is not a valid case, or if `--output` already exists.
  `report` never exits non-zero purely because a case has zero evidence,
  zero hypotheses, etc. — an empty case produces a valid, empty-sectioned
  report (see §14 for what *does* fail).
- **stdout/stderr discipline**: in default mode, the report body is the
  entirety of stdout; in `--output` mode, only the optional short
  confirmation line goes to stdout. In both modes, any error goes to
  stderr, matching every existing command's convention (e.g.
  `entities_show`, `replay`).

### `witnessgraph verify <case_dir> [--report]`

**Responsibility: confirm the case's integrity and reproducibility** —
the workflow-facing command a human runs to answer "is this case
trustworthy right now," as opposed to `replay`'s narrower, low-level
manifest-recomputation role (see §3):

- Recomputes the manifest and compares it to the recorded one, by
  calling the same `replay_and_verify` function `replay` uses
  internally — this is implementation reuse, not `verify` becoming a
  synonym for `replay`; see the responsibility split in §3.
- `--report` (option, optional, default off): additionally regenerate
  the Markdown report (§5) in memory and confirm report generation does
  not raise — this is a *smoke check* that report rendering succeeds
  against the case, not a second reproducibility guarantee (report
  content identity across runs is covered by the determinism contract in
  §7 and tested per §12, not by this flag). This smoke check is the one
  piece of `verify`'s scope that `replay` intentionally does not and
  will not perform, since `replay` is deliberately scoped to the
  manifest alone.
- **Exit codes**: `0` if the manifest matches the recorded one (and, if
  `--report` was given, report generation succeeded). `1` on manifest
  mismatch (same as `replay` today) or on a report-generation exception
  when `--report` is given.
- Output: the same two manifest-hash lines and `MATCH`/`MISMATCH` that
  `replay` already prints, plus (if `--report` was given) a confirmation
  that report generation succeeded.

### `witnessgraph replay <case_dir>` (existing, v0.1, unchanged)

**Responsibility: reproduction of the investigation's derivation
steps** — recompute the provenance manifest directly from the evidence
graph (per `witnessgraph.core.provenance.compute_manifest`) and confirm
it matches the recorded one. This is the project's original, narrowest
reproducibility primitive and remains exactly as it is today; v0.2 does
not modify `replay/replay.py`, its CLI command, or its output in any
way. It is retained specifically because it is useful on its own (e.g.
in scripts or tests that want only the manifest-recompute fact, without
`verify`'s broader workflow framing or its optional report smoke check).

No other CLI surface changes. `entities`, `hypothesis`, `timeline`,
`contradictions`, `export`, `import`, `init`, `ingest` are unchanged.

## 7. Determinism contract

"Deterministic report" means: **given a case directory in a fixed
on-disk state, two separate invocations of `witnessgraph report` — on
the same machine or different machines, at different times, in different
process environments — produce byte-identical output.** Concretely:

- **Ordering**: every collection is sorted by an explicit, stable key
  before rendering (evidence by `id`; normalized events by the existing
  `timeline` sort key, with ties broken by `id`; entities and hypotheses
  by `id`; time assertions within an event by `id`; contradictions by
  `(subject_event_id, assertion_a.id, assertion_b.id)`). Iteration order
  from `store.list_*()` (which is not itself guaranteed stable — see
  `SqliteStore`) is never relied upon directly.
- **Timestamps**: all datetimes in the report are rendered via the same
  canonical UTC ISO-8601 representation `canonical_json_bytes` already
  uses (`witnessgraph.core.ids._json_default`: UTC-normalized,
  `Z`-suffixed), not `str(datetime)` or any locale-dependent formatting.
  The report contains **no wall-clock-dependent content** — no "generated
  at <now>" line, no run-specific timestamp of any kind. If a
  human-facing "when was this report produced" note is ever wanted, it
  must be a separate, explicitly non-diffed line or omitted entirely; for
  v0.2, it is simply omitted.
- **UUIDs/IDs**: `NormalizedEvent`/`Entity`/`Hypothesis`/`TimeAssertion`
  ids are already-assigned random UUIDs from the stored case (per
  `new_object_id`) — the report renders whatever id the object already
  has; it never generates a new id. Two reports of the *same* case
  therefore render the *same* ids (they're stored, not freshly minted at
  report time). This is distinct from the known duplication follow-up
  (§9) — that issue is about re-ingestion creating new stored objects,
  not about report generation being non-deterministic for a fixed store.
- **Dictionary/map ordering**: any `dict` field (`attributes`,
  `identifiers`, `ingest_parameters`) is rendered with its keys sorted,
  never in raw Python dict iteration order.
- **Whitespace/newlines — byte-level contract (corrected after
  adversarial review, BLOCKER 2; see §21):** the report is defined as a
  **UTF-8 encoded byte sequence** using **LF-only line endings (byte
  `0x0A`)**, with no trailing-whitespace variance. This is a byte-level
  requirement, not merely a "logical" convention: the implementation
  must not rely on any platform-dependent text-mode newline translation
  (e.g. Python's universal-newline text-mode writes, which translate
  `\n` to `\r\n` on Windows) to produce or write this content. Both
  destinations defined in §6 — stdout and `--output PATH` — must
  originate from the **same UTF-8-encoded byte sequence**, written via a
  binary-safe path (e.g. encoding the rendered string to UTF-8 bytes and
  writing those bytes directly, rather than through a text-mode API that
  may perform OS-dependent newline translation). This guarantee must
  hold identically on Windows, Linux, and macOS: the same case state
  must produce byte-identical report output regardless of which of the
  three the report is generated on. This is enforced by the byte-level
  test requirement added to §12 (BLOCKER 2 resolution), not merely by
  the golden-fixture comparison alone.
- **Serialization**: field values are rendered via each model's own
  already-deterministic representation where one exists (e.g.
  `TimePrecision` and `HypothesisStatus` render as their `.value`, not
  `repr()`); no field is ever rendered via a non-deterministic `repr()`
  or `str()` of a Python object whose formatting isn't contractually
  stable.
- **Environment-dependent information**: the report contains no hostname,
  username, process id, Python version, OS, or environment variable
  value. `EvidenceItem.source_locator` (the *original* ingestion source
  path/locator, part of the case's own recorded content) is fine to
  include, because it is part of the case's data, not of the environment
  running `report`.
- **Paths**: absolute filesystem paths of the *machine currently running
  `report`* are never rendered (e.g. `case_dir`'s absolute path). Only
  `case_dir`'s final path component (its directory name) and paths that
  are themselves case content (`EvidenceItem.source_locator`, which
  records where evidence was originally collected from, at ingest time —
  a property of the case, not of wherever it happens to be re-verified)
  appear. See §13 for the security rationale.
  **Strengthened after adversarial review (MAJOR 6; see §21):** stored
  string fields that happen to look like filesystem paths — in
  particular `EvidenceItem.source_locator`, and any `ProvenanceRecord`
  fields that carry one — are **opaque stored text** for rendering
  purposes. The renderer must emit them exactly as stored, character for
  character, and must **never** pass them through `pathlib.Path`,
  `os.path`, or any other platform-aware path-normalization API before
  display. Doing so would silently reintroduce nondeterminism: a stored
  value such as `C:\Users\alice\case\events.jsonl:12` (produced by
  ingesting on Windows) could be re-normalized differently depending on
  which OS later runs `report`, breaking the "same on Windows, Linux,
  and macOS" byte-level guarantee this section otherwise establishes,
  for a field the case itself already fixed the exact text of at ingest
  time. The same stored string must render identically regardless of
  which operating system runs `report`.
- **Locale/timezone**: rendering never consults the host's locale or
  local timezone; all datetime rendering is explicit UTC as above,
  independent of `TZ` or system locale settings.
- **Generated timestamps**: none appear anywhere in the report body
  (reiterating the timestamps bullet above for emphasis, since this is
  the single most common way "deterministic" reports silently fail in
  practice).

## 8. Integrity contract

Four distinct concepts, kept explicitly separate:

1. **Evidence content hashes**: `EvidenceItem.raw_content_hash` (== `id`)
   — the SHA-256 of one piece of raw evidence's exact bytes. Unaffected
   by everything else in this document; unchanged from v0.1.
2. **Provenance**: `EvidenceItem.chain_of_custody`, a append-only,
   non-hashed record of what happened to that evidence (`"ingested"`,
   `"exported"`, `"imported"`, etc.). Explicitly **excluded** from the
   manifest hash (per `core/provenance.py`'s docstring), so it can grow
   over a case's lifetime without ever changing the case's
   reproducibility hash.
3. **Case integrity manifest/hash**: `ProvenanceManifest.manifest_hash`,
   computed by `compute_manifest()` over `EvidenceItem.raw_content_hash`
   plus the canonical content hash of every `NormalizedEvent`, `Entity`,
   `TimeAssertion`, and `Hypothesis` in the store. This is the *only*
   hash `witnessgraph replay`/`verify` compare. v0.2 adds nothing to what
   this hash covers and changes nothing about how it is computed.
4. **Report output**: the Markdown text `witnessgraph report` produces.
   **Not** covered by the manifest hash. This is a deliberate design
   decision (matching the research document's §11 recommendation (a)):
   the manifest scopes to the case's source-of-truth *data*; the report
   is a derived, regeneratable *presentation* of that data. Its fidelity
   is proven by the determinism contract (§7) and the determinism test
   (§12), not by hashing it into the manifest. Concretely: two
   byte-identical cases must produce byte-identical reports (tested), but
   there is no `report_hash` field anywhere in `ProvenanceManifest`, and
   none is added in v0.2.

**What is and is not covered by the case integrity hash, explicitly.**
**Corrected after adversarial review (MAJOR 1; see §21):** this table is
the authoritative scope of what a `MATCH` verdict actually guarantees.
Notably, `EvidenceItem`'s *ingestion metadata* — `collected_at`,
`source_locator`, `source_adapter`, `adapter_version`,
`ingest_parameters`, and `observed_at` — is **not** covered, only the
content bytes are (via `raw_content_hash`). This is an intentional,
pre-existing v0.1 design choice (`core/provenance.py`), not something
v0.2 introduces or is expected to change; v0.2's obligation is only to
disclose this scope honestly wherever the report displays these fields
(§5 item 7), not to alter the hashing architecture:

| Covered by `manifest_hash` | Not covered by `manifest_hash` |
|---|---|
| `EvidenceItem.raw_content_hash` for every evidence item (the evidence's raw bytes) | `EvidenceItem.chain_of_custody` |
| Canonical content hash of every `NormalizedEvent` | `EvidenceItem.collected_at` |
| Canonical content hash of every `Entity` | `EvidenceItem.source_locator` |
| Canonical content hash of every `TimeAssertion` | `EvidenceItem.source_adapter` / `adapter_version` |
| Canonical content hash of every `Hypothesis` | `EvidenceItem.ingest_parameters` |
| | `EvidenceItem.observed_at` |
| | Report output (any format) |
| | CLI invocation history / logs |
| | `case_dir`'s name/location |
| | Which machine/OS produced a report |

## 9. Reproducibility contract

After **export → import**, the following must be identical between the
original case and the imported copy (this is already true in v0.1 and is
not changed by v0.2 — it is restated here because §12 adds explicit tests
for it in the context of `report`):

- `case.compute_manifest().manifest_hash` (already tested,
  `tests/integration/test_export_import_roundtrip.py`).
- The full, sorted content of every collection (`list_evidence()`,
  `list_normalized_events()`, `list_entities()`, `list_time_assertions()`,
  `list_hypotheses()`) — i.e., not just the aggregate hash matching, but
  the actual objects being present and unchanged, per object.

After **replay/verify**: the recomputed manifest hash must equal the
recorded one (already tested; `verify` reuses `replay_and_verify`
unchanged).

**New for v0.2**: after **fresh report generation**, run twice against
the same on-disk case state (no ingest, no hypothesis changes in
between), `witnessgraph report` must produce byte-identical output both
times, and running it against an imported copy of an exported case must
produce output byte-identical to running it against the original,
pre-export case. This is the report-level restatement of DESIGN.md
principle 4 ("every exported case must be independently reproducible"),
extended from "the manifest hash matches" to "the report, as rendered,
is itself byte-for-byte reproducible." **Corrected after adversarial
review (MAJOR 1; see §21):** this is a claim about *rendering*
reproducibility — the same stored case state always renders the same
report bytes — not a claim that a `MATCH` manifest verdict certifies
every field the report displays. As §8's table and §5 item 7 make
explicit, `EvidenceItem` ingestion metadata (`collected_at`,
`source_locator`, `source_adapter`, `adapter_version`,
`ingest_parameters`, `observed_at`) is displayed in the report but is
*not* manifest-covered, so a `MATCH` verdict does not, by itself, prove
those specific fields are untampered — only that the manifest-covered
content (evidence bytes and every derived object's full canonical
content) is unchanged.

## 10. Data-model impact analysis

| Capability | Impact |
|---|---|
| Evidence inventory in report | Read-only projection of `store.list_evidence()`. No changes. |
| Timeline in report | Read-only projection of `store.list_normalized_events()` + `store.list_time_assertions()`. No changes. |
| Entity presentation | Read-only projection of `store.list_entities()`. No changes. No new linking capability (explicitly removed, §0). |
| Hypothesis presentation | Read-only projection of `store.list_hypotheses()`. No changes. |
| Contradiction presentation | Reuses `detect_time_contradictions()` unchanged. No changes. |
| Provenance/custody presentation | Read-only projection of `EvidenceItem.chain_of_custody`. No changes. |
| Integrity summary | Reuses `case.compute_manifest()` / `case.load_recorded_manifest()` unchanged. No changes. |
| `verify` command | Reuses `replay_and_verify()` unchanged; adds an optional report-generation smoke check. No changes to `replay/replay.py`'s data types. |
| Report determinism | Requires no new field on any model. Sorting/formatting logic lives entirely in the new report module, not in `core/`. |

**Conclusion: v0.2 requires zero schema changes and zero new persisted
model types.** Every proposed capability is a read-only projection over
existing `Store` protocol methods. This is consistent with the research
document's §7/§8 assessment and is treated here as a hard design
constraint, not just a preference: if a future implementer finds they
need a schema change to build the `report` command as specified above,
that is a signal the implementation has drifted from this spec, not a
green light to add one silently.

## 11. Architecture impact

New files a future implementation phase would add (not created now):

- `src/witnessgraph/report/__init__.py`
- `src/witnessgraph/report/render.py` — pure functions: `Store` (+
  `ProvenanceManifest`) in, deterministic Markdown string out, built with
  standard-library string/`str.join` formatting only (**resolved
  decision, §20 item 1** — no third-party templating dependency). No
  I/O, mirroring the existing purity discipline of `core/` and
  `correlate/`.
- `src/witnessgraph/report/sections.py` (optional split, at the
  implementer's discretion) — one function per report section (§5) to
  keep `render.py` from becoming one large function.

Files a future implementation phase would modify:

- `src/witnessgraph/cli/main.py` — add the `report` and `verify`
  commands, following the existing pattern (`Case.open`, do the read-only
  work, `case.close()`, `typer.echo`/`typer.Exit`).
- `pyproject.toml` — **not expected to change.** Per the resolved
  templating decision (§20 item 1), v0.2 uses only the Python standard
  library for report rendering; a third-party templating dependency is
  not introduced unless a concrete, specific requirement documented
  elsewhere in this specification is found, during implementation, to be
  genuinely unmet by standard-library string building. No such
  requirement is currently identified — §5's report structure (headings,
  lists, tables) is well within what `str`/f-string/`str.join`
  composition can produce deterministically.

No changes anywhere in `src/witnessgraph/core/`, `store/`, `ingest/`, or
`replay/`.

## 12. Test strategy

- **Unit tests** (`tests/unit/test_report_rendering.py`, new): each
  section-rendering function, given a small hand-built `Store` (or a
  fake implementing the `Store` protocol) with a handful of objects,
  produces the expected fragment; covers sorting, empty-section
  rendering, and correct supporting/contradicting evidence separation.
- **Deterministic-output tests**: call `render(store)` twice against the
  same store instance (and, separately, against two logically-identical
  but freshly-constructed stores with the same content) and assert
  identical output strings.
- **Byte-level determinism tests (added per BLOCKER 2 resolution, §21):**
  assert, on the encoded bytes of the report (not just the Python
  string): (a) the byte sequence contains no `\r` (`0x0D`) byte
  anywhere — i.e. LF-only line endings, never CRLF; (b) the byte
  sequence decodes as valid UTF-8; (c) invoking `witnessgraph report`
  with no `--output` (captured stdout bytes) and invoking it with
  `--output PATH` (bytes read back from `PATH`) against the same case
  produce **byte-for-byte identical** content, compared as raw `bytes`,
  not as OS-decoded text. These tests must pass as specified regardless
  of the OS the test suite runs on, and are the concrete test contract
  that makes the "same on Windows, Linux, and macOS" claim in §7
  checkable rather than aspirational.
- **Export/import reproducibility tests** (extends
  `tests/integration/test_export_import_roundtrip.py` or a new sibling):
  build a case, export it, import it, run `report` against both, assert
  byte-identical output (not just equal manifest hashes).
- **Integrity-manifest tests**: assert `report`'s printed integrity
  section's `manifest_hash` matches `case.compute_manifest().manifest_hash`
  independently computed in the test; assert the report's MATCH/MISMATCH
  statement agrees with a directly-called `replay_and_verify`.
- **CLI tests** (`tests/integration/`, using Typer's `CliRunner` the way
  existing CLI behavior is presumably exercised — verify the actual
  pattern in `tests/` before writing new ones, so this reuses whatever
  convention already exists): `witnessgraph report <case>` exits 0 and
  produces the expected content; `--output` to an existing path exits
  non-zero without writing; `witnessgraph verify` exits 0 on a matching
  case and 1 on a tampered/mismatched one (e.g. by hand-editing
  `manifest.json` in a test fixture).
- **Golden/fixture tests**: **resolved decision, corrected after
  adversarial review (see §20, item 4; BLOCKER 1 resolution, §21)** —
  reuse the existing `examples/sample-case/` directory as the anchor for
  the v0.2 report golden test, but do so **without modifying the
  existing v0.1 pipeline's inputs or assertions**. Concretely:
  - `examples/sample-case/data/*` (the files `events.jsonl`,
    `timeline.csv`, `auth.syslog`) and the assertions in
    `tests/integration/test_golden_sample_case.py` (including its
    hard-coded evidence counts per adapter and its
    `detect_time_contradictions(...) == []` assertion) are **not**
    changed by v0.2. That test continues to exercise exactly the v0.1
    pipeline it exercises today, unmodified.
  - `examples/sample-case/` already populates every collection §5's
    report renders (evidence from three adapters, one entity, one
    supported hypothesis) via its existing data, which is sufficient for
    the report's "happy path" golden coverage without any new data.
  - If, during implementation, a genuine `TimeAssertion` disagreement or
    a `contradicting_evidence` entry is wanted to exercise §5 section 6
    ("Contradictions") or a "contradicted" hypothesis non-trivially in
    the golden report, that data must live in a **new, additional**
    fixture that does not alter `examples/sample-case/data/*` or the
    existing pipeline test — for example, a small, separate data file
    (e.g. `examples/sample-case/data/report-extras.jsonl`) ingested only
    by a new, separate `witnessgraph report`-focused test/fixture (a new
    test file, or a new function in a new module under
    `tests/integration/`), never by
    `test_golden_sample_case_full_pipeline` itself. This new fixture
    mechanism is **specified here, not created now** — its exact shape
    (additional data file vs. a synthetically-constructed `Store` in the
    test) is left to the implementation phase, constrained only by the
    requirement that it must not touch the existing golden pipeline's
    inputs or assertions.
  - The v0.2 golden `report` output fixture (the committed, expected
    Markdown used for byte-for-byte comparison) is a **new** committed
    file (e.g. `tests/integration/fixtures/sample_case_report.md` or
    similar), not a modification of anything the existing pipeline test
    already checks.
- **Malformed/edge-case tests**: an entirely empty case (no evidence, no
  events, no entities, no hypotheses) still produces a valid,
  all-sections-empty report; a case with a `Hypothesis` whose
  `supporting_evidence`/`contradicting_evidence` reference an id that
  happens to no longer resolve to a live object in the store (a
  defensive test for the intentional storage/CLI-boundary validation gap
  noted in DESIGN.md principle 3 and restated in §9 of this doc) is
  rendered without crashing — the report should show the raw
  `EvidenceRef` (`kind`/`id`) it has, not silently drop it or dereference
  it as if guaranteed to exist; a case with a `case.db` file present but
  corrupted/truncated/not a valid SQLite database (added per MAJOR 5,
  §21) causes `report`/`verify` to exit non-zero with a concise
  diagnostic, not an unhandled traceback.
- **Unicode-neutralization tests (added per MAJOR 4 resolution, §21):**
  construct a `Hypothesis.statement` (and, separately, an `Entity`
  identifier value and a `NormalizedEvent` attribute value) containing a
  known Unicode bidirectional-control or zero-width character; assert
  the rendered report contains the fixed, visible placeholder form
  (§13) rather than the raw control character, and that this
  substitution is identical across repeated runs (determinism).

All new tests must keep the existing 78 v0.1 tests passing unmodified,
and must keep `ruff check .` and `mypy --strict src tests` clean, per
the acceptance criteria in §15.

## 13. Security considerations

- **Sensitive evidence**: unchanged threat model from `SECURITY.md` — v0.1
  implements no redaction, and neither does v0.2. `witnessgraph report`
  is a **more** convenient way to expose the *entirety* of a case's
  evidence content (including raw attribute values and source locators)
  in one document than the existing per-object CLI commands were. This
  specification does **not** propose adding redaction in v0.2 (out of
  scope, per the explicit non-goals), but the report's documentation and
  `--help` text must carry the same warning `SECURITY.md` already gives
  for `.wgcase` exports: do not generate or share a report from a case
  you are not comfortable exposing in full.
- **Accidental secret exposure**: because the report is a single,
  easily-shared file (unlike the case directory/SQLite file, which is
  less casually pasted into a chat or ticket), it is the most likely
  future accidental-leak vector for sensitive evidence. No mitigation is
  implemented in v0.2 beyond the documentation warning above — flagged
  explicitly as a real, un-mitigated risk, not silently ignored.
- **Path leakage**: per §7's determinism contract, the report never
  includes the absolute filesystem path of the machine that generated it.
  It does include `EvidenceItem.source_locator`, which is case content
  (where the evidence was originally collected from) and is already
  exported/shared today via `.wgcase`; this is not new exposure, just
  new visibility of existing case data in a more readable format.
- **Untrusted evidence content / report generation from attacker-
  controlled data**: evidence content (`attributes`, `identifiers`,
  free-text `statement`s, `source_locator` strings, etc.) may originate
  from attacker-controlled log lines. The report renderer must treat all
  such strings as **plain text data**, never as executable template
  syntax or shell input. Because v0.2 is Markdown-only (§6) and Markdown
  is rendered by whatever tool the human opens it in (not by
  Witnessgraph itself), the specific risk to guard against in
  implementation is Markdown/structure injection — e.g. an
  attacker-controlled attribute value containing literal Markdown table
  or heading syntax should not be able to corrupt the report's own
  section structure or forge a fake "Integrity summary" section. The
  implementation must escape or fence untrusted content appropriately
  (e.g. render arbitrary evidence values inside code spans/fenced code
  blocks rather than as raw inline Markdown) — this is a concrete
  implementation requirement, not left to the coder's discretion, even
  though the exact escaping mechanism is an implementation detail
  deferred to the coding phase.
- **Unicode visual spoofing — added after adversarial review (MAJOR 4;
  see §21)**: a report is specifically meant to be read and trusted by a
  human, which makes visual (not just structural) text spoofing a
  distinct risk from the Markdown-injection risk above. Attacker-
  controlled text may contain Unicode bidirectional control characters
  (e.g. RLO/LRO/PDF), zero-width characters (e.g. zero-width space/
  joiner), or other non-printing control characters that cause the
  *displayed* text to visually differ from its literal content (the
  "Trojan Source" class of spoofing). The renderer must apply a single,
  deterministic neutralization policy — replacing every Unicode
  bidirectional-control and zero-width/non-printing control character
  (outside of the LF byte defined by §7's byte-level contract) with a
  fixed, visible placeholder (e.g. its `U+XXXX` code point notation, in
  a code span) rather than passing it through unmodified — applied
  uniformly to every untrusted string category rendered in the report:
  evidence metadata values (§5 item 2), entity fields (§5 item 4), event
  attributes (§5 item 3), hypothesis text (§5 item 5), and
  provenance/source strings such as `source_locator` and
  `chain_of_custody` actor/action values (§5 items 2 and 7). This
  neutralization must itself be deterministic (the same input string
  always neutralizes to the same output bytes, per §7) and is
  independently testable (a golden/unit test constructing a string with
  a known bidi-control character and asserting the neutralized,
  placeholder form appears in the rendered output). No general-purpose
  Unicode-security library or subsystem is required — a small,
  self-contained character-class check and substitution in the render
  module is sufficient and is the smallest defensible resolution.
- **Archive/import safety — corrected after adversarial review (MAJOR
  2; see §21):** `witnessgraph verify`/`report` operate on
  already-imported case directories. `import_case`'s only
  currently-implemented protections are (a) refusing to import into a
  non-empty `dest_root` (`FileExistsError`) and (b) whatever
  `zipfile.ZipFile.extractall` itself does with member paths on
  extraction. **v0.1 does not contain any explicit,
  application-level validation of archive member paths before
  extraction** (no manual check against `../`-style traversal or
  absolute-path entries beyond what the standard library's
  `extractall` provides by default). This is a genuine, pre-existing
  security limitation of `import_case`, not a control that has been
  reviewed and confirmed adequate — it must not be described as
  "existing protection" this specification safely depends on. v0.2 does
  not modify `portable.py` and does not fix this limitation; it is
  called out here so the threat model stays honest, and should be
  tracked (e.g. in `SECURITY.md`) as a known gap for a future hardening
  pass, independent of v0.2's own scope.
- **Export symlink/stray-file exposure — added after adversarial review
  (MAJOR 3; see §21):** `export_case` (`portable.py`) packages *every
  file found under the case directory* (`case.root.rglob("*")`) into the
  `.wgcase` archive, not only the files the `Store`/`BlobStore`
  recognize. If the case directory contains unexpected filesystem
  entries — a symlink pointing outside the case directory, or a stray
  file placed there by another process — `zipfile.write` will follow and
  include that content in the exported archive. This is a pre-existing
  v0.1 behavior of `export_case`, treated here as a local-analyst
  filesystem-hygiene risk (the case directory is assumed to be under the
  analyst's own control, per DESIGN.md's local-first threat model) rather
  than something v0.2 introduces or fixes. It must not be assumed away:
  an exported `.wgcase` archive being "portable" and
  manifest-verifiable says nothing about whether the archive's *raw zip
  contents* are limited to recognized case data — v0.2's `report`
  command only ever reads through the `Store` protocol and is therefore
  unaffected by this, but a human reviewing an exported archive's raw
  file listing (outside of `report`) should not assume it contains only
  what the `Store` protocol would enumerate. No general filesystem
  hardening is proposed here; this is a disclosure, not a new
  requirement on `portable.py`.
- **Preserving the local-first threat model**: `report` and `verify` open
  no network connection, read only from the given `case_dir`, and write
  only to stdout or the given `--output` path. Per the resolved
  templating decision (§20 item 1), v0.2 introduces no new runtime
  dependency at all, so there is no third-party code in the report path
  whose network behavior would need separate evaluation; if a future
  version ever did add a templating dependency, it would need to be
  checked against this constraint explicitly before adoption.

## 14. Failure modes and explicit behavior

| Condition | Behavior |
|---|---|
| `case_dir` does not exist / is not a valid case (no `case.db`) | `report`/`verify` exit non-zero with the same `FileNotFoundError`-derived message `Case.open` already raises for every other command; no partial output written. |
| `case.db` **exists but is corrupted, truncated, not a valid SQLite database, or otherwise cannot be queried** (added per MAJOR 5, §21; e.g. a partially-written file, a disk-corrupted copy, or the result of extracting a tampered/corrupted `.wgcase` archive) | `report`, `verify`, and `replay` must fail cleanly: catch the underlying database error at the point a case is opened/first queried, exit non-zero, and print a concise, human-readable diagnostic to stderr (e.g. `error: <case_dir> does not contain a readable Witnessgraph case database`) — **not** an unhandled Python traceback as ordinary CLI behavior. The same requirement applies to `witnessgraph import` when the archive it just extracted turns out to contain such a `case.db`: `import` must not leave the user with a raw traceback either, even though the corruption is only detectable once the extracted database is actually opened/queried. This is specified as a requirement here; the exact exception-handling implementation is deferred to the coding phase, per this document's design-only scope. |
| `--output` path already exists | `report` exits non-zero before writing anything (no partial/truncated file left behind), mirroring `export_case`'s `FileExistsError` behavior. |
| `--format` given a value other than `markdown` | `typer.BadParameter`, non-zero exit, no output. |
| Case has zero evidence/events/entities/hypotheses | `report` succeeds (exit 0) with all sections present and explicitly empty (e.g. "(none)") — an empty case is a valid case, not an error. |
| A `Hypothesis`'s `EvidenceRef` points at an id no longer resolvable in the store | `report` renders the reference's raw `kind`/`id` as-is (does not crash, does not silently omit it) — see the malformed/edge-case test in §12; this is a direct consequence of the intentional storage/CLI-boundary validation gap in DESIGN.md principle 3, not a bug `report` should try to paper over. |
| Recorded manifest missing (`manifest.json` absent — e.g. a case that was never `init`-ed through the current CLI path, or created directly against `Store`) | `report`'s integrity section states "no recorded manifest" rather than a MATCH/MISMATCH verdict; `verify` mirrors `replay`'s existing behavior of treating this as trivially matching (`recorded is None` → `matches = True` in `replay_and_verify`), unchanged. |
| `verify --report` and report generation raises an unexpected exception | Exit 1, with the exception surfaced to stderr; the manifest MATCH/MISMATCH lines (already computed) are still printed first. |

## 15. Acceptance criteria

- `witnessgraph report <case_dir>` runs against the existing, unmodified
  `examples/sample-case/` fixture (and, if used, the new, additional
  fixture data described in §12/§21 BLOCKER 1) and produces a Markdown
  document a human can read and understand without the CLI, containing
  all seven sections from §5.
- `witnessgraph report <case_dir>` writes byte-identical, UTF-8-encoded,
  LF-only content whether invoked in default (stdout) mode or
  `--output PATH` mode, for the same case state, verified by comparing
  raw bytes rather than decoded text, on Windows, Linux, and macOS alike
  (resolved decision, §6/§20 item 3; byte-level contract, §7/§12 BLOCKER
  2 resolution).
- Running `report` twice against the same unmodified case produces
  byte-identical output (determinism test, §12, passes).
- `export` → `import` → `report` on the imported copy produces output
  byte-identical to `report` on the original case (reproducibility test,
  §12, passes).
- `witnessgraph verify` exits 0 on an untampered case and non-zero on a
  case whose recorded manifest has been made to disagree with its actual
  content (integrity-manifest test, §12, passes).
- `witnessgraph replay` continues to behave exactly as it does in v0.1,
  unmodified by this specification.
- **All 78 pre-existing v0.1 tests continue to pass, and none of their
  existing assertions or fixture inputs are modified** — including,
  specifically, `tests/integration/test_golden_sample_case.py` and
  `examples/sample-case/data/*`, which v0.2 must not alter (see §12/§21
  BLOCKER 1). New v0.2 tests and new, additional fixtures may freely be
  added alongside them; `ruff check .` and `mypy --strict src tests`
  remain clean after implementation.
- No new runtime dependency is added (resolved decision, §20 item 1) —
  report rendering uses the Python standard library only.
- No entity-linking capability of any kind exists in the shipped v0.2
  CLI (`entities` subcommands remain exactly `create`/`list`/`show`).

## 16. Non-goals

Restating and confirming the "explicitly out of scope" list from the
project direction, as binding for this specification:

- No AI assistance or LLM-generated conclusions anywhere in `report` —
  it is pure, deterministic templating over already-structured data.
- No web UI or server; `report` output is a static file/stdout stream.
- No graph database.
- No multi-user collaboration or auth.
- No network API.
- No live security-tool collection, live network scanning, malware
  analysis automation, exploitation, or credential collection — none of
  these were in v0.1 and none are introduced here.
- No new ingestion adapters, and no parser-breadth expansion of existing
  ones.
- **No entity-linking automation of any kind** (explicit reversal of the
  research document's proposal — see §0).
- No ML-based correlation.
- No case comparison/diffing (Candidate C from the research document
  remains deferred).
- No multi-tenant service architecture.
- No redaction/scrubbing of sensitive evidence in the report (flagged as
  a real, unmitigated risk in §13, not addressed in v0.2).

## 17. Deferred work / future phases

- Entity linking/resolution (opt-in, human-declared or otherwise) —
  explicitly deferred out of v0.2 (§0); may be reconsidered in a later
  phase with its own dedicated specification.
- HTML report output — deferred (§6); Markdown only for v0.2.
- Case comparison/diffing (research document Candidate C) — deferred
  until a multi-analyst/multi-session story exists.
- Multi-source coverage-gap detection (research document Candidate B) —
  deferred; a genuinely different, larger piece of work from the report/
  reproducibility focus of this spec.
- Redaction/scrubbing of sensitive evidence before report generation —
  deferred; noted as a real risk in §13.
- A decision on whether report content should ever become
  manifest-covered (§8 permanently defers this to "no" for v0.2, but a
  future phase could revisit it if a use case for hashing the report
  itself emerges).

## 18. Known v0.1 follow-ups — status for v0.2

Per the project direction, each is explicitly classified rather than
silently fixed:

1. **NormalizedEvent/TimeAssertion IDs are not content-derived
   (re-ingest duplication risk)**: **constraint, not a blocker.** v0.2's
   own workflow (§4) is a fresh-ingest workflow (`init` → `ingest` once
   per source → ... → `report`); it never re-runs ingest against a
   partially-populated case. As long as the v0.2 example/test cases are
   built via clean, uninterrupted ingest runs (the documented safe
   pattern in `SECURITY.md`), this limitation does not affect `report`'s
   correctness or determinism. It remains tracked in `SECURITY.md` and is
   explicitly **not** fixed as part of this specification or its future
   implementation.
2. **Crash atomicity remains a documented limitation**: **constraint, not
   a blocker.** `report`/`verify` are read-only and do not ingest
   anything, so they cannot themselves produce a partial case. A case
   that is already partially ingested (per the existing limitation) will
   simply be reported on faithfully, as-is — `report` reflects whatever
   state actually exists, consistent with how `replay` already behaves
   in that situation (per `replay/replay.py`'s own docstring: "`replay`
   will accurately reflect whatever partial state actually exists rather
   than silently hiding it"). No fix proposed here.
3. **EvidenceRef/Hypothesis validation remains at the storage/CLI
   boundary**: **constraint, explicitly handled by design in §14's
   failure-mode table**, not a blocker. `report` must render a
   `Hypothesis`'s evidence references as they are stored, without
   assuming referential existence, and the malformed/edge-case test in
   §12 exists specifically to pin down this behavior. No change to the
   validation boundary itself is proposed.

None of the three follow-ups block v0.2 as scoped in this document; all
three remain open, tracked, deliberate limitations.

## 19. Proposed implementation sequence (planning only — not executed)

1. Add `src/witnessgraph/report/render.py` with pure functions for each
   of the seven sections (§5), operating directly on a `Store` +
   `ProvenanceManifest`/`ReplayResult`, with unit tests per section
   (§12) before wiring up the CLI.
2. Add the determinism unit test (call render twice, assert identical
   output) alongside step 1, so determinism is enforced from the first
   commit, not retrofitted.
3. Wire `witnessgraph report` into `cli/main.py` (stdout + `--output`
   + `--format` validation), with CLI-level tests for the failure modes
   in §14.
4. Add `witnessgraph verify` as its own command that calls the existing
   `replay_and_verify` function (proven by a test asserting its manifest
   check agrees with `replay`'s on the same case, since both call the
   same underlying function) and prints the same manifest-hash/
   MATCH-MISMATCH output as `replay`; then add the `--report` smoke
   check on top. `replay` itself is not touched.
5. Add the v0.2 report golden test against the **existing, unmodified**
   `examples/sample-case/` data (resolved decision, §20 item 4, as
   corrected in §21 BLOCKER 1 — not a second *example*, but a new,
   additional test/fixture file that does not touch
   `examples/sample-case/data/*` or
   `tests/integration/test_golden_sample_case.py`'s existing assertions)
   plus a new committed golden `report` output fixture and its
   corresponding test. If contradiction/edge-case coverage is wanted, add
   it via the new, separate fixture described in §12 — never by editing
   the existing pipeline's data or assertions.
6. Add the export/import + report reproducibility integration test
   (§12/§9) as its own step, since it depends on steps 1–3 being done
   first.
7. Add the malformed/edge-case tests (empty case; dangling
   `EvidenceRef`) last, once the "happy path" renderer shape is settled,
   since they mainly guard against regressions introduced while doing
   steps 1–6.
8. Documentation pass: update `README.md`'s Quick Start and Status
   sections to mention `report`/`verify` once implemented (not part of
   this specification's own file changes — this spec only creates
   itself).

Each step above is intended to be its own small, independently
reviewable change in the future implementation phase; none of them are
executed as part of this specification.

## 20. Resolved design decisions

The four design decisions raised as open questions in an earlier pass of
this specification have all been **explicitly resolved** by direct
project-owner decision. None of the following is open; each is now a
binding part of this specification, cross-referenced from the sections
above:

1. **Templating approach — resolved: standard library only.** v0.2 uses
   a minimal, deterministic renderer built from Python standard-library
   string composition (`str`/f-strings/`str.join`, etc.) — see §11. No
   third-party templating dependency is introduced. This is not merely a
   default preference; it is binding unless a future implementer
   discovers a concrete, specific requirement elsewhere in this
   specification that standard-library string building genuinely cannot
   satisfy (none is currently identified — §5's structure is plain
   headings, lists, and tables). If such a requirement is ever found,
   introducing a dependency is a spec-amendment decision, not something
   an implementer decides unilaterally mid-implementation.
2. **`report` vs. `verify` vs. `replay` — resolved: three distinct,
   permanent capabilities, none replacing another.** See §3 and §6 for
   the full, explicit responsibility split:
   - `report` = deterministic, human-readable *projection* of the case's
     content. Performs no verification itself.
   - `verify` = integrity/reproducibility *verification*, the
     workflow-facing command for confirming a case is trustworthy
     (manifest check, optionally a report-generation smoke check).
   - `replay` = reproduction of the investigation's derivation
     steps — the existing v0.1 low-level manifest-recomputation
     primitive, unmodified.

   `verify`'s manifest check is implemented by calling the same
   `replay_and_verify` function `replay` already uses; this is
   implementation-level reuse of a pure function, not one command
   replacing or deprecating another. All three commands ship
   permanently in v0.2; none is a synonym, alias, or eventual
   replacement for another, and no future deprecation of `replay` is
   proposed by this specification.
3. **Report output destination — resolved: stdout by default, `--output`
   for a file, both byte-identical.** See §6 for the full contract:
   `witnessgraph report <case_dir>` writes deterministic Markdown to
   stdout when `--output` is not given. An explicit `--output PATH`
   writes the exact same deterministic byte sequence to `PATH` instead
   (fails without writing if `PATH` already exists). The only
   permissible difference between the two modes is an optional short,
   non-report confirmation line printed to stdout in `--output` mode
   only (e.g. `wrote report to <PATH>`) — the report *content* itself
   must be identical between modes for the same case state, and this is
   a tested acceptance criterion (§15).
4. **Golden fixture ownership — resolved: anchor on the existing
   `examples/sample-case/` example, without modifying its existing v0.1
   data or test assertions.** See §12 and §19 step 5, as corrected by
   the adversarial review (§21, BLOCKER 1). No second, separate golden
   *example* is introduced for v0.2, and the existing fixture's data and
   its existing pipeline test (`test_golden_sample_case_full_pipeline`)
   are **not modified** — that test continues to pass exactly as it does
   in v0.1, unchanged. The existing fixture already ingests from all
   three v0.1 adapters, creates an entity, and proposes/supports a
   hypothesis, which is sufficient to exercise every §5 report section
   for the "happy path" golden report test. If additional data (e.g. a
   genuine time contradiction) is wanted, it is added via a new,
   separate data file and a new, separate test — never by editing
   `examples/sample-case/data/*` or the existing test's assertions.

No design decisions remain open from this specification pass. Any new
design question that arises during future implementation should be
resolved by amending this specification (or a successor document), not
decided silently in code.

## 21. Adversarial review resolutions

An adversarial design review of the specification as it stood before
this section was added found 2 BLOCKER-level and 6 MAJOR-level issues.
All 8 are resolved in this revision, by editing this document only — no
source code, tests, or other project files were touched, and no
implementation has been started. This section is an index into where
each resolution actually lives; it does not duplicate the full reasoning
already inlined at each referenced location.

**BLOCKER 1 — golden fixture / existing test contradiction.** Resolved
by no longer requiring any change to `examples/sample-case/data/*` or to
`tests/integration/test_golden_sample_case.py`'s existing assertions.
The v0.2 report golden test is now specified to use the existing,
*unmodified* `examples/sample-case/` data for its "happy path" coverage,
with any additional data (e.g. a genuine time contradiction) required to
live in a new, separate fixture/test rather than an edit to the existing
one. See §12 ("Golden/fixture tests"), §15 (acceptance criteria, the
"78 pre-existing v0.1 tests" bullet), §19 step 5, and §20 item 4.

**BLOCKER 2 — byte-level determinism.** Resolved by making the
determinism contract an explicit byte-level contract: UTF-8 encoding,
LF-only (`0x0A`) line endings, no platform text-mode newline
translation, and stdout/`--output` required to originate from the same
encoded byte sequence — checkable on Windows, Linux, and macOS. See §7
("Whitespace/newlines — byte-level contract"), §6 (`--output PATH`
mode), §12 ("Byte-level determinism tests"), and §15 (the
byte-identical acceptance bullet).

**MAJOR 1 — integrity summary overstatement.** Resolved by requiring the
report's Integrity Summary to explicitly disclose which displayed
`EvidenceItem` fields are not manifest-covered, correcting §9's closing
claim to be about rendering-reproducibility rather than manifest
coverage, and expanding §8's covered/not-covered table to name every
affected field. No change to the actual v0.1 hashing architecture is
proposed or required. See §5 item 7, §8, and §9.

**MAJOR 2 — zip-slip claim.** Resolved by correcting §13's "Archive/
import safety" bullet to state accurately that `import_case` has no
explicit application-level member-path validation beyond whatever
`zipfile.extractall` provides by default, and that this is a
pre-existing, untouched v0.1 limitation, not a control this
specification depends on. No fix to `portable.py` is proposed or placed
in v0.2's scope. See §13.

**MAJOR 3 — export symlink/stray-file risk.** Resolved by adding an
explicit disclosure to §13 that `export_case` zips every file found
under the case directory, so unexpected symlinks or stray files there
could be included in an exported archive; treated as a pre-existing,
local-analyst filesystem-hygiene risk, not a defect v0.2 introduces or
is required to fix. See §13.

**MAJOR 4 — Unicode visual spoofing.** Resolved by adding an explicit,
deterministic neutralization requirement for Unicode bidirectional-
control and zero-width/non-printing characters in every untrusted
string category the report renders (evidence metadata, entity fields,
event attributes, hypothesis text, provenance/source strings), plus a
corresponding test requirement. No general Unicode-security subsystem is
introduced — a small, self-contained substitution rule is specified as
sufficient. See §13 ("Unicode visual spoofing") and §12
("Unicode-neutralization tests").

**MAJOR 5 — corrupted `case.db`.** Resolved by adding an explicit
failure-mode row requiring `report`, `verify`, `replay`, and `import` to
fail cleanly (non-zero exit, concise diagnostic) rather than surface an
unhandled traceback when `case.db` exists but is corrupted, truncated,
or otherwise unreadable. Not implemented as part of this specification
pass. See §14 and the corresponding entry in §12's malformed/edge-case
tests.

**MAJOR 6 — stored path-like strings.** Resolved by strengthening §7's
"Paths" bullet to require `source_locator` (and any other stored
path-like string) to be treated as opaque text at render time, rendered
exactly as stored, and never reprocessed through `pathlib`/`os.path` or
any platform-aware normalization — closing the specific cross-platform
determinism gap this would otherwise create. See §7.

**Remaining design concerns after this pass:** none rise to BLOCKER or
MAJOR. The MINOR and ACCEPTABLE items from the adversarial review (e.g.
the imprecise claim about `SqliteStore` ordering stability, the omission
of `ingest_parameters` from the evidence inventory, the lack of a
defined convention for rendering absent optional fields, the absence of
a size/performance guard for very large cases, the forward-compatibility
note about `export`/`import` potentially appending custody records in a
future version, and the lack of a machine-readable output mode) were not
required to be resolved by this pass and remain as documented
trade-offs/deferred items; none of them contradict or undermine the
resolutions above.
