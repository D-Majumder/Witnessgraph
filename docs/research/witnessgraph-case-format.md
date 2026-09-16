# Witnessgraph Case Package Format

A case package is a single, human-authorable file (`case.json`, or a
`.witnessgraph-case` archive wrapping one) that declares a whole
Witnessgraph case in one place, as an alternative to running many
individual `witnessgraph entities create` / `relationships create` /
`ingest` commands. It is implemented by `witnessgraph.casepkg`
(`src/witnessgraph/casepkg/`) and validated/imported/exported by the
`witnessgraph case-package` CLI group.

This document is the schema reference. See
`docs/research/witnessgraph-researcher-guide.md` for the full workflow
and `docs/research/witnessgraph-quickstart.md` for a fast path from
nothing to an opened case.

## Two portable formats, not one

Witnessgraph now has **two** distinct portable case formats, for two
different purposes — this document is about the second one:

| Format | What it is | When to use it |
| --- | --- | --- |
| `.wgcase` (`witnessgraph export`/`import`, `witnessgraph.portable`) | A byte-for-byte archive of an *already-built* case's SQLite database and blob store. | Handing an exact, already-analyzed case to another researcher for independent verification (DESIGN.md principle 4). Not meant to be hand-edited. |
| Case package (`case.json` / `.witnessgraph-case`, `witnessgraph.casepkg`, **this document**) | A declarative, human-readable JSON description of a case's contents. | **Authoring** a new case from your own data, or sharing a case in a form another researcher can read, diff, and hand-edit before importing. |

Both round-trip: export a case, reimport it, and you get back a case
with the exact same provenance manifest hash (`witnessgraph verify` /
`case-package import` both print it). Use `.wgcase` when you want an
exact binary copy; use a case package when you want something you can
read, review, or write by hand.

## File layout

A case package is either:

- a plain `case.json` file (read/write it in a text editor directly); or
- a `*.witnessgraph-case` archive: a zip containing exactly two members,
  `case.json` and `manifest.json` (`{"schema_version", "package_version",
  "content_sha256", "witnessgraph_version"}`), where `content_sha256` is
  the SHA-256 of `case.json`'s exact bytes. `case-package validate`/
  `import` verify this hash before trusting the archive's `case.json` at
  all — this is what lets you (or another researcher) verify "this is
  exactly the package that was analyzed." `case-package export` always
  produces this hash correctly; never hand-edit `manifest.json` and
  expect the result to still validate.

Which one you get from `case-package export`/`init` is decided by the
output path's extension: `.witnessgraph-case` writes the archive form;
anything else (conventionally `.json`) writes plain JSON.

## Top-level fields

```json
{
  "schema_version": 1,
  "package_version": "1.0.0",
  "case_metadata": { "title": "...", "description": "...", "created_by": "...", "created_at": "2026-01-01T00:00:00Z" },
  "evidence_items": [ ... ],
  "normalized_events": [ ... ],
  "entities": [ ... ],
  "relationships": [ ... ],
  "time_assertions": [ ... ],
  "hypotheses": [ ... ]
}
```

- `schema_version` (int, required): must equal the schema version this
  installation supports (currently **1**, `CASE_PACKAGE_SCHEMA_VERSION`
  in `casepkg/schema.py`). An older/newer value is rejected outright —
  there is no silent up/downgrade.
- `package_version` (string, required): a researcher-chosen free-form
  version label for *this specific package's content* (e.g. `"1.0.0"`,
  `"2026-01-pilot"`) — distinct from `schema_version`. Not interpreted
  by Witnessgraph; yours to define a convention for.
- `case_metadata`: `title`/`created_by`/`created_at` required,
  `description` optional. Purely descriptive — never affects import
  behavior or the resulting provenance manifest.
- Every other field is a list, defaulting to empty, described below.
  **Unrecognized top-level fields are rejected**, not ignored — most
  importantly, this means a `findings`/`contradictions`/`gaps` block is
  always rejected: those are system-derived analysis (see the section
  below), never something a package can declare.

All six declared-object lists are processed **in the fixed order shown
above**: `evidence_items`, then `normalized_events`, then `entities`,
then `relationships`/`time_assertions`/`hypotheses` (which may
interleave freely with each other). A reference to an object declared
*later* in the file, or in a list processed later, is always rejected —
there is no forward-reference resolution.

