# Security & Sensitive-Evidence Handling

Witnessgraph is a defensive/research tool for organizing and reasoning
about evidence you already possess. It is **not** a scanning, exploitation,
credential-harvesting, or persistence tool, and no such capability will be
accepted into this codebase.

## What v0.1 does and does not do

- **No network calls anywhere in the library.** Ingestion adapters only
  read files that already exist on the local filesystem
  (`witnessgraph.ingest.base.SourceDescriptor`). There is no adapter, CLI
  command, or code path that opens an outbound connection, scans a host,
  or acts on a live target.
- **No network listener in the core engine.** `core/`, `store/`,
  `ingest/`, `correlate/`, and `replay/` never open a listener; the CLI
  is a local process. The UI v1 milestone adds one explicit, narrowly
  scoped exception: `witnessgraph.api`, a local-only FastAPI server that
  binds to `127.0.0.1` only (never `0.0.0.0` or a public interface),
  serves exactly one case directory chosen at process startup (never
  from a request), and is started manually by the user
  (`witnessgraph-api <case_dir>`) — it is never started automatically,
  and no other part of the engine imports or depends on it. See
  `docs/phase-ui-v1-implementation.md` for the full security boundary.
- **No telemetry.** Nothing is ever sent anywhere.
- **No credential harvesting or exploitation capability**, automated or
  otherwise.

## Ingestion crash atomicity

Ingesting a source (`witnessgraph ingest ...`) wraps every evidence item,
normalized event, and time assertion that one adapter invocation produces
into a single SQLite transaction (`witnessgraph.ingest.pipeline.ingest_source`,
via `Case.transaction()`). **One `ingest` invocation is the atomic unit**:
if the process is killed partway through ingesting a multi-record source
(a crash, an out-of-memory kill, `Ctrl-C`), the SQLite metadata for that
invocation is rolled back in full rather than left partially committed.

The one piece of state that sits outside this transaction is the
content-addressed blob store: `case.blobs.put(raw_bytes)` is called for
each record *before* that record's SQLite writes, since a filesystem
write cannot itself participate in a SQLite transaction. This ordering is
deliberate and safe: `FileBlobStore.put` is self-idempotent
(content-addressed, stage-to-temp-then-atomic-rename), so a crash after a
blob write but before the SQL transaction commits leaves at most a
harmless orphaned blob file with no metadata row pointing at it yet —
never a metadata row referencing a blob that was never written.

**Re-running an interrupted ingest is safe.** Because `EvidenceItem`,
`NormalizedEvent`, and `TimeAssertion` ids are all content-derived
(re-deriving the same input reproduces the same id) and blob writes are
idempotent, simply re-running `witnessgraph ingest` with the same source
after an interruption converges rather than duplicates: already-committed
records are re-derived to the same ids/blobs and become no-ops, and only
genuinely new records are newly written. There is no need to discard and
restart from an empty case directory.

## Sensitive evidence — read this before ingesting real data

Evidence you ingest (logs, timelines, etc.) may contain secrets, personal
data, or other sensitive material. **Witnessgraph v0.1 implements no
redaction of any kind.** Raw evidence bytes are stored, content-addressed
and unmodified, exactly as provided. If you ingest a file containing
credentials or PII, that file's contents will be stored verbatim in the
case's blob store and will appear verbatim in any exported `.wgcase`
archive.

Do not ingest evidence into a Witnessgraph case unless you are comfortable
with its contents being stored and exported as-is. Redaction/scrubbing is
a real, useful feature for a future version — it is explicitly **not**
implemented here, and no part of this codebase should be read as implying
it exists.

## Untrusted archive import (`.wgcase`, case packages)

Both `witnessgraph import` (a `.wgcase` archive) and
`witnessgraph case-package import`/`validate` (a `case.json` or
`.witnessgraph-case` archive) may be handed a file from another
researcher and must treat it as untrusted input:

- **`.wgcase` import** (`witnessgraph.portable.import_case`) validates
  every archive member's path resolves strictly inside the destination
  directory before extracting anything (rejecting absolute paths, `..`
  traversal, or a drive change), and enforces both a per-member and a
  total uncompressed-size ceiling — checked from the zip's central
  directory *before* any bytes are decompressed — to bound a
  decompression-bomb archive's worst-case disk usage. See
  `tests/integration/test_portable_security.py`.
- **Case package import** (`witnessgraph.casepkg`) never calls
  `zipfile.extractall` at all: the `.witnessgraph-case` archive format
  reads exactly two fixed, hard-coded member names by name and ignores
  everything else, so there is no code path that turns a zip-entry name
  into a filesystem path in the first place. A declared archive
  member's uncompressed size is also capped before decompression, and
  the archive's recorded content hash is verified against the actual
  `case.json` bytes read, so a corrupted or tampered archive is
  detected before its contents are trusted. A case package's own
  content (evidence bytes, object counts) is separately capped
  (`docs/research/witnessgraph-case-format.md`'s "size and count
  limits"), and no participant/researcher-supplied string is ever used
  to build a filesystem path outside a case's own fixed directory
  layout. See `tests/integration/test_portable_security.py` and
  `tests/unit/test_casepkg_build.py`.

Neither import path ever executes anything from the archive/package —
only the documented JSON/SQLite data formats are parsed.

## Test and example data

All fixtures under `tests/fixtures/`, `examples/sample-case/data/`, and
`research/examples/sample-researcher-case/` are entirely synthetic,
hand-authored data. No real logs, credentials, IPs, hostnames, or
personal data of any kind are used anywhere in this repository.

## Reporting a vulnerability

This is a young project without a dedicated security contact yet. Please
open an issue describing the problem in general terms and avoid including
exploit details in a public issue.
