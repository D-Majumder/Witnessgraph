# Witnessgraph

An evidence-first, reproducible cybersecurity investigation platform.

> Cybersecurity investigations should be reproducible from evidence, not
> dependent on opaque conclusions.

Witnessgraph is a **local-first, defensive/research** tool: it ingests
evidence you already have, keeps it immutable and content-addressed,
represents hypotheses as explicitly evidence-backed claims (never bare
facts), and lets a case be exported, handed to someone else, and
independently reproduced — provenance hash and all.

The core object model (evidence, provenance, hypotheses) was locked at
v0.1 and has not changed since; everything built on top of it —
contradiction detection, coverage-gap analysis, tracked findings,
analyst-declared time assertions, JSON reporting, directed relationships
between entities, and bounded graph traversal — is additive. See
`DESIGN.md` for the locked architectural principles and `SECURITY.md`
for what this tool does and does not do.

## Install (development)

```sh
python -m venv .venv
.venv/Scripts/activate   # or: source .venv/bin/activate
pip install -e ".[dev]"
```

### Python version

Witnessgraph v0.1 targets **Python 3.11+**. This is a deliberate baseline,
not an oversight: the code uses no syntax newer than 3.11 (the one place
this matters in tooling is `ruff`'s `UP042` check, which is disabled with
an inline explanation, since `enum.StrEnum` isn't available before 3.12).
If your environment has 3.12+ available, Witnessgraph runs fine there too
— the floor is 3.11, not a ceiling.

## Quick start

```sh
witnessgraph init ./my-case
witnessgraph ingest ./my-case jsonl ./events.jsonl --source-id host-a
witnessgraph timeline ./my-case
witnessgraph contradictions ./my-case
witnessgraph gaps ./my-case --min-gap-seconds 300
witnessgraph entities create ./my-case host --derived-from <evidence-id> --id hostname=host-a
witnessgraph relationships create ./my-case connected_to \
  --source <host-entity-id> --target <ip-entity-id> --derived-from <evidence-id>
witnessgraph hypothesis propose ./my-case "the statement" --evidence <id>
witnessgraph report ./my-case
witnessgraph export ./my-case ./my-case.wgcase
witnessgraph import ./my-case.wgcase ./my-case-restored
witnessgraph verify ./my-case-restored
```

See `examples/sample-case/` for a full worked example, and `--help` on
any command (or command group) below for the exact options.

## Status

The core object model (evidence, provenance, hypotheses) is stable at
v0.1 (`DESIGN.md`'s seven locked principles). Everything else below was
added afterward, in the same evidence-first style, and is exercised by
582 tests. There is no AI integration, no graph database, and no web
UI — this is deliberately a local CLI over a SQLite + content-addressed
store; see `DESIGN.md` for what stays out of scope by design.

### CLI reference

| Command | Purpose |
| --- | --- |
| `init` | Create a new, empty case directory. |
| `ingest <case> <adapter> <source> [--source-id]` | Ingest one evidence source (`jsonl`, `csv_timeline`, or `syslog`) into a case, optionally under an analyst-declared source identity. |
| `timeline` | Print all normalized events, ordered by earliest known time. |
| `entities create / list / show` | Create and inspect entities explicitly linked to the evidence that established them. |
| `relationships create / list / show [--entity]` | Create and inspect directed, evidence-backed relationships (graph edges) between two entities. |
| `graph neighbors <entity> [--max-depth] [--direction]` | List every entity reachable from one entity within a bounded number of hops. |
| `graph path <source> <target> [--max-depth] [--direction]` | Find one deterministic, shortest relationship chain between two entities, with full provenance. |
| `time-assertions create` | Record one analyst's explicit, cited claim about when an event occurred. |
| `hypothesis propose / support / contradict / list` | Manage evidence-backed hypotheses — never bare, unsupported claims. |
| `contradictions [--track]` | Report structural `TimeAssertion` contradictions, optionally persisting each as a tracked finding. |
| `gaps --min-gap-seconds [--refine-source-by-attribute] [--track]` | Report deterministic cross-source evidence coverage gaps between analyst-declared sources. |
| `findings list / show / ack` | Inspect and annotate persisted, tracked gap findings. |
| `contradiction-findings list / show / ack` | Inspect and annotate persisted, tracked contradiction findings. |
| `report [--format markdown\|json] [--output]` | Render a case's full investigative content as one deterministic document. |
| `export` / `import` | Package a case into a portable `.wgcase` archive and restore it elsewhere. |
| `verify [--report]` | Recompute a case's provenance manifest and confirm it matches the recorded one. |
| `replay` | Recompute and verify a case's provenance manifest (used internally by `verify`). |

## Project structure

```
src/witnessgraph/
├── core/        # Frozen data model: evidence, events, entities, relationships, hypotheses, provenance
├── store/       # SQLite metadata store + content-addressed blob store
├── ingest/      # Source adapters (jsonl, csv_timeline, syslog) and the ingest pipeline
├── correlate/   # Contradiction detection, coverage-gap analysis, graph traversal
├── replay/      # Provenance manifest recomputation/verification
├── report/      # Deterministic Markdown/JSON report rendering
├── cli/         # Typer CLI wiring the above into `witnessgraph`
└── portable.py  # .wgcase export/import
```

## Relationships

Witnessgraph's data model has always had a graph's *nodes* (`Entity`)
but, through v1.0, no *edges* — no way to record that two entities were
observed to be connected. `Relationship` (v1.1) closes that gap: a
directed, evidence-backed claim that a source entity and a target entity
are related, with the same discipline as everything else in
Witnessgraph — it must cite the evidence it is grounded in, it is never
inferred automatically, and it is immutable once created.

This exists because an investigation is rarely about isolated facts —
it's about how entities relate (a host connected to an IP, a user
authenticated on a host, a process that spawned another process).
Recording those connections explicitly turns a case from a list of
individually-supported claims into an explorable graph, without
compromising the evidence-first model everything else here follows.

```sh
witnessgraph entities create ./my-case host --derived-from <ev-id> --id hostname=corp-ws-1
witnessgraph entities create ./my-case ip --derived-from <ev-id> --id address=203.0.113.7
witnessgraph relationships create ./my-case connected_to \
  --source <host-entity-id> --target <ip-entity-id> \
  --derived-from <ev-id> --attribute protocol=tcp
witnessgraph relationships list ./my-case
witnessgraph relationships list ./my-case --entity <host-entity-id>
witnessgraph relationships show ./my-case <relationship-id>
```

`relationships show` output:

```json
{
  "id": "3f9c1e...",
  "relationship_type": "connected_to",
  "source_entity_id": "c0000000-...-01",
  "target_entity_id": "c0000000-...-02",
  "attributes": {"protocol": "tcp"},
  "derived_from": ["23da92a4..."],
  "created_at": "2026-01-01T12:00:00Z"
}
```

Relationships appear in both report formats (`report` / `report --format
json`), are covered by the provenance manifest exactly like every other
object type, and survive export/import unchanged.

**Limitations:** `relationship_type` is a free-form, analyst-declared
label — Witnessgraph does not constrain its vocabulary, infer a reverse
edge, or attempt any automatic relationship discovery. `--source`/
`--target` must already name existing entities; there is no automatic
entity creation. `relationships create` is idempotent (a `Relationship`'s
id is content-derived, like `TimeAssertion`) — re-running it with
identical arguments converges rather than duplicates.

Because this adds a sixth collection (`relationships`) to what the
provenance manifest hashes, the manifest algorithm version bumped from 2
to 3. This changes every case's manifest hash, even one with zero
relationships — exactly as the v0.1/v0.2 → v0.3 change already did once
before. A case created before this version keeps working unchanged (its
`relationships` table is created empty, lazily, the next time it's
opened), but `verify`/`replay` against its old recorded manifest reports
`NOT COMPARABLE`, not a false `MISMATCH`. Any command that mutates the
case (`ingest`, `entities create`, `relationships create`, ...) already
re-records its manifest under the current algorithm as a side effect, so
a case simply becomes freshly comparable (v3-to-v3) the next time
something is added to it.

## Graph Analysis

Relationships give Witnessgraph edges; `witnessgraph graph` is what makes
them analyzable. It does not introduce a second graph model or an
external graph database — it's a small, deterministic traversal layer
over exactly the `Entity`/`Relationship` data already in the case's
SQLite store, built once per invocation and searched with a plain,
bounded breadth-first search.

**Directed by default.** A `Relationship` is directed
(`source_entity_id -> target_entity_id`); both commands default to
`--direction out`, following only that arrow. `witnessgraph
graph path B A` does **not** find a path along an edge recorded as
`A -[connected_to]-> B` unless you explicitly ask for it:
`--direction in` follows edges backward, `--direction both` follows
either way. Whichever way an edge is walked, the relationship reported
is always exactly as stored — its own source/target are never swapped;
the output separately marks each step as `forward` or `backward` so
direction is never hidden.

**Bounded, not exhaustive.** `graph neighbors` reports every entity
reachable within `--max-depth` hops (default 1: direct neighbors only).
`graph path` returns **one** deterministic, shortest (fewest-hop) chain
— never "all paths" — within `--max-depth` hops (default 10), tie-broken
by relationship id when more than one shortest chain exists, never by
incidental storage order. `--max-depth` is capped at 50. A cycle
anywhere in the graph cannot cause an infinite search: an entity is only
ever discovered once.

```sh
witnessgraph graph neighbors ./my-case <entity-id>
witnessgraph graph neighbors ./my-case <entity-id> --max-depth 3 --direction both
witnessgraph graph path ./my-case <source-entity-id> <target-entity-id>
witnessgraph graph path ./my-case <source-entity-id> <target-entity-id> --format json
```

Example `graph path` output:

```
path found: 2 hop(s)
step 1: <A> --[connected_to via `<rel-1>`, forward]--> <B> (derived_from: `<ev-1>`)
step 2: <B> --[resolved_from via `<rel-2>`, forward]--> <C> (derived_from: `<ev-2>`)
```

"No path found within N hops" is a normal, successful result (exit code
0), not an error — it means the search completed and found nothing,
which is different from an invalid request like an unknown entity id
(exit code 1). `--format json` represents "not found" as data
(`"found": false, "steps": []`), never as an exception, for scripting.

**Provenance, not conclusions.** Every step names its relationship id,
type, and `derived_from` evidence — a result is fully auditable back to
what was actually recorded. A path or neighborhood describes a
*structural connection*, evidenced by cited relationships, and nothing
more: it is never itself a claim of causation, responsibility, or truth.

**Limitations:** no entity resolution or fuzzy matching is performed —
two different entity ids are always treated as different entities, even
if they plausibly refer to the same real-world thing (consistent with
`entities create`'s own v1.0 scope). There is no "all paths" or induced-
subgraph command; only bounded neighborhoods and one shortest path.
Graph analysis is not integrated into `report` — it stays a dedicated
CLI output so an ordinary report never pays for a traversal it didn't
ask for.

## Known limitations

### Scripting against the CLI in your own CI/automation

Typer (via its bundled `rich` integration) renders styled, boxed error
output whenever the `GITHUB_ACTIONS`, `FORCE_COLOR`, or `PY_COLORS`
environment variable is set, regardless of whether stderr is an actual
terminal. If you invoke `witnessgraph` from your own CI pipeline and
parse its stderr (e.g. grepping for an option name in a usage error),
set `_TYPER_FORCE_DISABLE_TERMINAL=1` in that environment first to get
the same plain-text output `witnessgraph` produces interactively.

### Coverage gap analysis

`witnessgraph gaps <case> --min-gap-seconds <N>` reports intervals where
one analyst-declared source (`--source-id` at ingest time) has no
observed evidence while a different, independently-declared source has
corroborating activity in that same interval. Two limitations apply that
users must understand before relying on its output:

- **`source_id` collisions.** Witnessgraph cannot independently verify
  physical source identity — it only compares the labels an analyst
  supplied. If two genuinely distinct systems are accidentally given the
  same `source_id`, their evidence is merged into one source group, and
  a real coverage gap in either one can be silently masked. An optional,
  opt-in mitigation exists: `--refine-source-by-attribute <key>`
  subdivides each declared `source_id` group by an existing
  `NormalizedEvent` attribute (e.g. `host`), for the specific case where
  one declared source actually covers several distinct real systems. It
  never overrides, replaces, or invents a `source_id` — it only
  subdivides one that was already declared — and a record with no value
  for the given attribute falls back to its coarse `source_id` group
  unchanged. The attribute value is ingested, untrusted content and
  receives no independent verification, so refinement **does not prove
  physical source identity**; it does not automatically detect or
  resolve `source_id` collisions on its own, since it only helps when
  records already carry a suitable distinguishing attribute and an
  analyst explicitly requests it. Omitting the option reproduces the
  unmitigated behavior above exactly.
- **Clock skew.** Gap analysis operates entirely on recorded timestamps
  and does not estimate or correct for clock offsets between sources.
  Skew between an absent and a corroborating source can affect both
  cross-source corroboration and the attribution of a finding to a
  specific interval. This remains unresolved and is out of scope.

A finding is a structural statement about the absence of *recorded*
evidence relative to another source, never a claim about what did or
did not physically occur — findings must not be interpreted as proof
that an event did or did not happen.

### Time assertions and contradictions

`witnessgraph contradictions` detects *structural* disagreement between
two `TimeAssertion`s about the same event (e.g. two analysts, or an
adapter and an analyst, citing incompatible times). Witnessgraph never
adjudicates which claim is correct — a contradiction is recorded and
left for a human to resolve; there is no "most trusted source" logic
anywhere in the codebase.

## Testing

```sh
pytest
ruff check .
mypy src
```

582 tests (unit + integration) exercise the full pipeline, including
property-based tests (`hypothesis`) for serialization and provenance
determinism. `ruff` and `mypy --strict` are both clean on `src/`.

## Security

See `SECURITY.md` for the full boundary: no network calls, no network
listener, no telemetry, and — critically — **no redaction**. Evidence is
stored and exported verbatim; do not ingest evidence you are not
comfortable storing as-is.

## License

MIT — see `LICENSE`.
