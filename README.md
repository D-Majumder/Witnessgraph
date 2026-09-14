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
635 tests. There is no AI integration, no graph database, and no web
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
| `graph neighbors <entity> [--max-depth] [--direction] [--explain]` | List every entity reachable from one entity within a bounded number of hops. |
| `graph path <source> <target> [--max-depth] [--direction] [--explain]` | Find one deterministic, shortest relationship chain between two entities, with full provenance. |
| `graph paths <source> <target> [--max-depth] [--direction] [--limit] [--explain]` | Find every relationship chain tied for shortest between two entities, up to `--limit`, with full provenance; `--explain` also reports whether the chains found are evidence-independent. |
| `graph components [--min-size] [--explain]` | Partition every related entity into weakly-connected clusters, direction-independent. |
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

### All shortest paths

`graph path` reports one representative shortest chain; it cannot tell
you whether that connection is corroborated by more than one
structurally distinct chain of relationships, or rests on a single link
that one missing or mistaken `Relationship` would sever entirely.
`witnessgraph graph paths` answers exactly that: every distinct chain
tied for the same shortest (fewest-hop) length between two entities, up
to `--limit`.

```sh
witnessgraph graph paths ./my-case <source-entity-id> <target-entity-id>
witnessgraph graph paths ./my-case <source-entity-id> <target-entity-id> --limit 25
witnessgraph graph paths ./my-case <source-entity-id> <target-entity-id> --format json
```

Example output:

```
2 shortest chain(s) found: 2 hop(s) each
chain 1:
  step 1: <A> --[connected_to via `<rel-1>`, forward]--> <B> (derived_from: `<ev-1>`)
  step 2: <B> --[connected_to via `<rel-2>`, forward]--> <D> (derived_from: `<ev-1>`)
chain 2:
  step 1: <A> --[connected_to via `<rel-3>`, forward]--> <C> (derived_from: `<ev-2>`)
  step 2: <C> --[connected_to via `<rel-4>`, forward]--> <D> (derived_from: `<ev-2>`)
```

**Shortest-length chains only, still not "all paths".** A longer detour
between the same two entities is never reported, exactly as `graph
path` never reports one — only chains tied for the minimum hop count
are in scope. **Hard-capped, not merely bounded by depth.** Even
restricted to shortest length, the number of tied chains can grow
quickly in a densely-connected graph; `--limit` (default 10, capped at
500) is a real ceiling on how many are ever materialized. A result with
`"truncated": true` means more tied-shortest chains exist beyond
`--limit` — reported honestly, never silently dropped or presented as
complete. Computation is bounded, not exponential: one extra bounded
BFS pass (backward from the target) restricts the search to only the
edges that can possibly lie on a shortest chain, so enumeration never
explores a dead end and always stops the instant `--limit` chains are
found.

**Corroboration, not confirmation.** Multiple structurally distinct
shortest chains are a structural fact — the connection does not depend
on any single `Relationship` — never a claim that it is therefore true,
important, or causal. A single chain is likewise never reported as
suspect; it is simply what the evidence currently records. `graph
paths <X> <X>` (source equals target) is trivially one zero-hop chain,
exactly like `graph path`.

**Structural multiplicity is not evidence independence.** The two
chains above are structurally distinct — different Relationships,
different intermediate entities — but that alone says nothing about
whether they are backed by different evidence: both could cite the same
`derived_from` id (e.g. one log line that happened to name both
connections). `--explain` resolves exactly that question; see "Evidence
independence" below.

### Evidence independence (`graph paths --explain`)

Counting structurally distinct chains as corroboration silently
overclaims if two of them turn out to cite the very same underlying
record. `witnessgraph graph paths ... --explain`, whenever 2 or more
chains are found, additionally resolves each chain's relationships'
`derived_from` ids down to the root `EvidenceItem` id(s) they ultimately
trace to (following through a `NormalizedEvent`'s own `derived_from`
where one is cited instead of an `EvidenceItem` directly), and reports
whether any root evidence id is shared by more than one chain.

```sh
witnessgraph graph paths ./my-case <source-entity-id> <target-entity-id> --explain
```

