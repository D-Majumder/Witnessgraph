# Witnessgraph UI v1 — Architecture Design

Status: **design-only. No implementation exists yet.** Written against
published HEAD `a72984544caea527f0b39981e0339cd776b5008b` (731 tests
passing; JSON coverage complete across `graph *`, `report`,
`contradictions`, `gaps`, `findings`, `contradiction-findings`). This
document does not modify core semantics, graph algorithms, CLI
behavior, or dependencies — it is the architecture a future
implementation session builds from.

**Core requirement, unchanged and still governing every decision
below: the UI is a consumer of the Witnessgraph reasoning engine, never
a second implementation of it.** Every fact the UI displays must be
traceable to a structured result this engine already computes (or a
small, explicitly-identified, not-yet-built extension of one) — never
re-derived in the frontend, never parsed out of human-readable text.

## 1. Explicit non-goals

- Not an implementation session. No frontend code, no API server code,
  and no new dependency is added by this document.
- Not a UI mockup or visual design. This is a data-flow and boundary
  architecture; visual design is a later, separate concern.
- Not a plan to replace the CLI. The CLI remains the primary, stable,
  scriptable interface; the UI is an additional, optional consumer of
  the same engine, and every code path the UI depends on must remain
  usable from the CLI too (see §3).
- Not a general-purpose forensic acquisition, artifact-parsing, or
  case-management product. See §18 for the full non-goal list.
- Not a claim that this design supersedes or outperforms commercial
  forensic suites (Magnet AXIOM, EnCase, Autopsy) — see the project
  README's own framing. Witnessgraph occupies a different, narrower
  layer: reasoning over evidence already extracted and ingested, not
  acquisition or artifact parsing.

## 2. Current engine architecture (as verified by direct inspection)

Package layout (`src/witnessgraph/`): `core/`, `store/`, `ingest/`,
`correlate/`, `replay/`, `report/`, `cli/`, plus `portable.py` at the
top level. Dependencies (`pyproject.toml`): `pydantic>=2.6` and
`typer>=0.12` only — no web framework, no HTTP client, no async
runtime, no graph library, anywhere in the dependency tree today.

Answering Part 1's nine questions directly, from the actual code:

1. **Domain logic** lives in `core/` — `Entity`, `Relationship`,
   `EvidenceItem`, `NormalizedEvent`, `TimeAssertion`, `Hypothesis`,
   `TrackedGapFinding`, `TrackedTimeContradiction`, `ProvenanceManifest`.
   All are frozen Pydantic models; `core/` performs no I/O (DESIGN.md
   principle 6) and imports nothing from `store/`, `correlate/`, or
   `cli/`.
2. **Analytical logic** lives in `correlate/` — `graph.py` (traversal:
   `find_neighbors`/`find_path`/`find_all_shortest_paths`/
   `find_components`, plus explainability and
   `analyze_paths_evidence_overlap`), `contradictions.py`
   (`detect_time_contradictions`), `gaps.py` (`find_gaps`),
   `tracking.py`/`contradiction_tracking.py` (persist-if-absent
   orchestration for findings/contradictions plus
   `is_still_reproduced`). Every one of these takes a `Store` and
   returns a plain dataclass — no CLI, Typer, or I/O-formatting
   concern appears anywhere in this package.
3. **Persistence** lives in `store/` — `Store`/`BlobStore` are
   `Protocol`s (`store/base.py`); `SqliteStore`/`FileBlobStore`
   (`store/sqlite_store.py`) are the only implementation. `Case`
   (`store/case.py`) is the unit of "one investigation": one directory,
   one `SqliteStore` connection (`sqlite3.connect`, no
   `check_same_thread=False`, no connection pool — a `Case` is
   confined to the thread/process that opened it), one
   `FileBlobStore`. `Case.open`/`Case.create` are the only entry
   points; there is no other way to obtain a `Store`.
