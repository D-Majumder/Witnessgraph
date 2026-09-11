# Witnessgraph — v0.1 Design Principles

Witnessgraph is an evidence-first, reproducible cybersecurity investigation
platform. Its thesis: **investigations should be reproducible from evidence,
not dependent on opaque conclusions.** The following seven principles are
locked for v0.1. Every module's docstring that implements one of them points
back here; if code and this document ever disagree, this document wins and
the code has a bug.

## 1. Evidence is immutable

Once an `EvidenceItem` is created, its content can never change. Its `id` is
the SHA-256 hash of the exact raw bytes it represents
(`witnessgraph.core.evidence.EvidenceItem`), so a modified copy is, by
construction, a *different* object with a different id — never a mutation of
the original. Pydantic models for evidence are frozen. Blob storage
(`witnessgraph.store.sqlite_store.FileBlobStore`) never overwrites an
existing file at a content address.

## 2. Every derived object has explicit lineage

`NormalizedEvent` and `Entity` each carry a non-empty `derived_from` field
referencing the `EvidenceItem`/`NormalizedEvent` id(s) they came from,
enforced by validation, not convention. There is no way to construct a
derived object that doesn't point at what it was derived from.

## 3. Observed evidence and analyst/engine inference are different object types

`EvidenceItem`/`NormalizedEvent`/`Entity`/`TimeAssertion` represent what was
observed. `Hypothesis` represents a claim *about* what was observed, and is a
structurally distinct type that can only ever reference evidence — it cannot
assert a bare fact. Adapters never guess at ambiguous data (e.g. a
timestamp with no timezone is left unparsed rather than assumed).

Note on referential existence: a `Hypothesis`/`EvidenceRef` is validated to
have the right *shape* (it must reference at least one id, of a known kind)
at construction time, but `core/` has no I/O (principle 6) and so cannot
itself confirm that a referenced id exists in some case's store. That check
happens one layer up, at the CLI (`witnessgraph.cli.main._resolve_evidence_ref`)
today. This is an intentional boundary, not a gap that was missed.

## 4. Every exported case must be independently reproducible

A case is one portable directory (SQLite metadata + content-addressed
blobs). Exporting packages it as a single `.wgcase` archive; importing it
elsewhere and recomputing its provenance manifest must produce the exact
same manifest hash as the original. This is directly tested
(`tests/integration/test_export_import_roundtrip.py`) and directly
demonstrated by `examples/sample-case`.

## 5. Provenance is cryptographically verifiable

All hashing is over a deterministic canonical serialization
(`witnessgraph.core.ids.canonical_json_bytes`): sorted keys, fixed
separators, UTC-normalized timestamps. A case's `ProvenanceManifest`
(`witnessgraph.core.provenance`) is a sorted hash-of-hashes over every
evidence item, normalized event, entity, time assertion, and hypothesis —
anyone holding the case directory can recompute it themselves with no need
to trust a stored value. This is what `witnessgraph replay` does.

## 6. The core library is local-first and has no network listener

Witnessgraph v0.1 opens no sockets, runs no server, and makes no outbound
network calls anywhere in `core`, `store`, `ingest`, `correlate`, or
`replay`. Adapters only read files that already exist on the local
filesystem (`witnessgraph.ingest.base.SourceDescriptor`). See `SECURITY.md`
for the full boundary.

## 7. AI is not part of v0.1 and cannot be authoritative over evidence

There is no AI/assistant integration in this version, full stop. The
`Hypothesis.inferred_by` field exists specifically so that if a future
version adds an assistant, it can only ever *propose* a `Hypothesis`
attributed to itself — there is no code path, now or by design, that lets
any inference (human or automated) silently become evidence.
