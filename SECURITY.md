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
- **No network listener.** The CLI is a local process; there is no server
  mode in v0.1.
- **No telemetry.** Nothing is ever sent anywhere.
- **No credential harvesting or exploitation capability**, automated or
  otherwise.

## Known limitation: ingestion is not crash-atomic

Ingesting a source (`witnessgraph ingest ...`) writes each evidence item,
normalized event, and time assertion to the SQLite metadata store as its
own committed write, one at a time, as the adapter produces them. If the
process is killed partway through ingesting a multi-record source (a
crash, an out-of-memory kill, `Ctrl-C`), the case will contain whatever
records were written before the interruption and nothing after it --
**a genuinely partial case, not an all-or-nothing outcome.**

This is a real, current limitation, not a hypothetical one: v0.1 does not
wrap a multi-record ingest in a single database transaction. Nothing else
in this codebase should be read as claiming otherwise. Two things *are*
still true even in a partially-populated case: every record that *is*
present is exactly as trustworthy as in a complete case (content-addressed,
immutable), and `witnessgraph replay` will accurately reflect whatever
partial state actually exists rather than silently hiding it — but the
case as a whole is not a complete, faithful copy of the source until a
full ingest run has finished without interruption.

**Do not simply re-run an interrupted ingest as a fix.** Re-ingesting the
same source is a safe, non-duplicating no-op only at the raw-evidence
layer (`EvidenceItem` ids are content hashes, and the store merges rather
than duplicates — see its docstring). `NormalizedEvent` and
`TimeAssertion` ids are freshly generated on every construction, not
derived from content, so re-running ingest against a source that was
already partially ingested will currently create *duplicate* normalized
events and time assertions for whatever portion succeeded the first time.
There is no dedup step for those object types in v0.1. If an ingest is
interrupted, the safest recovery today is to discard the partial case
directory and start over from an empty one, not to re-run ingest in place.

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

## Test and example data

All fixtures under `tests/fixtures/` and `examples/sample-case/data/` are
entirely synthetic, hand-authored data. No real logs, credentials, IPs,
hostnames, or personal data of any kind are used anywhere in this
repository.

## Reporting a vulnerability

This is a young project without a dedicated security contact yet. Please
open an issue describing the problem in general terms and avoid including
exploit details in a public issue.