4. **CLI orchestration** lives entirely in `cli/main.py` (one file,
   ~1750 lines). Every Typer command follows the same shape: open the
   case, call one or more `correlate.*`/`store.*` functions, render
   text or (where supported) call a `*_to_json` builder and write
   `canonical_json_bytes`, close the case. **There is currently no
   application/service layer distinct from the CLI** — `cli/main.py`
   *is* today's only orchestration boundary. This is the single most
   important finding for this design: introducing a real
   application/service layer (§4) is new work, not a relocation of
   existing code, though the amount of genuinely new logic it requires
   is small (see §4's "thin" characterization).
5. **Structured results are created** in `correlate/*.py`, as frozen
   dataclasses (`NeighborsResult`, `PathResult`,
   `AllShortestPathsResult`, `ComponentsResult`, `PathsEvidenceOverlap`,
   `TimeContradiction`, `GapAnalysisResult`, `GapFinding`) — never as
   dicts, never inside `cli/main.py`.
6. **JSON serialization is performed** by paired `*_to_json` functions
   living beside each dataclass's owning module (`correlate/graph.py`,
   `correlate/contradictions.py`, `correlate/gaps.py`,
   `correlate/tracking.py`, `correlate/contradiction_tracking.py`), and
   by `report/render_json.py` for the whole-case report tree (which
   itself now delegates to those same functions rather than
   duplicating their logic — see the commit `7c404a1` that completed
   this). `core/ids.canonical_json_bytes` is the *only* place bytes are
   actually produced from a dict tree (sorted keys, compact separators,
   `ensure_ascii=True`, UTC `Z`-suffixed datetimes) — this exists for
   byte-for-byte CLI reproducibility, not because HTTP JSON responses
   need that exact canonicalization (see §7's note on this).
7. **Safe for a UI to consume directly (in-process, same Python
   runtime):** everything in `core/`, `correlate/`, `store/`, `replay/`,
   `report/render_json.py`'s public `build_report_json_tree`, and
   `portable.py`. All of it is pure, synchronous, local-file-only, and
   already covered by 731 tests.
8. **Must NOT be imported directly by a frontend:** nothing, because
   the frontend (§6) is JavaScript/TypeScript and cannot import Python
   at all — the real constraint is that the frontend must never
   reimplement any of §2's logic in JS. If a Python-only UI is ever
   built instead (rejected in §6, but worth stating precisely): it
   *could* technically import `correlate/*` directly, but should not —
   it should still go through the application/service boundary in §4,
   so the CLI and the UI never diverge in how they call the engine.
9. **The missing boundary** is exactly the application/service layer:
   a place that owns "open this case, call this analysis, shape this
   result for a caller that is not a terminal" — independent of
   whether that caller is the CLI's own `typer.echo`/`canonical_json_bytes`
   path or a future HTTP handler's JSON response. See §4.

## 3. UI technology decision

**Decision: a local-only web UI — React + TypeScript frontend, a thin
FastAPI backend, communicating over `localhost` HTTP — is the smallest
architecture that satisfies the graph-interaction requirement without
becoming a second implementation of the engine.**

Options actually evaluated against this repository, not against
popularity:

- **B. Python-native desktop UI (Tkinter/PyQt/etc.), rejected.** Would
  avoid a second language and keep everything in-process (no HTTP
  boundary at all — the UI could call `correlate/*` directly). But
  Part 6 requires click-driven node/edge selection, path highlighting,
  multi-path overlay rendering, and hover/drill-down interaction on a
  force-directed graph. Python's own graph-rendering options
  (`matplotlib`/`networkx` static plots, `PyQtGraph`) are static or
  weak at exactly this interaction model; building it from scratch in
  Qt would either take longer than the rest of V1 combined or produce
  the "decorative graph viewer" this task explicitly warns against.
- **C. Python web UI (Streamlit/Gradio/Dash), rejected as the primary
  pick.** Fast to prototype, stays in one language. `dash-cytoscape`
  specifically would give real graph interactivity and was seriously
  considered. Rejected because: (a) it commits the whole application to
  Dash's server-side callback/state model, which is more constraining
  long-term than a plain REST API + independent frontend, especially
  once cross-view state (selected entity ↔ highlighted path ↔
  provenance panel, per Part 5/6/7) grows; (b) it still needs a runtime
  Python process serving the UI, so it does not actually avoid a
  server boundary — it just merges the "backend" and "frontend"
  process, which does not simplify anything relevant here; (c) it
  still needs Cytoscape.js under the hood, so the "no JS" benefit is
  already partial. Documented here so this was a real evaluation, not
  an unconsidered option.
- **A. React + TypeScript frontend, FastAPI backend — selected.**
  Graph libraries with the required interactivity (click node/edge,
  style by data attribute, programmatically highlight a path or a set
  of paths, hover tooltips) are overwhelmingly a JS-ecosystem strength;
  **Cytoscape.js** in particular is purpose-built for exactly this
  (network/security-graph visualization is one of its standard use
  cases) and needs no custom interaction plumbing built from scratch.
  A thin JSON-over-HTTP boundary is a natural, incremental step from
  what already exists: every `*_to_json` builder already produces
  exactly the dict tree an HTTP JSON response needs; the API layer adds
  routing and case-lifecycle handling, not analysis logic. FastAPI is
  justified specifically because: it is Pydantic-native, and
  Witnessgraph's own domain models are already Pydantic — request/
  response typing can lean on the same library the domain already
  uses, without necessarily reusing the *same* models for responses
  (see §7's canonicalization note); it needs no async database driver
  or connection pool (SqliteStore is synchronous, one connection per
  request-scoped `Case.open`, mirroring the CLI's own per-invocation
  lifecycle exactly — see §4); and it auto-generates an OpenAPI
  schema, which is a real asset for keeping the API's contract honest
  and typed on both sides without hand-maintained documentation
  drifting from the code.

This does **not** contradict DESIGN.md principle 6 ("the core library
... has no network listener"): that principle scopes `core`, `store`,
`ingest`, `correlate`, `replay` — the reasoning engine — which remains
exactly as local-first and listener-free as it is today. The API
server is new, explicitly-scoped code living in its own package,
bound to `127.0.0.1` only in local mode (§10), never a change to what
the engine itself does.

## 4. Application/service boundary

**Yes, an explicit service layer is needed, and it does not exist yet
(§2, point 9).** Proposed shape:

```
CLI            UI (via HTTP)
  \            /
   \          /
  witnessgraph.service   <- NEW, thin
        |
  core + correlate + store + replay + portable   <- UNCHANGED
```

`witnessgraph.service` (new package, `src/witnessgraph/service/`) is
deliberately **thin**: every function opens (or accepts) a `Case`,
calls exactly the `correlate.*`/`store.*` function the CLI already
calls, and returns exactly the same dataclass or `*_to_json` dict the
CLI already produces. No new analysis, no new sorting/determinism
rule, no new domain concept. Its entire value is giving the CLI and
the future API server *one shared place* to call instead of each
re-deriving "how do I open a case and run this analysis" independently
— today's `cli/main.py` would refactor to call this layer too (a
mechanical, behavior-preserving change, not part of this design
session).

Concrete operations, evaluated against what actually exists today
(mapped exactly, not the full example list from the brief):

| Service operation | Backed by (today) | Status |
| --- | --- | --- |
| open/close case | `Case.open`/`Case.create`/`Case.close` | exists |
| case overview (counts: evidence, entities, relationships, hypotheses, tracked findings/contradictions; manifest verdict) | *nothing standalone* — only derivable by calling `store.list_*` for every collection, or fetching the full `report --format json` tree and counting arrays | **missing** — see §5's Overview view and the gap list below |
| list entities / get entity | `store.list_entities()` / `store.get_entity(id)` (already used by `entities_show`'s `model_dump_json`) | exists, but no public `entity_to_json` helper outside `report/render_json.py`'s private `_build_entities` — trivial to add (a pure pass-through of `Entity`'s own fields) |
| list relationships (optionally by entity) / get relationship | `store.list_relationships()` (+ CLI's own `--entity` filter) / `store.get_relationship(id)` | exists; same "no public single-object JSON helper outside a private report builder" note as entities |
| get evidence item | `store.get_evidence(id)` | exists on `Store`; **no public JSON shape outside graph.py's private `_evidence_item_to_json`** — see gap list |
| list time assertions for an event / list all | `store.list_time_assertions()` (unfiltered) | exists on `Store`; **no public JSON shape, no CLI command at all (`time-assertions` only has `create`)** — see gap list |
| analyze neighbors / path / all shortest paths / components | `find_neighbors`/`find_path`/`find_all_shortest_paths`/`find_components` | exists, fully — this is the most complete part of the surface |
| explain a graph result | `explain_relationship`/`resolve_entity`/`resolve_evidence_ref`, wired via each `*_result_to_json(..., store=...)`'s `store` parameter | exists |
| evidence-independence for tied-shortest paths | `analyze_paths_evidence_overlap` | exists |
| detect contradictions / detect gaps | `detect_time_contradictions` / `find_gaps` | exists |
| list/get tracked findings / tracked contradictions | `store.list_tracked_findings`/`get_tracked_finding` + `is_still_reproduced` (folded via `tracked_finding_to_json`, v1 of this session's predecessor); `store.list_tracked_contradictions`/`get_tracked_contradiction` + `tracked_contradiction_to_json` | exists |
| annotate (ack) a finding/contradiction | `store.annotate_tracked_finding`/`annotate_tracked_contradiction` | exists — the one **write** operation currently exposed anywhere (see §10) |
| get case report (Markdown/JSON) | `render_report_bytes`/`render_report_json_bytes` | exists |
| export / import / verify | `export_case`/`import_case`/`replay_and_verify` | exists; **`replay_and_verify`'s `ReplayResult` has no `*_to_json` at all** — `verify`/`replay` are CLI-text-only today — see gap list |

This table is deliberately *not* the brief's full example list —
several of those (e.g. a generic "get reports" beyond what `report`
already returns) map to nothing new; the table above is the actual,
minimal set worth building a service function for.

## 5. Structured result contracts

Every shape below is **copied from the actual code**, not invented.
Field lists are exhaustive as of HEAD `a729845...`.

**Entity** (`core/entities.py`, no dedicated `*_to_json` yet — see gap
list; shape shown is `Entity`'s own fields, exactly what
`entities show`'s `model_dump_json()` already emits):
`id, entity_type, identifiers, first_seen, last_seen, derived_from`.

**Relationship** (`correlate/graph.py::_relationship_to_json`, also
`report/render_json.py::_build_relationships`):
`id, relationship_type, source_entity_id, target_entity_id, attributes, derived_from`,
plus `evidence_lineage` (array of `ResolvedEvidenceRef`, see below)
**only** when a graph command's `store=` explain parameter is set.

**EvidenceItem** (`correlate/graph.py::_evidence_item_to_json`,
private — see gap list): `id, source_adapter, adapter_version,
source_locator, raw_size_bytes, collected_at, observed_at`.
`report/render_json.py::_build_evidence` additionally includes
`chain_of_custody` (array of `{actor, action, timestamp,
source_locator, source_id}`) — the graph-explain shape does not, since
custody history is not part of what a graph result's provenance
question needs.

**NormalizedEvent** (`correlate/graph.py::_normalized_event_to_json`):
`id, event_type, attributes, derived_from`.

**ResolvedEvidenceRef** (one `derived_from` id, resolved —
`correlate/graph.py::_resolved_evidence_ref_to_json`): `id, kind`
(`"evidence_item" | "normalized_event" | "not_found"`),
`evidence_item` (nullable), `normalized_event` (nullable).

**ResolvedEntity** (`_resolved_entity_to_json`): `entity_id, found,
entity_type` (null if not found), `identifiers` (null if not found).

**Graph step** (`_step_to_json`): `from_entity_id, to_entity_id,
walked_direction` (`"forward" | "backward"`), `relationship` (the
Relationship shape above).

**Neighbors result** (`neighbors_result_to_json`): `origin_entity_id,
direction, max_depth, reached` (array of `{entity_id, hop_count, via:
<step>}`), plus `entities` (map of entity id → `ResolvedEntity`,
explain-only).

**Path result** (`path_result_to_json`): `source_entity_id,
target_entity_id, direction, max_depth, found, hop_count, steps`
(array of steps), plus `entities` (explain-only).

**All-shortest-paths result** (`all_shortest_paths_result_to_json`):
`source_entity_id, target_entity_id, direction, max_depth, limit,
found, hop_count, truncated, paths` (array of arrays of steps — one
inner array per tied-shortest chain), plus `entities` and
`evidence_independence` (both explain-only).

**Evidence-independence result** (`paths_evidence_overlap_to_json`):
`chains` (array of `{chain_index, root_evidence_ids}`),
`shared_evidence_ids` (array), `fully_evidence_independent`
(`true | false | null` — `null` when fewer than 2 chains exist, i.e.
"not applicable", never a vacuous `true`).

**Components result** (`components_result_to_json`): `min_size,
total_entities_in_graph, total_relationships, total_components_found,
components` (array of `{index, entity_ids, relationships}`), plus
`entities` (explain-only).

**Contradiction** (`contradictions_to_json`): `subject_event_id,
assertions` (exactly 2, ascending by id, each `{id, value, precision,
source_evidence_id}`).

**Gap analysis result** (`gap_analysis_to_json`):
`refine_source_by_attribute, findings` (array of `{absent_source,
present_source, absent_source_refinement, present_source_refinement,
interval_start, interval_end, corroborating_time_assertion_ids,
bounding_absent_assertion_ids}` — the last is an order-significant
`[start, end]` pair, never sorted), `excluded_no_time_assertion,
excluded_no_declared_source, excluded_ambiguous_source,
excluded_unrefined_fallback_with_refined_sibling`.

**Tracked gap finding** (`tracked_finding_to_json`): every
`TrackedGapFinding` field (`id, absent_source, present_source,
absent_source_refinement, present_source_refinement, interval_start,
interval_end, corroborating_time_assertion_ids,
bounding_absent_assertion_ids, min_gap_seconds,
min_corroborating_events, refine_source_by_attribute, status,
annotated_by, annotated_at, note`) plus `still_reproduced` (live,
caller-supplied — never persisted).

**Tracked contradiction** (`tracked_contradiction_to_json`): `id,
subject_event_id, assertion_ids, status, annotated_by, annotated_at,
note`. Deliberately **no** `still_reproduced` field (see that
function's own docstring: always-true would convey no information).

**Whole-case report tree** (`build_report_json_tree`): `schema_version,
case_name, manifest, evidence, timeline, entities, relationships,
hypotheses, contradictions, coverage_gaps` (`null` when gap analysis
was not run this call — a distinct meaning from `{"findings": [], ...}`),
`tracked_findings, tracked_contradictions`.

**Encoding contract every one of the above is subject to**
(`core/ids.canonical_json_bytes`): sorted keys, compact separators,
`ensure_ascii=True`, datetimes normalized to UTC ISO-8601 with a `Z`
suffix (`2026-01-01T00:00:00Z`, not `+00:00`). This exists so the CLI's
byte output is reproducible for hashing/diffing/scripting — an HTTP
JSON response body does **not** need this exact canonicalization to be
correct (a JS client does not care about key order), but **does** need
the same datetime normalization (so the frontend never has to handle
two different timestamp formats depending on whether it's talking to
the CLI's saved output or the API). The service layer (§4) should
reuse the dict-building functions (`*_to_json`) directly and let
FastAPI/Starlette serialize them (not necessarily via
`canonical_json_bytes`), but must still apply the same datetime
normalization — either by keeping `_json_default`'s Z-suffix rule
available to the API's JSON encoder, or by continuing to call
`canonical_json_bytes` and returning it as a raw `Response` body
(simplest, zero new formatting code, marginal cost of non-pretty-sorted
keys the frontend will never notice).

### Missing/needed structured contracts (identified, not built)

Honest gap list, each traced to a specific missing piece, not a vague
"add more JSON":

1. **Case overview/summary.** No standalone operation returns just
   counts (evidence/entities/relationships/hypotheses/tracked findings
   and contradictions) plus the manifest verdict. Today the only way to
   get these numbers is the full `report --format json` tree (which
   also serializes every evidence item and the full timeline — needless
   cost for a landing page) or several separate `store.list_*` calls.
   **Needed for:** the Overview view (§6). Small: a new
   `case_overview_to_json(store, case)` combining existing `len(...)`
   counts and `case.compute_manifest()`/`load_recorded_manifest()`
   verdict logic (already exists in `render_json._build_manifest`,
   itself reusable).
2. **Single Entity/Relationship JSON builder, public.** `entities show`/
   `relationships show` already emit valid JSON today
   (`model_dump_json()`), so this is not a *missing capability*, only a
   missing *shared, service-layer-callable* function — today that
   JSON is produced ad hoc inline in `cli/main.py`, not via a function
   the service layer can call directly to build, e.g., a list response
   without going through Typer.
3. **Evidence item / NormalizedEvent, standalone.** No CLI command
   (`evidence show`, `events show`) exists at all; the two private
   `_evidence_item_to_json`/`_normalized_event_to_json` functions in
   `correlate/graph.py` are the only place these shapes are produced,
   and only ever as part of a resolved `derived_from` reference inside
   a graph result — never addressable by id on their own. **Needed
   for:** a UI's Evidence view (§6) if it is to support browsing/
   searching evidence directly, not only reaching it by drilling down
   from a relationship. A small addition (public
   `evidence_item_to_json`, `normalized_event_to_json`, `list_evidence`
   /`get_evidence` service functions) — not built this session.
4. **TimeAssertion, standalone.** `time-assertions` only has `create`;
   there is no `list`/`show`, and no public JSON shape for a bare
   `TimeAssertion` outside its embedding in a contradiction/timeline
   entry. `timeline` itself is text-only (no `--format json`) — the
   only structured path to normalized-event+assertion data today is
   the full report tree's `timeline` array. **Needed for:** the
   Timeline view (§8) if it is to be its own lightweight fetch instead
   of always pulling the whole-case report.
5. **Verify/replay, standalone.** `ReplayResult` has no `*_to_json`;
   `verify`/`replay` are CLI-text-only. Lower priority than 1–4 (an
   integrity indicator is a small part of the Overview view, not a
   primary view), but worth a one-line `replay_result_to_json` if the
   Overview view wants to surface "manifest verified" as a fact rather
   than re-deriving it from re-running `compute_manifest`/
   `load_recorded_manifest` itself.

None of the above changes any existing behavior; each is strictly
additive, in the same style as every `*_to_json` function that already
exists. They are listed here so the next implementation session does
not have to rediscover them by trial and error while wiring the API.

## 6. UI information architecture

Organized around the domain (per Part 5's instruction), not the CLI
command list:

```
CASE
├── Overview       — case identity, counts, manifest/integrity verdict
├── Evidence       — browse/search raw EvidenceItems (needs §5 gap #3)
├── Entities       — browse entities; entry point into the graph
├── Relationships  — browse edges directly (useful for a specific
│                    relationship_type audit, independent of graph nav)
├── Graph          — the central interactive view (§7)
├── Timeline       — NormalizedEvents + TimeAssertions in time order
├── Contradictions — structural TimeAssertion conflicts
├── Gaps           — structural coverage-gap findings
├── Findings       — tracked gap findings + tracked contradictions,
│                    review/annotation workflow
├── Hypotheses     — analyst-proposed, evidence-backed claims
└── Report         — the existing Markdown/JSON case report, as a
                     downloadable/viewable document
```

| View | Purpose | Primary data | Key interactions | Provenance access | Relation to other views |
| --- | --- | --- | --- | --- | --- |
| Overview | Orient on a case before diving in | case_overview (§5 gap #1), manifest verdict | open a different case, jump to any other view | manifest hash shown, no drill-down needed here | landing page; links out to every other view |
| Evidence | See what was actually ingested | EvidenceItem list/detail (§5 gap #3) | filter by source_adapter/locator, open one item's metadata | is itself the provenance root — nothing "under" it | linked from every relationship/entity's drill-down |
| Entities | Browse the node set directly | Entity list/detail | search by type/identifier, click → open in Graph centered on this entity | shows `derived_from` → Evidence view | feeds Graph |
| Relationships | Browse the edge set directly | Relationship list/detail | filter by type/entity, click → highlight in Graph | shows `derived_from` → Evidence/NormalizedEvent | feeds Graph |
| Graph | Central structural exploration | Neighbors/Path/Paths/Components results | select node/edge, run path/paths/components, toggle direction | full drill-down chain (§7) | hub of the whole UI |
| Timeline | Temporal ordering of events | NormalizedEvent + TimeAssertion (§5 gap #4) | filter by event_type/source, jump to a contradiction | each entry → its EvidenceItem | cross-links to Contradictions/Gaps |
| Contradictions | See disagreeing time claims | TimeContradiction list | open the two disagreeing TimeAssertions side by side | both assertions' `source_evidence_id` | can "track" one → Findings |
| Gaps | See coverage-gap findings | GapAnalysisResult | adjust `--min-gap-seconds`/refinement, re-run | bounding/corroborating assertion ids | can "track" one → Findings |
| Findings | Review/annotate persisted findings | TrackedGapFinding/TrackedTimeContradiction | ack (status + note), see live "still reproduced" | same as source Contradiction/Gap | the one place with a write operation (§10) |
| Hypotheses | See analyst claims | Hypothesis list | (v1: read-only view; propose/support/contradict are CLI-only for now — see §16) | each EvidenceRef → Evidence view | explicitly never auto-generated (§9) |
| Report | Full-case document | Markdown or JSON report | download, or view rendered Markdown | is itself a provenance-complete snapshot | superset view; not a replacement for the interactive views above |

## 7. The graph view

This is the central interactive capability (per Part 6) and must
render only facts the engine already computed — never a layout or
grouping decision presented as if it were analytical output.

**Entity node.** Label: an identifier drawn from `identifiers` (the
existing `Entity` model imposes no schema on this dict, so the UI picks
a reasonable display key per `entity_type`, e.g. `hostname` for `host`
— a display heuristic, never a new domain concept). Node style keyed
by `entity_type` (color/icon), never by anything inferred. Tooltip:
`entity_type`, `id`, full `identifiers` map.

**Relationship edge.** Directed arrow (never rendered symmetric — the
engine itself is directed-by-default and treats `--direction both` as
an explicit, separate choice, and the UI must preserve that
distinction rather than always drawing edges as if undirected). Label:
`relationship_type`. Style/thickness must not encode an invented
"strength" or "confidence" — there is no such field on `Relationship`.

**Entity selection.** Opens a detail panel: the `Entity` record itself,
its direct relationships (`graph neighbors <id> --max-depth 1` both
directions, or a plain `relationships list --entity <id>`), and a
"view evidence" action into the Evidence view for each `derived_from`
id.

**Relationship selection.** Opens a detail panel: `id, relationship_type,
source_entity_id, target_entity_id, attributes`, and its
`evidence_lineage` (call the graph command that produced this edge with
`--explain`, or — once built — a small dedicated
`relationship_evidence_to_json` service function) resolving each
`derived_from` id to its full EvidenceItem/NormalizedEvent record.

**Path.** Selecting a source and target entity runs `graph path`;
render the returned `steps` as a highlighted sequence of edges over the
full graph (or the full graph filtered to the neighborhood, for a large
case — see §15). Never render it as "the connection" if `found` is
`false` — render "no path found within N hops" exactly as the engine
reports it, never silence.

**Multiple (tied-shortest) paths.** Selecting "show all shortest
chains" runs `graph paths`; render every returned chain as a distinct
highlighted overlay (e.g. one color per chain index), with a visible
count ("`N` chains found" / "truncated — more exist beyond limit,
raise the limit to see more") taken directly from `hop_count`,
`len(paths)`, and `truncated`. Never collapse them into one line, and
never imply that a longer detour exists just because it isn't shown —
`graph paths` only ever returns chains tied for the *minimum* length,
by design.

**Components.** A "show clusters" toggle runs `graph components` and
colors/groups nodes by `component.index`. Because components are
computed direction-independent (a deliberate, documented exception —
see `correlate/graph.py`'s own module docstring), this view must be
labeled as such, distinct from the directed neighbors/path views, so a
user does not conclude "these are all reachable from each other" when
the actual guarantee is weaker (weak connectivity only).

**Explain: graph result → relationship → evidence → entity.** One
consistent drill-down mechanic (see §8 for the chosen mechanism):
every rendered edge/step already carries its full `Relationship`
object; clicking it opens the relationship detail panel (above), whose
`evidence_lineage`/`derived_from` list is itself clickable into the
Evidence view, whose record shows `source_adapter`/`source_locator`/
`collected_at` — the same three-hop chain the engine's own `--explain`
machinery already performs, rendered instead of printed.

**Evidence independence.** This is the one place language discipline
matters most (per Part 6/Part 3's explicit caution, and this
repository's own prior design decision — see
`correlate/graph.py`'s "Structural multiplicity is not evidence
independence" docstring passage). The UI must render, verbatim in
spirit:

- *Structural fact:* "N structurally distinct chains connect these two
  entities" (from `all_shortest_paths_result_to_json`'s `paths`).
- *Evidence fact, separately:* "these chains' root evidence is fully
  disjoint" / "chains 1 and 3 share evidence item `<id>`" (from
  `evidence_independence.fully_evidence_independent` and
  `shared_evidence_ids`) — never merged into one sentence with the
  structural fact above, and never using the words "proof",
  "corroboration", or "confirms" for either fact on its own. The
  correct UI copy is closer to: "Structurally distinct: yes (2 chains).
  Evidence-independent: no — both chains cite EvidenceItem `<id>`,"
  presented as two separate, labeled facts, exactly mirroring the two
  separate fields the engine returns.
- When `fully_evidence_independent` is `null` (fewer than 2 chains),
  render "not applicable" — never a default "true", which the engine
  itself deliberately never returns for this case (see
  `PathsEvidenceOverlap`'s own docstring).

## 8. Provenance UX

**Mechanism: expandable inline lineage, not a separate drill-down
page.** Rationale: provenance in this engine is always a *short*,
*bounded* chain (id → id → id, at most a few hops — `derived_from` is
never deep, `--explain` never traverses further than the result it
explains), so a full page navigation per hop would fragment a fact a
user should be able to see in one glance. An expandable
tree/disclosure widget attached to whatever is already on screen
(a relationship row, a graph edge's detail panel, a timeline entry)
is the right granularity — consistent with how `--explain`'s own text
output already nests evidence under each step with indentation rather
than requiring a second command.

Concretely: `Relationship → derived_from → EvidenceItem/NormalizedEvent
→ metadata` and `Graph result → contributing relationships → derived
evidence → original stored records` are both the *same* mechanic
applied at different starting points — a "provenance" disclosure
triangle next to any id-bearing fact, which expands in place to show
the resolved record, never navigating away from the current view. A
dedicated Evidence-view page (§6) still exists for *browsing* evidence
directly, but drilling down *from* a relationship/graph result should
never force that navigation.

## 9. Temporal analysis UI

Timeline view: NormalizedEvents in time order (mirroring `timeline`'s
own sort key — earliest known `TimeAssertion` value, or `created_at`
when none exists), each row expandable to show every `TimeAssertion`
about that event (source, precision, asserted value). Contradictions
and gap findings are cross-linked *into* this view (a contradiction row
links to both disagreeing assertions' timeline entries; a gap finding
links to the absent source's bracketing assertions and the present
source's corroborating ones) rather than being a wholly separate
timeline of their own.

**The required distinction, made explicit in UI copy, not just data
shape:** a gap finding's absent side must never be worded as "the event
did not happen" — the engine's own `GapFinding` docstring and
`correlate/gaps.py`'s module docstring are explicit that this is
structurally impossible to claim honestly ("no observed evidence...
never a claim that an event *should* have existed"). Correct UI
copy: "No matching evidence was found for `<source>` in
`[interval_start, interval_end)`, while `<present_source>` shows
corroborating activity in that same window" — exactly the engine's own
sentence, not a paraphrase that drifts toward "nothing happened here."

## 10. Findings and hypotheses

Four genuinely distinct tiers exist in the actual model, and the UI
must never blur them:

1. **Structural analysis** (a `TimeContradiction`/`GapFinding`/graph
   result) — mechanically, deterministically re-derived every time; not
   persisted by itself; carries no analyst judgment at all.
2. **Tracked finding** (`TrackedGapFinding`/`TrackedTimeContradiction`)
   — the *same* structural fact, given a stable identity and
   optionally an analyst's review annotation (`status`,
   `annotated_by`, `note`). `status=reviewed` means only "an analyst
   looked at this" — never "this was validated" (`TrackedGapFinding`'s
   own docstring is explicit). This is the *only* place in the whole
   engine where a human annotation attaches to a structural fact, and
   it is still not a claim about ground truth.
3. **Hypothesis** — a structurally distinct type (DESIGN.md principle
   3): an analyst's claim *about* the evidence, which can only ever
   *reference* evidence (`EvidenceRef`), never assert a bare fact.
   `inferred_by` is always non-blank; there is no anonymous or
   tool-generated hypothesis today (DESIGN.md principle 7: "AI is not
   part of v0.1 and cannot be authoritative").
4. **Analyst interpretation** — anything a human says *about* a
   Hypothesis or a Finding that is not itself stored as one of the
   above (a Slack message, a report paragraph outside this tool). The
   UI has nothing to render for this tier and must not invent a field
   for it.

UI treatment: distinct visual/label treatment per tier — a structural
result should never look like a Hypothesis card, and a Hypothesis
should never look like a computed, "verified" result. Concretely: graph
results and contradiction/gap findings render with a "structural,
mechanically derived" badge and no status field until tracked; tracked
findings additionally show the annotation workflow (§6's Findings
view); Hypotheses render in their own view with an explicit
`status: proposed/supported/contradicted/withdrawn` chip and the exact
evidence references backing them, never a confidence score (none
exists in the model, and none should be invented).

## 11. Security model

**Local mode (v1's only mode):** the FastAPI server binds to
`127.0.0.1` only, started by the user alongside (or launched by) the
desktop-style app shell; no authentication is needed because the only
network peer possible is a process on the same machine, run by the
same user who already has filesystem access to the case directory —
identical trust boundary to running the `witnessgraph` CLI itself.
CORS is locked to the frontend's own origin (the dev server's or the
packaged app's exact origin, never `*`).

**Path traversal / arbitrary filesystem access — the one real risk a
server introduces that the CLI does not.** The CLI trusts the shell's
own path argument (the user typed it); an HTTP API cannot do the same
without becoming an arbitrary-file-read primitive for anything that
can reach `127.0.0.1` (a malicious page open in the same browser,
e.g.). Mitigation for v1: the server is launched *bound to one case
directory* (passed on the server's own command line/config at startup,
not accepted as a request parameter), so `case_dir` never appears in
an API request at all — every endpoint operates on "the case this
server instance was started for." Opening a *different* case means
restarting the server pointed at it (or, for a "recent cases" picker,
a strictly validated allow-list of directories the user has explicitly
opened via a native file-picker dialog in the desktop shell, never an
arbitrary path string accepted from an HTTP body). This is the
simplest mechanism that closes the traversal risk without adding an
auth system to a fundamentally single-user local tool.

**Sensitive evidence metadata.** SECURITY.md is unambiguous:
Witnessgraph v0.1 "implements no redaction of any kind" — evidence is
stored and exported verbatim. The API/UI inherits this as-is; it must
not silently start redacting (a scope change) or silently assume
redaction happened (a false safety claim). The UI should surface
SECURITY.md's own warning near the Evidence view, not invent a new
warning.

**Read-only vs. write.** Every operation in §4's table is read-only
except the "ack" annotation on a tracked finding/contradiction — a
narrow, already-existing, already-validated write (`--by` required and
non-blank, exactly mirroring the CLI's own validation, which the
service layer must reuse rather than re-implement). No other write
operation exists in v1's scope (see §16); ingest/entity/relationship/
hypothesis creation remain CLI-only for v1, deliberately.

**Remote/hosted mode — explicitly out of scope for v1, noted only so
it is not silently assumed later:** if a hosted, multi-case, possibly
multi-user deployment is ever pursued, it needs real authentication,
per-case authorization, and a redaction/handling policy this document
does not attempt to design — SECURITY.md's "no redaction" posture
would need its own explicit re-evaluation before any hosted mode ships,
since "verbatim evidence, no auth" and "reachable over a network by
more than the one analyst who ingested it" are not compatible.

## 12. Offline-first behavior

The UI opens **local case directories directly** (via the API server
bound to one, per §11) — there is no cloud storage, no hosted case
concept, and nothing in this design introduces one. Import/export of
`.wgcase` archives remains exactly as it is today (`export_case`/
`import_case`, CLI-driven or triggered from the UI's Overview view by
calling the same functions through the service layer) — a portable
file a user moves between machines, not a sync mechanism. The API
server itself needs no network access beyond the loopback interface;
starting it is equivalent to starting the CLI, and the UI provides no
capability the CLI cannot already do standalone.

## 13. Future UI technology (concrete stack)

- **Frontend:** React + TypeScript. Justification: the graph library
  choice (Cytoscape.js) is a JS library either way, so the frontend is
  JS/TS regardless of framework; React is chosen over a lighter
  alternative (e.g. Svelte) only because it is the most widely
  supported target for graph-library React wrapper packages
  (`react-cytoscapejs`) and general component libraries this project
  will eventually need (panels, tables, forms) — not a preference
  claim beyond that.
- **Graph:** Cytoscape.js (via `react-cytoscapejs`). Justification: see
  §3 — purpose-built for exactly the node/edge selection, style-by-
  data-attribute, and programmatic path-highlighting interaction this
  design requires, with a large existing user base in network/security
  graph visualization specifically.
- **Backend:** FastAPI (+ Uvicorn as the ASGI server). Justification:
  see §3 — Pydantic-native (matches the domain's own modeling choice),
  synchronous-friendly (no async database work needed, since
  `SqliteStore` is synchronous and each request opens/closes its own
  `Case`, exactly mirroring the CLI's per-invocation lifecycle),
  auto-generated OpenAPI schema for a typed contract between frontend
  and backend without hand-written API documentation.
- **State/data-fetching (frontend):** a lightweight fetch/cache layer
  (e.g. TanStack Query) rather than a full global-state framework —
  every view's data is a direct, cacheable GET against a case that
  does not change except when a write (§10's ack, or a fresh
  ingest/track run) happens, so this project does not need Redux-style
  global mutable state.
- **Explicitly not added:** no ORM (the engine already owns SQLite
  access via `SqliteStore`; the API layer never touches SQL directly),
  no message queue, no background task runner (every analysis in this
  engine completes synchronously within its own documented bound — see
  §15), no auth library (§11), no GraphQL (the resource shapes are
  already fixed, well-understood dict trees — REST/JSON is a strictly
  simpler match, see §14).

## 14. API design

Resource-oriented, built around the service operations in §4's table
— not a mechanical copy of CLI subcommands. Every response body is
exactly the corresponding `*_to_json(...)` dict tree from §5 (through
the service layer), serialized by FastAPI's normal JSON response
handling (see §5's canonicalization note) — never terminal text, never
a Markdown string outside the one explicit `GET /report` endpoint that
is defined to return Markdown.

| Endpoint | Purpose | Inputs | Response | Read-only? | Provenance |
| --- | --- | --- | --- | --- | --- |
| `GET /case` | Case overview | — | case_overview (§5 gap #1, to be built) | yes | manifest verdict included |
| `GET /entities` | List entities | optional `entity_type` filter | array of Entity shapes | yes | `derived_from` on each |
| `GET /entities/{id}` | One entity | path id | Entity shape, 404 if absent | yes | `derived_from` |
| `GET /relationships` | List relationships | optional `entity_id`, `relationship_type` filters | array of Relationship shapes | yes | `derived_from` per row |
| `GET /relationships/{id}` | One relationship | path id | Relationship shape (+ `evidence_lineage`, always resolved — the API has no reason to withhold it the way `--explain` opts in for a human-scale CLI listing), 404 if absent | yes | full lineage |
| `GET /evidence` | List evidence | optional `source_adapter` filter | array of EvidenceItem shapes (§5 gap #3) | yes | is the root |
| `GET /evidence/{id}` | One evidence item | path id | EvidenceItem shape, 404 if absent | yes | is the root |
| `GET /graph/neighbors` | Ego-network | `entity_id`, `max_depth`, `direction` | neighbors_result_to_json shape | yes | full via `entities`/`evidence_lineage` |
| `GET /graph/path` | One shortest chain | `source_entity_id`, `target_entity_id`, `max_depth`, `direction` | path_result_to_json shape | yes | same |
| `GET /graph/paths` | All tied-shortest chains + evidence independence | `source_entity_id`, `target_entity_id`, `max_depth`, `direction`, `limit` | all_shortest_paths_result_to_json shape (always with explain resolved — see the `relationships/{id}` note above) | yes | same, plus `evidence_independence` |
| `GET /graph/components` | Weak components | `min_size` | components_result_to_json shape | yes | same |
| `GET /timeline` | Normalized events + assertions | optional `event_type` filter | timeline array shape (§5 gap #4, to be built) | yes | each entry's `derived_from` |
| `GET /contradictions` | Structural TimeAssertion conflicts | — | contradictions_to_json shape | yes | both assertions |
| `POST /contradictions/track` | Persist as tracked contradictions | — | `{new, already_tracked}` (mirrors CLI's own `--track` summary) | **write** | n/a |
| `GET /gaps` | Coverage-gap findings | `min_gap_seconds`, `min_corroborating_events`, `refine_source_by_attribute` | gap_analysis_to_json shape | yes | bounding/corroborating ids |
| `POST /gaps/track` | Persist as tracked findings | same params as the analysis that produced them | `{new, already_tracked}` | **write** | n/a |
| `GET /findings` | Tracked gap findings | — | array of tracked_finding_to_json shapes | yes | `still_reproduced` live |
| `GET /findings/{id}` | One tracked finding | path id | tracked_finding_to_json shape, 404 if absent | yes | same |
| `POST /findings/{id}/ack` | Annotate a tracked finding | `status`, `by` (required, non-blank), optional `note` | updated tracked_finding_to_json shape | **write** | records `annotated_by`/`annotated_at` |
| `GET /contradiction-findings` | Tracked contradictions | — | array of tracked_contradiction_to_json shapes | yes | — |
| `GET /contradiction-findings/{id}` | One tracked contradiction | path id | shape, 404 if absent | yes | — |
| `POST /contradiction-findings/{id}/ack` | Annotate | `status`, `by`, optional `note` | updated shape | **write** | — |
| `GET /hypotheses` | List hypotheses | — | array of Hypothesis shapes (pass-through of the model) | yes | each `EvidenceRef` |
| `GET /report` | Full-case document | `format=markdown\|json` | Markdown text or the report JSON tree | yes | is a provenance-complete snapshot |
| `POST /verify` | Recompute + compare manifest | — | replay_result shape (§5 gap #5, to be built) | yes (never mutates) | manifest hashes |

Errors: a 404 for an unknown id (mirroring the CLI's own "no such
entity"/"no such relationship" clean-failure convention, never a raw
exception); a 400 for an invalid parameter (mirroring `typer.BadParameter`'s
existing validation — e.g. `max_depth`/`limit` bounds, `min_gap_seconds`
required-and-positive) with the same message text the CLI already
produces, so the two surfaces never silently diverge on what counts as
valid input.

## 15. Graph data transfer

**No second graph model.** The API never introduces its own
"nodes"/"edges" schema distinct from `Entity`/`Relationship` — the
brief's own instruction ("do not invent a second graph model") is
already how every existing `*_result_to_json` function behaves: a
result's `reached`/`steps`/`paths`/`components` arrays are built
directly from `Entity`/`Relationship` fields, never a parallel
"visualization node" type.

Where the frontend needs a `{nodes: [...], edges: [...]}` shape for
Cytoscape.js specifically (that library's own input format), this
transformation belongs at the **application/service boundary** (per
Part 14's own instruction: "place it in the application/API boundary,
not the frontend") — a thin mapping function, e.g.
`to_cytoscape_elements(entities, relationships)`, producing
`{data: {id, label, entity_type, ...}}` per node and
`{data: {id, source, target, relationship_type, ...}}` per edge, with
every field traceable 1:1 back to the `Entity`/`Relationship` record it
came from (never a synthesized id, never a dropped field). This
function lives in `witnessgraph.service` (§4) or a thin
`api/transform.py` immediately behind it — never in the React
codebase, so the mapping stays covered by the same test discipline
(§21) as everything else, and a future non-Cytoscape frontend would
not need to re-derive it.

## 16. Performance

**The current "load relationships into memory" architecture (see
`correlate/graph.py::_build_adjacency`, which loads and sorts every
relationship once per call) is appropriate for v1** — every graph
operation in this engine is already bounded (BFS is O(V+E); `graph
paths`' extra backward BFS pass and capped DFS add only a small,
documented constant factor; `--limit`/`--max-depth` are validated
before expensive work per this codebase's own established convention).
For a case sized like `examples/sample-case` (a handful of entities) or
even a few thousand relationships, this is instant. The first
realistic bottleneck is not traversal — it is:

1. **Whole-graph rendering.** `graph components --format json` with no
   `--min-size` filter, or a `graph neighbors` call at a large
   `--max-depth` on a densely-connected case, can return (and the
   frontend would then have to lay out) thousands of nodes/edges at
   once. Mitigation for v1: default the Graph view to a bounded ego-
   network (`--max-depth 1`or `2`) around a selected entity rather than
   rendering the whole case by default; make "show the whole graph"
   an explicit, opt-in action with a visible node-count warning before
   it runs, exactly mirroring how `graph neighbors` itself already
   defaults to depth 1 rather than unbounded.
2. **`--explain` payload size.** Resolving every `derived_from` id in a
   large `graph paths` result (many tied chains, each with several
   steps) multiplies the response size by however much evidence
   metadata gets attached. `--limit`'s existing cap (default 10, max
   500) already bounds this; the API should keep the same default and
   the same ceiling rather than raising it "for the UI's convenience."
3. **JSON payload size for the full report.** `report --format json`
   serializes every EvidenceItem and the full timeline — fine for
   `examples/sample-case`, potentially large for a case with heavy
   ingestion. This is exactly why §5's case-overview gap should be
   filled with a *lightweight*, count-only endpoint rather than having
   the Overview view fetch the full report just to display four
   numbers.

No premature optimization is proposed: no caching layer, no pagination
scheme, no background job queue for v1 — the engine's existing bounds
(§2's `MAX_ALLOWED_DEPTH`/`MAX_ALLOWED_PATHS_LIMIT` validation pattern)
are the correct first line of defense, and the UI should simply respect
the same defaults the CLI already ships with.

## 17. V1 scope

**MUST HAVE**

1. Open a local case (server started against one case directory, §11).
2. Case Overview (once §5 gap #1 is filled).
3. Interactive Graph view: entity/relationship selection, `graph path`,
   `graph paths` with evidence-independence rendering (§7) — this is
   the feature that makes the research identity legible; it is the one
   view that cannot be deferred.
4. Relationship detail panel with full evidence lineage (provenance
   drill-down, §8).
5. Entity detail panel.
6. Evidence detail (at minimum reachable via drill-down from a
   relationship; a full standalone Evidence *browse* view can be
   SHOULD HAVE — see below).

**SHOULD HAVE**

7. Components view (toggle, on top of the same Graph canvas).
8. Timeline view (once §5 gap #4 is filled).
9. Contradictions + Gaps views (read-only display; the API/service
   support already exists in full).
10. Standalone Evidence browse view (not just drill-down).
11. Findings view with the ack/annotate workflow (the one write
    operation, §10/§11) — valuable, but the read-only structural views
    above demonstrate the engine's identity on their own even without
    it.

**DEFERRED**

12. Hypotheses view (read-only display is easy; anything beyond that —
    proposing/supporting a hypothesis from the UI — is a new write
    surface not needed to demonstrate the engine).
13. Report view (the Markdown/JSON report already exists standalone;
    embedding it is convenience, not core to the demonstration).
14. Export/import from the UI (works fine from the CLI today; wiring
    it into the UI is a small, low-priority convenience).
15. Multi-case management UI (switching cases without restarting the
    server) — deferred by §11's own security design, which deliberately
    binds one server instance to one case directory for v1.
16. Anything in §18.

## 18. What not to build (explicit non-goals for the UI, not only V1)

- AI-generated conclusions of any kind (DESIGN.md principle 7: no
  AI/assistant integration exists, and none should be simulated by the
  UI presenting a computed result as if it were an authoritative
  narrative).
- Attack attribution, "who did this," or any causal narrative — the
  engine's own module docstrings are explicit that connectivity is
  never causation; the UI must hold that line as strictly in copy/
  labeling as the engine holds it in code.
- Automated guilt/culpability determination of any kind.
- Generic risk scores, confidence percentages, or "likelihood" —
  no such field exists anywhere in the domain model, and none should
  be invented for the UI's benefit.
- Cloud SaaS infrastructure, hosted multi-tenant case storage (§11's
  remote-mode note stands: out of scope until explicitly re-designed).
- Collaborative multi-user permissions/roles — v1 is single-analyst,
  single-machine, matching the engine's own current scope.
- Massive enterprise ingestion pipelines, mobile acquisition, or device
  imaging — entirely outside this project's layer (evidence is already
  ingested by the time Witnessgraph sees it).
- Decorative dashboards (charts/gauges that do not correspond to a
  structured result this engine actually computes).
- Unnecessary authentication for local mode (§11) — a login screen for
  a single-user local tool would be security theater, not security.
- A second graph model, a graph database, or a second implementation of
  any correlation logic in the frontend (the standing rule this entire
  document exists to protect).

## 19. Researcher demonstration (3–5 minutes)

1. **Open a case** (the `examples/sample-case` synthetic case) — show
   the Overview: evidence/entity/relationship counts, manifest
   verified.
2. **Evidence-backed entities.** Open the Entities view; pick the
   `user` entity (`jsmith`); show its detail panel and its
   `derived_from` evidence — "every entity here points back to the
   record that established it; nothing is inferred."
3. **Navigate a relationship.** From that entity, open the Graph view;
   click the `authenticated_as` edge to the `host` entity; show its
   evidence lineage in the drill-down panel.
4. **Compute a path.** Select the `user` and the `ip` entity two hops
   away; run `graph path`; the UI highlights the two-hop chain.
5. **Show multiple shortest chains.** On a case built to have a
   diamond shape (a small synthetic addition to the demo case, not a
   production feature), run `graph paths`; show two highlighted chains
   and the "2 chains found" count.
6. **Show evidence overlap/independence.** With `--explain` open, show
   the two chains' `evidence_independence` panel: "structurally
   distinct: yes. Evidence-independent: no — both cite EvidenceItem
   `<id>`" (using the earlier-built overlap fixture) — this is the
   single most identity-defining moment of the demo: a plain graph
   viewer cannot make this distinction, because it does not track
   evidence at all.
7. **Drill into provenance** one more time from that shared
   EvidenceItem id, showing `source_adapter`/`source_locator`/
   `collected_at` — "every fact on screen traces back to a real,
   inspectable record."
8. **Show a contradiction or gap.** Open the Contradictions view; show
   two disagreeing TimeAssertions about the same event, with the UI
   copy making clear neither is marked as "the truth."
9. **State the boundary explicitly, out loud, pointing at the
   screen:** "This tool never tells you who did something or why — it
   tells you what is connected, what is disjoint, what disagrees, and
   exactly which record backs each of those facts. The moment it would
   have to guess, it stops and shows you the boundary instead."

This demo deliberately avoids a generic dashboard tour — every step
maps to a structural or provenance capability unique to this engine,
culminating in step 6, which no plain graph-visualization tool can
reproduce without the evidence-independence machinery this project
built specifically to make that distinction honest.

## 20. Where this document lives, and what happens next

This file is `docs/phase-ui-v1-architecture-design.md`, following this
project's existing `docs/phaseN-...-design.md` convention for a
design-before-implementation document (see `docs/phase5-v0.5-gap-analysis-design.md`
for the precedent this mirrors in structure and tone). A future
implementation session should:

1. Fill the five structured-contract gaps in §5 (small, additive,
   fully in the existing `*_to_json` style — no new domain concepts).
2. Introduce `witnessgraph.service` (§4) as a thin layer the *existing*
   `cli/main.py` refactors to call too, so the CLI and the future API
   are provably calling the same code, not two paths that can drift.
3. Add FastAPI (+ Uvicorn) as a new, explicitly-scoped dependency at
   that point — not before, per this session's own instruction.
4. Build the API (§14) as a direct, thin wrapper over
   `witnessgraph.service`.
5. Build the React/Cytoscape.js frontend (§13) against that API.

No part of this sequencing requires re-deriving the architecture from
scratch — that is the point of writing it down now.