Example text output (two evidence-independent chains):

```
evidence independence:
  chain 1: root evidence `<ev-1>`
  chain 2: root evidence `<ev-2>`
  fully evidence-independent: true (no shared root evidence)
```

Example text output (two chains sharing a root `EvidenceItem`, even
though their raw `derived_from` ids differ — e.g. one cites the
`EvidenceItem` directly and the other cites a `NormalizedEvent` built
from that same `EvidenceItem`):

```
evidence independence:
  chain 1: root evidence `<ev-1>`
  chain 2: root evidence `<ev-1>`
  fully evidence-independent: false -- shared evidence: `<ev-1>`
```

With fewer than 2 chains found, there is nothing to compare — the text
output says so explicitly ("only one chain -- evidence independence
does not apply") and the JSON's `fully_evidence_independent` is `null`
rather than a vacuous `true`. `--format json` represents the same
analysis as data under `evidence_independence` (present only with
`--explain`, exactly like `entities`): `chains` (each chain's index and
its `root_evidence_ids`), `shared_evidence_ids` (every root evidence id
cited by 2 or more chains), and `fully_evidence_independent`
(`true`/`false`/`null`).

**What this means:** an id in `shared_evidence_ids` names an
`EvidenceItem` that backs two or more of the *returned* chains — their
apparent structural corroboration rests, at least in part, on the same
underlying record. **What this does NOT mean:** it is never a claim
that a chain is therefore true, false, more important, or more
trustworthy than another, and disjoint evidence is never itself a claim
that a connection is "confirmed" — only that the records cited are
distinct. It says nothing about chains beyond `--limit`/`truncated`,
either — the verdict describes only the chains actually returned.

Bounded, not a new traversal: this resolves only the `derived_from` ids
already present in the already-bounded `paths` result, one lookup per
id (cycle-safe, like `_bfs`, against the hypothetical case of malformed
data forming a reference cycle) — no new depth parameter, no graph
walking.

### Connected components

`witnessgraph graph components` answers a different question from
`neighbors`/`path`: not "what is reachable from this one entity" but
"how does this case's whole relationship graph break down into
independent clusters". It partitions every entity that appears in at
least one relationship into groups where every member is joined to every
other member by some chain of relationships.

This is the one graph command that treats direction as irrelevant —
`A --connected_to--> B` puts A and B in the same cluster exactly as
`B --connected_to--> A` would, because cluster membership and
point-to-point reachability are genuinely different questions (`graph
path B A` still would not find that edge without `--direction in`/
`both`). An entity with zero relationships is not part of any cluster —
it is never reported as a trivial cluster of its own.

```sh
witnessgraph graph components ./my-case
witnessgraph graph components ./my-case --min-size 3
witnessgraph graph components ./my-case --format json
```

Example output:

```
2 component(s) covering 5 of 5 entities in the relationship graph (4 relationship(s) total; min-size=1)
- component 0: 3 entities, 3 relationship(s)
  entities: `<A>`, `<B>`, `<C>`
  - `<rel-1>`: <A> -[connected_to]-> <B> (derived_from: `<ev-1>`)
  - `<rel-2>`: <B> -[connected_to]-> <C> (derived_from: `<ev-1>`)
  - `<rel-3>`: <C> -[connected_to]-> <A> (derived_from: `<ev-1>`)
- component 1: 2 entities, 1 relationship(s)
  entities: `<X>`, `<Y>`
  - `<rel-4>`: <X> -[connected_to]-> <Y> (derived_from: `<ev-2>`)
```

Components are ordered by their smallest member entity id, and entities/
relationships within a component are each sorted by id — a property of
the graph itself, not of insertion order, so this never needs a
traversal tie-break the way `path` does. `--min-size` (default 1: show
everything) filters small clusters out of the *displayed* result without
changing what was actually computed; every component has at least 2
entities by construction, so `--min-size 1`/`2` are equivalent. A cycle
resolves to one ordinary component, never a hang or a duplicate count. A
`.json` result is the same partition as data: `total_entities_in_graph`
and `total_relationships` describe the whole graph, `total_components_found`
is the count before `--min-size` filtering, and every relationship
inside every component still carries its full `derived_from` lineage.

**Limitations:** no entity resolution or fuzzy matching is performed —
two different entity ids are always treated as different entities, even
if they plausibly refer to the same real-world thing (consistent with
`entities create`'s own v1.0 scope). There is no induced-subgraph
command, and `graph paths` reports only chains tied for the *shortest*
length, capped at `--limit` — never every path of every length between
two entities. A component is a structural grouping only —
membership is never a claim that everything inside it shares a cause, an
actor, or a conclusion. Graph analysis is not integrated into `report` —
it stays a dedicated CLI output so an ordinary report never pays for a
traversal or partition it didn't ask for.

### Explainability (`--explain`)

Every `graph neighbors`/`graph path`/`graph paths`/`graph components`
result already names its relationships' ids, types, and `derived_from`
evidence ids — but until now, turning one of those ids into something
readable meant a manual, out-of-band lookup (there is still no
standalone `evidence show` command). `--explain`, accepted by all four
commands, closes that gap:
it resolves every relationship's `derived_from` ids and every
participating entity id to their actual stored records, so a result
answers *why* Witnessgraph produced it without a second lookup.

```sh
witnessgraph graph path ./my-case <source-entity-id> <target-entity-id> --explain
witnessgraph graph path ./my-case <source-entity-id> <target-entity-id> --explain --format json
```

Example text output (`--explain`, abridged):

```
path found: 2 hop(s)
step 1: <A> --[authenticated_as via `<rel-1>`, forward]--> <B> (derived_from: `<ev-1>`)
   evidence:
     - evidence_item `<ev-1>`: source_adapter=jsonl, source_locator=events.jsonl:1, collected_at=2026-01-01T09:00:00+00:00
step 2: <B> --[connected_to via `<rel-2>`, forward]--> <C> (derived_from: `<ev-1>`)
   evidence:
     - evidence_item `<ev-1>`: source_adapter=jsonl, source_locator=events.jsonl:1, collected_at=2026-01-01T09:00:00+00:00
entities:
  - `<A>` (user): username=jsmith
  - `<B>` (host): hostname=corp-ws-042
  - `<C>` (ip): address=203.0.113.7
```

This is a pure lookup, never fabrication: resolving an id calls the same
`Store.get_evidence`/`get_normalized_event`/`get_entity` every other
referential-existence check in this codebase already uses. Nothing is
summarized, guessed, or invented — a `derived_from` id naming neither an
EvidenceItem nor a NormalizedEvent (`core/` does not enforce referential
integrity at construction time) is reported as `"not_found"`, not
dropped or raised as an error. `--explain` is strictly bounded by the
result it explains: it resolves only ids already present in an
already-bounded `neighbors`/`path`/`paths` result or an already-whole-graph
`components` result — no new traversal, no new depth parameter.

`--explain` is additive and opt-in: omitting it reproduces byte-for-byte
the same output as before this capability existed (both `text` and
`json`); with it, JSON gains a `evidence_lineage` array on every
relationship and a top-level `entities` map keyed by every entity id
appearing in the result — structured data a future UI could render
without parsing any human-readable string.

**Limitations:** `--explain` reports a *structural fact* (this
relationship exists) and a *provenance fact* (it is grounded in this
evidence) — never a forensic conclusion. It never says who did
something, why, or that two entities belong to the same incident merely
because a path or component connects them. Resolved evidence metadata is
exactly what `EvidenceItem`/`NormalizedEvent` already store (adapter,
locator, timestamps, event type/attributes) — never raw evidence
content, and never anything the database does not already contain.

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

635 tests (unit + integration) exercise the full pipeline, including
property-based tests (`hypothesis`) for serialization and provenance
determinism. `ruff` and `mypy --strict` are both clean on `src/`.

## Security

See `SECURITY.md` for the full boundary: no network calls, no network
listener, no telemetry, and — critically — **no redaction**. Evidence is
stored and exported verbatim; do not ingest evidence you are not
comfortable storing as-is.

## License

MIT — see `LICENSE`.