## `local_id`: package-internal references

Every declared object carries a `local_id` — a string you choose,
unique within the file, used only to reference that object *from
elsewhere in this same package* (`derived_from`, `source_entity`/
`target_entity`, `subject_event`/`source_evidence`, hypothesis evidence
refs).

- For **evidence_items** and **normalized_events** (content-addressed
  types), `local_id` is *only* a reference key. The object's real,
  final Witnessgraph id is always derived from its content (a SHA-256
  hash for evidence, a content hash of identity fields for normalized
  events) — exactly as every other ingestion path in this codebase
  already computes it. You will not see your chosen `local_id` in the
  imported case's actual ids for these two types.
- For **entities** and **hypotheses** (not content-addressed),
  `local_id` *becomes the literal stored id* directly. This is
  deliberate: it is what makes export-then-reimport reproduce the exact
  same entity/hypothesis ids, and it lets you pick one memorable string
  (e.g. `"host-a"`) and reuse it everywhere in the file. `local_id` is
  optional for a hypothesis (a random id is assigned if omitted) and
  required for an entity.
- **relationships** and **time_assertions** accept an optional
  `local_id` purely for your own bookkeeping/error-message clarity — it
  is never used as their stored id, since both are content-addressed.

A duplicate `local_id` anywhere in the file is rejected. A reference
that does not resolve to an earlier `local_id` of the expected kind is
rejected, with an explicit message naming the missing id — never
silently dropped or auto-created.

## Object fields

### `evidence_items[]`

| Field | Required | Notes |
| --- | --- | --- |
| `local_id` | yes | Reference key only (see above). |
| `content` | exactly one of `content`/`content_base64` | Evidence bytes as UTF-8 text. |
| `content_base64` | exactly one of `content`/`content_base64` | Evidence bytes, base64-encoded — use this for binary content or text that is not valid UTF-8. |
| `source_locator` | yes | Where this evidence came from, e.g. `"case1/incident.jsonl:12"`. Free text. |
| `collected_at` | yes | ISO-8601 timestamp, timezone-aware (see "Timestamps" below). |
| `observed_at` | no | ISO-8601 timestamp, if different from `collected_at`. |
| `source_id` | no | An explicit, researcher-declared common-source identity (see `docs/phase4-v0.4-source-identity-design.md`) — never inferred. |
| `ingest_parameters` | no | Free-form `{string: string}` map. |

The resulting `EvidenceItem.id` is always the SHA-256 hash of the exact
bytes you supplied (DESIGN.md principle 1) — two evidence items with
identical content always converge to the same stored id, exactly as two
identical ingested log lines would. `EvidenceItem.source_adapter` is
recorded as `"researcher-case-package"`, so it is always possible to
tell apart evidence a researcher declared directly in a case package
from evidence an ingestion adapter produced from a raw source file.

### `normalized_events[]`

| Field | Required | Notes |
| --- | --- | --- |
| `local_id` | yes | Reference key only. |
| `event_type` | yes | Free-form label, e.g. `"login"`. |
| `derived_from` | yes, non-empty | `local_id`(s) of earlier `evidence_items`/`normalized_events`. |
| `attributes` | no | Free-form `{string: string}` map. |
| `created_at` | yes | ISO-8601 timestamp. |

### `entities[]`

| Field | Required | Notes |
| --- | --- | --- |
| `local_id` | yes | **Becomes the literal `Entity.id`.** |
| `entity_type` | yes | Free-form label, e.g. `"host"`, `"user"`, `"ip"`. |
| `identifiers` | no | Free-form `{string: string}` map, e.g. `{"hostname": "ws-01"}`. |
| `derived_from` | yes, non-empty | `local_id`(s) of `evidence_items`/`normalized_events` establishing this entity. |
| `first_seen` / `last_seen` | no | ISO-8601 timestamps. |

### `relationships[]`

| Field | Required | Notes |
| --- | --- | --- |
| `local_id` | no | Bookkeeping only. |
| `relationship_type` | yes | Free-form label, e.g. `"connected_to"`. |
| `source_entity` / `target_entity` | yes | `local_id`(s) of two **different** declared entities — directed, source → target. |
| `derived_from` | yes, non-empty | `local_id`(s) of `evidence_items`/`normalized_events`. |
| `attributes` | no | Free-form `{string: string}` map. |
| `created_at` | yes | ISO-8601 timestamp. |

