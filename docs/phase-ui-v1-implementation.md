# Witnessgraph UI v1 — Implementation Report

Status: **complete, hardened first vertical slice.** Written against the
architecture in `docs/phase-ui-v1-architecture-design.md`, which this
document does not redesign — it records what was actually built, where
it matches that design exactly, and the handful of places it deviates
or extends, with the reasoning for each. Read the architecture document
first; this one assumes it. This revision supersedes the initial
vertical-slice pass: it adds the Evidence/Timeline/Gaps/Findings views,
contradiction/gap tracking, and the acknowledgement workflow that pass
deliberately deferred, and records a review of the "always resolve
explainability data" decision made in that first pass.

## 1. What exists now

```
existing Witnessgraph engine (core/store/correlate/replay, unchanged)
        |
witnessgraph.service        <- thin (§2)
        |
witnessgraph.api            <- FastAPI, local-only (§3)
        |
frontend/ (React + TS + Cytoscape.js)   <- §4
```

The engine itself (`core/`, `store/`, `ingest/`, `correlate/`, `replay/`)
was **not modified in behavior** — every change to it is either a new,
additive `*_to_json`/public-wrapper function (never touching an existing
one's output) or a pure aggregation/projection function
(`correlate/overview.py`, `correlate/timeline.py`). 804 tests pass (731
pre-existing + 73 new across both passes); `ruff check .` and
`mypy src` are both clean; the frontend has 35 Vitest tests and clean
`oxlint`/`tsc --noEmit`/`vite build`.

## 2. Service layer (`src/witnessgraph/service/`)

Modules, each a thin wrapper over the corresponding `correlate`/`store`
call, matching the CLI's own case-opening/validation/error sequence:

- `errors.py` — `CaseNotFoundError`, `CaseUnreadableError`,
  `EntityNotFoundError`, `RelationshipNotFoundError`,
  `TrackedFindingNotFoundError`, `TrackedContradictionNotFoundError`,
  `ValidationError`. A closed, small set the CLI and the API each
  translate into their own idiom (an exit code + stderr line, or an
  HTTP status + JSON body).
- `case_service.py` — `open_case`, `get_case_overview` (architecture §5
  gap #1, via `correlate.overview`).
- `entities_service.py` — `list_entities`/`get_entity`.
- `relationships_service.py` — `list_relationships`/`get_relationship`
  (the latter always resolves `evidence_lineage`).
- `graph_service.py` — `neighbors`/`path`/`paths`/`components`, each
  taking an `explain: bool` so the CLI keeps its opt-in verbosity
  control while the API always passes `explain=True` (see §5).
- `evidence_service.py` — `list_evidence` (Evidence-browse, second pass)
  and `resolve_evidence` (single-reference resolution, first pass).
- `timeline_service.py` — `get_timeline` (architecture §5 gap #4, second
  pass), wrapping the new `correlate.timeline.build_timeline_json`.
- `contradictions_service.py` — `list_contradictions` (read) and
  `track_detected_contradictions` (write, second pass).
- `gaps_service.py` — `analyze_gaps` (read) and `track_gaps` (write,
  second pass), mirroring `cli.main.gaps`'s validation and
  read-then-persist transaction ordering exactly.
- `findings_service.py` / `contradiction_findings_service.py` (second
  pass) — list/get/ack for each tracked-finding kind. `ack_*` requires a
  non-blank analyst identity and accepts only the three existing
  `FindingStatus` values (`open`/`reviewed`/`dismissed`) — there is no
  code path that can produce or accept "validated"/"confirmed".

**Additive engine changes made to support this layer** (all covered by
tests, none changing any existing output):

- `core/provenance.py`: public `manifest_verdict()`, shared by
  `report/render_json.py` and `correlate.overview`.
- `core/entities.py`: public `entity_to_json()`, reused by
  `report/render_json._build_entities`.
- `correlate/graph.py`: public `relationship_to_json`,
  `resolved_evidence_ref_to_json`, `evidence_item_to_json`,
  `normalized_event_to_json` — thin aliases of the pre-existing private
  functions, exposed for callers outside this module.
- `correlate/overview.py` — case counts + manifest verdict (gap #1).
- `correlate/timeline.py` (second pass) — `build_timeline_json`,
  extracted out of `report/render_json.py`'s private `_build_timeline`
  so both the report renderer and the service layer share one
  implementation. **No second temporal model**: identical
  `NormalizedEvent`/`TimeAssertion` fields, identical sort key
  (earliest known `TimeAssertion` value, or `created_at`), identical
  ordering to before this module existed.

**CLI refactor (§4's "where practical"):** `cli.main.entities_list` and
`cli.main.relationships_list` call the service layer instead of
duplicating store access/filtering (safe: `SqliteStore.list_*` already
returns rows `ORDER BY id`, so the service layer's own re-sort is
byte-identical). **Deliberately not refactored:** `entities_show`/
`relationships_show` (nothing to converge — already a single
`store.get_*` call) and every `graph_app`/`gaps`/`contradictions`
command (their JSON branches already call the exact same
`correlate.*.*_to_json` functions the service layer calls; their text
branches need the raw dataclass result, which the service layer
intentionally does not expose, to avoid computing results twice per
invocation). This is a narrower CLI refactor than a maximal reading of
"where practical" might attempt, chosen to avoid destabilizing the
existing CLI integration test suite for marginal benefit.

## 3. API (`src/witnessgraph/api/`)

FastAPI app factory: `create_app(case_dir, *, allowed_origins=None)`.
Binds to exactly one case directory, probed once at build time (fails
fast) — `case_dir` is never a request parameter anywhere in this
package. Launcher: `api/__main__.py` (`witnessgraph-api` console
script), hardcoding `host="127.0.0.1"` (not a CLI flag).

Every route calls `witnessgraph.service`, never `correlate`/`store`
directly, and returns `api/responses.json_response`'s
`core.ids.canonical_json_bytes` encoding (byte-identical datetime
formatting to the CLI's own `--format json`):

| Endpoint | Notes |
| --- | --- |
| `GET /case` | Case overview. |
| `GET /entities`, `GET /entities/{id}` | Optional `entity_type` filter. |
| `GET /relationships`, `GET /relationships/{id}` | Optional `entity_id`/`relationship_type` filters; single fetch always resolves `evidence_lineage`. |
| `GET /evidence` | List, optional `source_adapter` filter (second pass). |
| `GET /evidence/{id}` | Resolve one reference; always 200, `kind` distinguishes `evidence_item`/`normalized_event`/`not_found`. |
| `GET /graph/neighbors`, `/graph/path`, `/graph/paths`, `/graph/components` | Always explain-resolved — see §5. |
| `GET /timeline` | Optional `event_type` filter (second pass). |
| `GET /contradictions` | Read-only detection. |
| `POST /contradictions/track` | Write: persist each detected contradiction (second pass). |
| `GET /gaps` | Requires `min_gap_seconds`; optional `min_corroborating_events`, `refine_source_by_attribute` (second pass). |
| `POST /gaps/track` | Write: same params, persists findings (second pass). |
| `GET /findings`, `GET /findings/{id}` | Tracked gap findings, `still_reproduced` live-recomputed (second pass). |
| `POST /findings/{id}/ack` | Write: `{status, by, note?}` body (`AckRequest`), requires non-blank `by` (second pass). |
| `GET /contradiction-findings`, `GET /contradiction-findings/{id}` | Tracked contradictions (second pass). |
| `POST /contradiction-findings/{id}/ack` | Write, same shape (second pass). |

**Reviewed per this milestone's explicit instruction: "every graph
endpoint always resolves explainability data."** Verdict: **(A) appropriate
and bounded — left unchanged.**

- `neighbors`/`path`/`paths` are bounded by `max_depth`/`limit`, the
  exact same bound the CLI itself enforces; explain adds only O(1)
  lookups per already-bounded result element (an entity's resolved
  type/identifiers, a relationship's resolved `derived_from` ids) — no
  new order-of-growth cost, and no unbounded traversal is introduced.
- `components` (no `max_depth`/`limit` — bounded only by `min_size` and
  case size) is the one endpoint where a large, unfiltered case could
  mean a large response. This is a **pre-existing** cost of calling
  `/graph/components` with no `min_size` at all, not a new cost explain
  introduces (explain is a linear multiplier on an already-unbounded
  result, not a change in whether it's bounded) — and it is exactly the
  concern architecture §16 already names and already assigns to the
  *frontend* to mitigate: default to a bounded view, make "show
  everything" an explicit, warned opt-in. The frontend does exactly
  that (`GraphPanel`'s `FULL_GRAPH_WARNING_THRESHOLD`); no backend
  change was made, and none is warranted — restoring a CLI-style
  `?explain=` toggle here would only reintroduce a second round-trip
  for data a JSON caller almost always wants, for a cost the frontend
  already bounds at the point that actually matters.
- Conclusion: the decision from the first implementation pass is
  **retained as-is**, per this milestone's own instruction not to
  "blindly restore the CLI's exact `--explain` semantics" without a
  concrete reason.

**Error mapping** (`api/errors.py`): `*NotFoundError` → 404 with the
CLI's own message text; `ValidationError` → 400; a validation failure
FastAPI/Pydantic itself catches (bad query type, malformed `AckRequest`
body, an invalid `FindingStatus` string) → 422, Starlette's own
convention — never hand-duplicated as a second 400 implementation.

**Security** (see also `SECURITY.md`): binds to `127.0.0.1` only; CORS
allows exactly the frontend dev server's origins, never `*`; no route,
query parameter, or request body accepts a filesystem path (verified by
an OpenAPI-schema-inspecting test); no SQL is ever written in `api/`;
one per-request `Case`, opened and closed by a FastAPI dependency.

## 4. Frontend (`frontend/`)

Vite + React 19 + TypeScript, Cytoscape.js core (no `react-cytoscapejs`
— see §5). TanStack Query for data-fetching/cache/mutation-invalidation.

```
frontend/src/
├── api/          # types.ts (mirrors backend JSON contracts), client.ts (fetch wrapper)
├── graph/        # elements.ts (Entity/Relationship/GraphComponent -> Cytoscape elements),
│                 # CytoscapeGraph.tsx (thin wrapper), stylesheet.ts, GraphPanel.tsx (mode/overlay orchestration)
├── components/   # CaseHeader, EntityList/Detail, RelationshipList/Detail, Provenance,
│                 # EvidenceIndependencePanel, PathExplorer, ComponentsPanel, EvidencePanel,
│                 # TimelinePanel, ContradictionsPanel, GapsPanel, FindingsPanel, ErrorScreen
├── App.tsx       # top-level nav + Graph-workspace state (selection, overlay, component focus)
└── main.tsx      # QueryClientProvider
```

**Information architecture:** a persistent case-overview header (always
visible — counts + manifest verdict, refreshed after every tracking/ack
mutation) plus a top-level nav: **Graph** (default; sidebar tabs
Entities/Relationships/Components), **Evidence**, **Timeline**,
**Contradictions**, **Gaps**, **Findings** — matching the architecture's
domain-organized structure, not the CLI's command list. The graph
remains the single central workspace; every other view is a focused,
single-purpose structured-data screen, never a decorative dashboard.

**Graph view:** "full case graph" (built directly from the
already-fetched entity/relationship lists) below a small entity-count
threshold, else a bounded "ego network" (`GET /graph/neighbors`) by
default with "show the whole graph" as an explicit, warned opt-in
(§16). A third mode, **component focus** — selecting a row in the new
Components sidebar tab renders exactly that `GraphComponent`'s own
entities/relationships (`graph/elements.ts::componentElements`, zero
recomputation) — coexists with path-overlay mode; selecting one clears
the other. Useful empty states throughout ("select an entity to explore
its neighborhood", "nothing to render — no entities yet"). Layout is
always deterministic: `grid` (pre-sorted by id) for the full graph,
`breadthfirst` for ego/path/component views — never force-directed.

**Path / tied-shortest-paths:** unchanged from the first pass —
`PathExplorer` renders `GET /graph/path`/`/graph/paths` results as a
per-chain-colored overlay on the graph canvas, with an explicit "clear
overlay" action distinct from "clear component focus".

**Evidence independence (the critical interaction):**
`EvidenceIndependencePanel` renders the structural fact ("N
structurally distinct chains…") and the evidence fact
("evidence-independent: yes/no/not applicable…") as two separate,
labeled sentences — never merged, never "proof"/"corroboration"/
"confirms", never coercing a `null` verdict to `true`. Verified in this
pass both by the existing component tests and by a real, live
end-to-end demo against a synthetic diamond-shaped case with
deliberately shared evidence (see §7).

**Provenance UX:** unchanged mechanism (`components/Provenance.tsx`,
expandable inline disclosure) — extended targets: an Evidence-browse row
(§ new in this pass) and a Timeline entry's time assertions.

**Evidence browsing (`EvidencePanel`, new):** a filterable table of
every EvidenceItem's metadata (id, source_adapter, source_locator,
collected_at, raw_size_bytes) — content-addressed identifiers and
recorded locator strings only; no raw blob content is ever fetched or
rendered, and no code path in this view reads a file from disk (the
`source_locator` string is metadata the engine already recorded at
ingest time, exactly as the CLI's own `report`/`--explain` output
already displays it).

**Timeline (`TimelinePanel`, new):** `GET /timeline`'s structured JSON
only, ordered exactly as the engine orders it. Each event expands to
show every `TimeAssertion` about it, with explicit copy pointing to
Contradictions for events where those assertions disagree. No parsing
of `timeline`'s CLI text output anywhere — the CLI and the UI share the
same structured source.

**Contradictions (`ContradictionsPanel`, extended):** detected
contradictions plus the one write action, "track as findings"
(`POST /contradictions/track`), reported as `{new, already_tracked}`.
Never renders either assertion as "the truth"; tracking is described
as "persisting with a stable id for review", never "resolving".

**Gaps (`GapsPanel`, new):** a form for the engine's own
required/optional parameters (`min_gap_seconds` has no default the
engine claims is objectively correct, so none is silently chosen),
"Analyze", and — only once an analysis found something — "Track
findings". Copy is exact and tested: a finding is rendered as "no
evidence from `<source>` … while `<source>` has corroborating
activity", **never** "the event did not happen" or "never happened".

**Findings (`FindingsPanel`, new):** two sections — tracked gap
findings (with the live `still_reproduced` indicator) and tracked
contradiction findings (deliberately without one — see
`TrackedTimeContradiction`'s own docstring) — each with an
acknowledgement form (status/by/note). The status `<select>` only ever
offers `open`/`reviewed`/`dismissed`; there is no `validated`/
`confirmed` option anywhere in this codebase, frontend included.

## 5. Deliberate deviations / extensions, and why

1. **No `react-cytoscapejs`.** Cytoscape.js core via a small React
   wrapper (`graph/CytoscapeGraph.tsx`). One fewer dependency, no
   wrapper-package React-19 compatibility surface, full control over
   layout determinism. The architecture's actual requirement
   (Cytoscape.js's interaction model) is met in full.
2. **Every graph endpoint always resolves explainability data** — see
   §3's review. Retained after explicit re-examination this pass, not
   merely carried over unexamined.
3. **`GET /evidence/{id}` always returns 200** (`kind: "not_found"` is
   data, not a 404) — a dangling reference is a real, documented engine
   possibility, reported the same way `--explain` reports it, never
   raised as an error.
4. **422 (not 400) for FastAPI/Pydantic's own request-shape validation**
   (bad query type, malformed `AckRequest` body) — every
   *application-level* validation (entity/relationship existence,
   `max_depth`/`limit`/`min_gap_seconds` bounds, non-blank `by`) still
   maps to the CLI's own 404/400 distinction exactly.
5. **`POST /gaps/track` and `POST /contradictions/track` take query
   parameters, not a JSON body** — consistent with `GET /gaps` using
   the same parameter set, and avoids a body schema for what is
   structurally identical to the GET's own filter parameters.

## 6. Genuinely deferred (not built)

Per the mission's explicit DEFERRED list plus items judged out of scope
for a UI whose job is to expose the *existing* engine, not extend it:

- Hypotheses view, embedded Report view, UI-driven export/import,
  multi-case switching (explicitly deferred by both milestones).
- `POST /verify` / a `ReplayResult` JSON contract (architecture §5 gap
  #5) — low priority; the CLI's `verify`/`replay` already cover it.
- CLI refactor of `graph_app`/`gaps`/`contradictions` commands and
  `entities_show`/`relationships_show` — see §2's explicit reasoning.
- A history/audit trail for finding/contradiction acknowledgements —
  the engine itself has none (`annotate_tracked_*` replaces, never
  appends); the UI does not invent one.

## 7. Manual end-to-end verification

Performed against a live `witnessgraph-api` server (not just unit/
component tests) using the existing `examples/sample-case` pipeline,
extended with one synthetic second host to form a diamond
(`user → host-A → ip`, `user → host-B → ip`, both paths' relationships
citing the *same* EvidenceItem) and one deliberately conflicting
second `TimeAssertion` on the case's `logon` event:

1. Started `witnessgraph-api` bound to the case; started the frontend
   dev server; opened it in a real browser.
2. Overview header showed correct counts and `MATCH` manifest verdict.
3. Graph view: selected an entity (opened its detail panel with
   expandable provenance resolving to a real `EvidenceItem`), selected
   a relationship (its evidence-lineage disclosure), ran `graph path`
   and `graph paths`.
4. `graph paths` returned 2 structurally distinct chains, rendered as
   two distinctly colored overlays; the Evidence Independence panel
   correctly reported "evidence-independent: no — 1 EvidenceItem cited
   by more than one chain", with the shared id shown.
5. Components tab: one component (4 entities), clicking it focused
   exactly that cluster in the graph canvas via `breadthfirst` layout.
6. Evidence tab: all 9 ingested EvidenceItems listed with real
   source_adapter/source_locator/collected_at, filterable.
7. Timeline tab: 9 events in time order; expanding the `logon` event
   showed both disagreeing TimeAssertions.
8. Contradictions tab: the same disagreement detected and displayed;
   clicked "Track as findings" → `{new: 1, already_tracked: 0}`; the
   header's "Tracked contradictions" count updated live from 0 to 1
   without a page reload (a real staleness bug caught and fixed during
   this verification — see the git history for the fix).
9. Findings tab: the tracked contradiction appeared; entered an analyst
   identity and submitted an acknowledgement → status changed to
   "reviewed (by demo-analyst)" in place.
10. Gaps tab: ran an analysis against the case's real (undeclared-source)
    evidence; got the honest "no coverage gaps found at this threshold"
    result plus real exclusion counts — not a fabricated result.
11. Checked the browser console throughout: no errors.

## 8. Honest limitations

- The frontend's production bundle is ~730 KB (mostly Cytoscape.js),
  above Vite's default 500 KB warning threshold. Not addressed with
  code-splitting — a local, single-analyst desktop-style tool has no
  CDN transfer-budget pressure comparable to a public website.
- Automated end-to-end coverage is Vitest + Testing Library at the
  component level (35 tests) plus the manual, real-browser verification
  in §7 — there is no committed Playwright/Cypress browser-automation
  suite.
- This UI does not, and cannot, prove evidence independence in an
  epistemic sense — it renders exactly the structural and provenance
  facts the engine computes, nothing more. It does not replace
  acquisition or artifact-analysis suites; its contribution is making
  evidence-backed relationships and reasoning explicit, traceable,
  reproducible, and machine-queryable — see the architecture's own
  researcher-demo closing line (§19 step 9), which this implementation
  does not weaken anywhere.
