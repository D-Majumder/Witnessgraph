# Witnessgraph UI v1 — Implementation Report

Status: **first working vertical slice implemented.** Written against
the architecture in `docs/phase-ui-v1-architecture-design.md`, which
this document does not redesign — it records what was actually built,
where it matches that design exactly, and the handful of places it
deviates or extends, with the reasoning for each. Read the architecture
document first; this one assumes it.

## 1. What exists now

```
existing Witnessgraph engine (core/store/correlate/replay, unchanged)
        |
witnessgraph.service        <- NEW, thin (§2 below)
        |
witnessgraph.api            <- NEW, FastAPI, local-only (§3 below)
        |
frontend/ (React + TS + Cytoscape.js)   <- NEW (§4 below)
```

The engine itself (`core/`, `store/`, `ingest/`, `correlate/`, `replay/`)
was **not modified in behavior** — every change to it is either a new,
additive `*_to_json`/public-wrapper function (never touching an existing
one's output) or a pure aggregation function (`correlate/overview.py`).
778 tests pass (731 pre-existing + 47 new); `ruff check .` and
`mypy src` are both clean.

## 2. Service layer (`src/witnessgraph/service/`)

Modules, each a thin wrapper over the corresponding `correlate`/`store`
call, matching the CLI's own case-opening/validation/error sequence:

- `errors.py` — `CaseNotFoundError`, `CaseUnreadableError`,
  `EntityNotFoundError`, `RelationshipNotFoundError`, `ValidationError`.
  A closed, small set the CLI and the API each translate into their own
  idiom (an exit code + stderr line, or an HTTP status + JSON body).
- `case_service.py` — `open_case` (mirrors `cli.main._open_case_or_fail`
  exactly), `get_case_overview` (fills architecture §5 gap #1 via the
  new `correlate.overview` module).
- `entities_service.py` — `list_entities`/`get_entity`.
- `relationships_service.py` — `list_relationships`/`get_relationship`
  (the latter always resolves `evidence_lineage` — see §3's API note).
- `graph_service.py` — `neighbors`/`path`/`paths`/`components`, each
  taking an `explain: bool` so the CLI can keep its existing opt-in
  verbosity control while the API always passes `explain=True`.
- `contradictions_service.py` — `list_contradictions`.
- `evidence_service.py` — `resolve_evidence` (see §5, a deliberate small
  extension beyond the architecture's original gap list).

**Small, additive engine changes made to support this layer** (all
covered by new/existing tests, none changing any existing output):

- `core/provenance.py`: extracted `manifest_verdict()` out of
  `report/render_json.py`'s private `_build_manifest`, so both the
  report renderer and `correlate.overview` compute the exact same
  verdict from the exact same logic. `_build_manifest`'s own output is
  byte-for-byte unchanged.
- `core/entities.py`: added public `entity_to_json()`, matching
  `report/render_json._build_entities`'s per-entity shape exactly;
  `_build_entities` now calls it instead of duplicating the dict.
- `correlate/graph.py`: added public `relationship_to_json()` and
  `resolved_evidence_ref_to_json()` as thin aliases of the existing
  private `_relationship_to_json`/`_resolved_evidence_ref_to_json` —
  no behavior change, just a supported entry point for callers outside
  this module.
- `correlate/overview.py` (new module): `CaseOverview` dataclass +
  `compute_case_overview`/`case_overview_to_json`, filling architecture
  §5 gap #1 exactly as that document specified.

**CLI refactor (§4's "where practical"):** `cli.main.entities_list` and
`cli.main.relationships_list` now call `entities_service.list_entities`/
`relationships_service.list_relationships` instead of duplicating
`Store.list_entities()`/inline `--entity` filtering. This is safe because
`SqliteStore.list_*` already returns rows `ORDER BY id`, so the service
layer's own (redundant, harmless) re-sort produces byte-identical output
to before. **Deliberately not refactored:** `entities_show`/
`relationships_show` (already a single `store.get_*` call plus
`model_dump_json()` — there is no duplicated logic to eliminate, and
changing their output encoding to the service layer's canonical-JSON
shape would be a real, untested-for behavior change to existing CLI
output for zero benefit) and every `graph_app` command (their JSON
branches already call the exact same `correlate.graph.*_to_json`
functions the service layer calls — there is no second implementation to
converge; their text-mode branches need the raw dataclass result, which
the service layer intentionally does not expose, to avoid computing
results twice per invocation). This is a narrower CLI refactor than a
maximal reading of "where practical" might attempt, chosen specifically
to avoid destabilizing the 34+ existing CLI integration tests for
marginal benefit — see §7 for the honest accounting of this tradeoff.

## 3. API (`src/witnessgraph/api/`)

FastAPI app factory: `create_app(case_dir, *, allowed_origins=None)`
(`api/app.py`). Binds to exactly one case directory, probed once at
build time (fails fast, mirroring `_open_case_or_fail`) — `case_dir`
is never a request parameter anywhere in this package. Launcher:
`api/__main__.py`, exposed as the `witnessgraph-api` console script,
which hardcodes `host="127.0.0.1"` (not a CLI flag — see
`docs/phase-ui-v1-architecture-design.md` §11's "no accidental remote
bind").

Routes (`api/routes/*.py`), each a thin call into `witnessgraph.service`
— never into `correlate`/`store` directly — with responses encoded via
`api/responses.json_response`, which calls `core.ids.canonical_json_bytes`
directly (the architecture §5's "simplest, zero new formatting code"
option), so every JSON body's datetime formatting (UTC, `Z`-suffixed) is
byte-identical to the CLI's own `--format json` output for the same
underlying dict tree:

| Endpoint | Notes |
| --- | --- |
| `GET /case` | Case overview (§2). |
| `GET /entities`, `GET /entities/{id}` | Optional `entity_type` filter. |
| `GET /relationships`, `GET /relationships/{id}` | Optional `entity_id`/`relationship_type` filters; single-object fetch always resolves `evidence_lineage`. |
| `GET /evidence/{id}` | See §5 — new, small, deliberately justified. |
| `GET /graph/neighbors`, `/graph/path`, `/graph/paths`, `/graph/components` | See the deviation in §5. |
| `GET /contradictions` | Read-only, parameter-free; included because it needed no new contract. |

**Deviation from architecture §14 (documented, not silent): every graph
endpoint always resolves explainability data** (`entities`,
`evidence_lineage`, and — for `/graph/paths` — `evidence_independence`);
there is no `?explain=` query parameter. The architecture's own §14
table already decided this for `GET /relationships/{id}` ("the API has
no reason to withhold it the way `--explain` opts in for a human-scale
CLI listing") and explicitly generalized it to `GET /graph/paths`
("always with explain resolved"). This implementation applies the same
reasoning to `/graph/neighbors`, `/graph/path`, and `/graph/components`
too: the CLI's `--explain` flag exists only to keep a human-scale
*text* listing short by default, which has no equivalent for a machine
JSON caller that would otherwise have to make a second round-trip for
data it almost always wants. `witnessgraph.service.graph_service`'s
functions still accept an `explain: bool` parameter, so the CLI keeps
its existing opt-in exactly as before.

**Error mapping** (`api/errors.py`): `EntityNotFoundError`/
`RelationshipNotFoundError` → 404 with the CLI's own exact message text
(`"no such entity: <id>"`); `ValidationError` → 400; a validation
failure FastAPI itself catches (an out-of-range/mistyped query
parameter Pydantic rejects before the service layer ever runs) → 422,
Starlette's own convention — a real, minor deviation from the
architecture's "a 400 for an invalid parameter" (§14), accepted because
duplicating FastAPI's own request-parsing validation as hand-written
400s would be exactly the kind of "competing implementation" this
project avoids elsewhere; both are still unambiguously 4xx client
errors, never a 500.

**Security** (see also `SECURITY.md`): binds to `127.0.0.1` only;
CORS allows exactly the frontend dev server's origins
(`http://127.0.0.1:5173`, `http://localhost:5173`) by default, never
`*`; no route, query parameter, or request body accepts a filesystem
path (verified by a test that inspects the generated OpenAPI schema for
any parameter name containing "path"/"dir"/"file"); no SQL is ever
written in `api/`; the one per-request `Case` is opened and closed by a
FastAPI dependency (`api/deps.py`) exactly mirroring the CLI's own
per-invocation lifecycle.

## 4. Frontend (`frontend/`)

Vite + React 19 + TypeScript, Cytoscape.js **without** the
`react-cytoscapejs` wrapper package (a deliberate, documented deviation
from architecture §13 — see §5). State/data-fetching: TanStack Query, as
specified.

```
frontend/src/
├── api/            # types.ts (mirrors the backend's JSON contracts), client.ts (fetch wrapper)
├── graph/           # elements.ts (Entity/Relationship -> Cytoscape elements, §15's "no second graph model"),
│                     # CytoscapeGraph.tsx (thin wrapper), stylesheet.ts, GraphPanel.tsx (mode/overlay orchestration)
├── components/       # CaseHeader, EntityList/Detail, RelationshipList/Detail, Provenance (§8),
│                     # EvidenceIndependencePanel (§7's critical UX), PathExplorer, ContradictionsPanel, ErrorScreen
├── App.tsx           # top-level layout/state (selection, overlay)
└── main.tsx          # QueryClientProvider
```

**Case opening/startup flow (Phase C item 1):** there is no in-UI case
picker — the architecture deliberately binds one server process to one
case directory at startup (§11), so there is nothing to pick. On load,
the UI calls `GET /case`; if that fails (server not running yet, or
unreachable), `ErrorScreen` renders with the exact command to start the
backend (`witnessgraph-api path/to/case-directory`) and the API base URL
it is trying to reach — never a generic "something went wrong."

**Graph view:** starts in "full case graph" mode (built directly from
the already-fetched entity/relationship lists — no extra request) for
cases at or below a small entity-count threshold; above it, "show the
whole graph" becomes an explicit, warned opt-in exactly as §16
specifies. Selecting a node switches to a bounded "ego network" mode
(`GET /graph/neighbors`, adjustable depth). Layout is deterministic —
`grid` (elements pre-sorted by id) for the full graph, `breadthfirst`
rooted at the selected entity for ego/path views — never a
force-directed layout, per §7's explicit caution.

**Path / tied-shortest-paths (Phase C items 7–8):** `PathExplorer` runs
`GET /graph/path` or `GET /graph/paths` and hands the returned chain(s)
to `GraphPanel` as an "analytical overlay," rendered with one distinct
color per chain (`graph/elements.ts::pathOverlayElements`) and a
`.wg-selected` styling reserved for whatever is open in the detail
panel — kept visually and semantically distinct from the overlay
classes, per §7's "clear distinction between the selected graph context
and analytical overlays." An edge shared by two chains gets both chain
classes, a visible signal rather than an arbitrarily-chosen single
color.

**Evidence independence (Phase C item 9, the critical one):**
`EvidenceIndependencePanel` renders exactly two separate, labeled
sentences — "Structural fact: N structurally distinct chain(s)..." and
"Evidence fact (a separate question): evidence-independent:
yes/no/not applicable..." — never merged, never using "proof",
"corroboration", or "confirms." A `null` `fully_evidence_independent`
(fewer than 2 chains) renders as "not applicable," never coerced to
`true`. Covered by a dedicated test asserting the phrase "independently
corroborated" never appears in the rendered output.

**Provenance UX (Phase C item 6, §8):** `components/Provenance.tsx`
implements the "expandable inline disclosure, not a separate page"
mechanism for both a relationship's already-resolved `evidence_lineage`
and an entity's own `derived_from` ids (resolved on demand via
`GET /evidence/{id}` — see §5). No separate Evidence-browse page exists
(deferred — see §6).

## 5. Deliberate deviations / extensions, and why

1. **No `react-cytoscapejs`.** Cytoscape.js core is used directly via a
   ~40-line React wrapper (`graph/CytoscapeGraph.tsx`, a `useRef`+
   `useEffect` pair). One fewer dependency, avoids that wrapper
   package's own React-18/19 compatibility surface, and keeps full,
   direct control over layout determinism. The architecture's actual
   requirement — Cytoscape.js for the interaction model — is met in
   full; only the specific wrapper package named in §13 is not used.
2. **Every graph endpoint always resolves explainability data** (no
   `?explain=` toggle in the API) — see §3. A generalization of a
   decision the architecture itself already made for two of the five
   graph-shaped endpoints, applied consistently to the rest, not a new
   design decision.
3. **`GET /evidence/{id}`** (`evidence_service.resolve_evidence`) is a
   small, deliberate slice of architecture §5 gap #3 ("Evidence item /
   NormalizedEvent, standalone") — not the full standalone Evidence
   *browse* view (deferred, §6), but the one lookup the Entity detail
   panel's own provenance disclosure requires to resolve an
   `Entity.derived_from` id, exactly the way a relationship's
   `evidence_lineage` already resolves `Relationship.derived_from`.
   Built via the engine's own existing `resolve_evidence_ref`, not new
   logic. Always returns 200 (`kind: "not_found"` is data, not a 404 —
   consistent with how the engine's own `--explain` machinery treats a
   dangling reference as a reportable fact, never an error).
4. **422 vs. 400 for FastAPI's own parameter validation** — see §3.

## 6. Genuinely deferred (not built this pass)

Per the mission's explicit DEFERRED list plus a few architecture SHOULD-
HAVEs judged not required for a first honest vertical slice:

- Hypotheses view, embedded Report view, UI-driven export/import,
  multi-case switching (all explicitly deferred by the mission).
- Standalone Evidence *browse* view (list/filter/search across all
  EvidenceItems) — architecture §5 gap #3's full form; only the
  single-id resolution needed for provenance disclosure was built (§5).
- Timeline view — blocked on architecture §5 gap #4 (no `TimeAssertion`
  list/show, no `timeline --format json`); not built because nothing in
  the MUST-HAVE slice required it, and inventing a timeline JSON
  contract "to make the UI easier" is explicitly against the mission's
  instructions.
- Gaps view / `POST /gaps` — `find_gaps` requires an explicit, no-default
  `min_gap_seconds` the architecture itself says has no objectively
  correct value; wiring it into the UI means designing a parameter-input
  UX for it, which is real, separate work, not a thin passthrough.
- Findings view + the ack/annotate workflow — the one write operation in
  the whole architecture (§10/§11); the read-only structural views
  already demonstrate the engine's identity without it.
- `POST /verify`, `/report` — architecture §5 gap #5 and an existing,
  already-complete CLI/document feature respectively; low priority per
  §17's own SHOULD-HAVE/DEFERRED split.
- CLI refactor of `graph_app`'s commands and `entities_show`/
  `relationships_show` — see §2's explicit reasoning.

## 7. Honest limitations

- The frontend's production bundle is ~715 KB (mostly Cytoscape.js),
  above Vite's default 500 KB warning threshold. Not addressed with
  code-splitting in this pass — a local, single-analyst desktop-style
  tool has no CDN transfer-budget pressure comparable to a public
  website, and adding `import()`-based splitting purely to silence a
  build warning would be complexity added for its own sake.
- The evidence-independence and provenance panels are exercised by
  targeted unit/component tests (backend and frontend) and by manual,
  real end-to-end verification (a live `witnessgraph-api` server against
  a synthetic diamond-shaped case, driven through an actual browser —
  see the milestone report's demo section), not by a browser-automation
  test suite committed to the repository. Vitest + Testing Library
  cover component-level state transitions; there is no Playwright/
  Cypress harness in this pass.
- This UI does not, and cannot, prove evidence independence in an
  epistemic sense — it renders exactly the structural and provenance
  facts the engine computes, nothing more. See the researcher-demo
  script's own closing line (architecture §19 step 9); this
  implementation does not weaken that boundary anywhere.