### `time_assertions[]`

| Field | Required | Notes |
| --- | --- | --- |
| `local_id` | no | Bookkeeping only. |
| `subject_event` | yes | `local_id` of a declared `normalized_events` entry. |
| `value` | yes | ISO-8601 timestamp — the claimed time. |
| `precision` | yes | One of `exact`, `second`, `minute`, `hour`, `day`, `approximate`. |
| `source_evidence` | yes | `local_id` of a declared `evidence_items` entry. |
| `asserted_by` | yes | Free text identifying who/what is making this claim. |
| `created_at` | yes | ISO-8601 timestamp. |

### `hypotheses[]`

| Field | Required | Notes |
| --- | --- | --- |
| `local_id` | no | If given, becomes the literal `Hypothesis.id`. |
| `statement` | yes | The claim, in your own words. |
| `status` | no (default `proposed`) | One of `proposed`, `supported`, `contradicted`, `withdrawn`. |
| `supporting_evidence` / `contradicting_evidence` | at least one across both, required | Each entry: `{"kind": "evidence_item" \| "normalized_event", "local_id": "..."}`. |
| `inferred_by` | yes | Free text identifying who/what is making this claim. |
| `created_at` | yes | ISO-8601 timestamp. |

## Declared fact vs. system-derived analysis vs. researcher hypothesis

This distinction is load-bearing, not cosmetic (DESIGN.md principle 3),
and the importer enforces it structurally, not by convention:

- **Declared fact**: `evidence_items`, `normalized_events`, `entities`,
  `relationships`, `time_assertions`. Each is *your* explicit assertion
  that you observed this, backed by an explicit `derived_from`/
  `source_locator`/`source_evidence` pointing at what you observed it
  from — exactly what every other Witnessgraph ingestion path already
  requires. The importer never infers one of these from another (a
  filename is never turned into evidence provenance, a note is never
  turned into an entity, graph adjacency is never turned into an
  implied relationship, and a *missing* record is never turned into
  negative evidence of anything).
- **Researcher hypothesis**: `hypotheses`. A `Hypothesis` can only ever
  reference evidence (`supporting_evidence`/`contradicting_evidence`) —
  it is structurally incapable of asserting a bare, evidence-free fact.
  It is never treated as more authoritative than what it cites.
- **System-derived analysis**: findings, contradictions, and gaps. These
  are *computed* by `witnessgraph.correlate` from an already-imported
  case (`witnessgraph contradictions`, `witnessgraph gaps`,
  `witnessgraph findings`/`contradiction-findings`) — **a case package
  cannot declare them**. Any `findings`/`contradictions`/`gaps` key in
  `case.json` is rejected at parse time (the schema forbids unrecognized
  top-level fields), specifically so a researcher cannot smuggle a
  precomputed "result" in as if it were input data.

## Timestamps

Every timestamp field must be an ISO-8601 string with an explicit
timezone offset (e.g. `"2026-01-01T00:00:00Z"` or
`"2026-01-01T00:00:00+05:30"`). A naive (timezone-less) timestamp is
rejected — Witnessgraph never guesses a timezone (DESIGN.md principle
3), the same rule every ingestion adapter already follows.

## Size and count limits

Applied before any hashing/storage work, to bound a hostile or
malformed package's worst-case resource use — not claimed to be the
objectively correct limits for every deployment, only safe defaults
(`casepkg/build.py`):

- One evidence item's `content`/`content_base64`, decoded: **50 MB**.
- Total declared objects across all six lists in one package:
  **200,000**.
- A `.witnessgraph-case` archive member's declared uncompressed size:
  **200 MB** (checked from the zip's central directory *before*
  decompressing anything — see `casepkg/archive.py`'s security note).

## Validation vs. import

`case-package validate <package>` runs the exact same resolution logic
`case-package import` does (`casepkg/build.py`), but never touches a
filesystem `Case` — it can never disagree with what an import would
actually produce, and it never modifies the file it is checking.
`case-package import` only ever creates a new case directory if
validation succeeded in full; an invalid package leaves no partial case
behind.

## Example

See `research/examples/sample-researcher-case/` for a complete,
synthetic worked example, and run
`witnessgraph case-package init <path>` for a minimal starting template.
