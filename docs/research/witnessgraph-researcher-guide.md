# Witnessgraph Researcher Guide

For a university researcher, professor, research supervisor, or
independent evaluator who wants to run Witnessgraph on their own
machine, bring their own structured case data, and inspect it through
the graph/provenance tooling and UI — without needing to already know
this codebase.

See `docs/research/witnessgraph-quickstart.md` for the fastest path from
nothing to an opened case, and `docs/research/witnessgraph-case-format.md`
for the full schema reference this guide's import/export sections rely
on.

## 1. What Witnessgraph is

An evidence-first, reproducible investigation platform: it keeps raw
evidence immutable and content-addressed, requires every derived object
(entity, relationship, normalized event) to carry explicit lineage back
to the evidence it came from, keeps analyst/researcher hypotheses
structurally distinct from observed evidence, and can export a case as
a single archive that anyone can reimport and independently verify
against the exact same provenance hash. See `DESIGN.md` for the seven
locked design principles this guide assumes throughout.

## 2. What problem it addresses

Investigations built on graph/relationship data are prone to a specific,
easy-to-make error: mistaking **structural path multiplicity** (many
distinct-looking chains connecting two things) for **provenance
multiplicity** (many genuinely independent underlying pieces of
evidence). Two chains that look structurally different can still
recursively resolve to the *same* root evidence once you follow their
derivation lineage all the way down — and a reader who only sees "two
paths" may read that as two independent confirmations. Witnessgraph's
core mechanism (`find_all_shortest_paths` +
`analyze_paths_evidence_overlap`, `docs/research/wg-bench.md`) exists to
make that distinction inspectable and explicit rather than left to
intuition. WG-Study (§18 below) is this project's mechanism for testing,
with real human participants, whether making that distinction visible
actually helps a reader avoid the error — that is a live, unresolved
research question, not a settled result.

## 3. What it does NOT establish

Read this before relying on anything Witnessgraph reports:

- **Not proof of causality, authenticity, or truth.** A `Relationship`
  or `Hypothesis` is a claim grounded in cited evidence, never an
  adjudicated fact.
- **Not proof of epistemic independence.** Disjoint root evidence (two
  chains resolving to different `EvidenceItem`/`NormalizedEvent` ids) is
  a property of the *declared case model* — what the case's evidence and
  derivation lineage say — not a real-world guarantee that two
  observations are independent, authentic, or truthful. See
  `docs/research/wg-study-reporting.md` §21 for the exact, careful
  wording this project holds itself to on this point.
  - Whether the imported ids happen to come from real forensic
    acquisition, a researcher's own hand-authored case package, or
    anywhere in between, disjoint provenance means "the declared model
    does not show these as sharing a source" — it is never upgraded to
    a stronger claim by anything in this codebase.
- **Not an autonomous forensic examiner, truth oracle, malware scanner,
  or replacement for forensic acquisition tools.** Witnessgraph
  organizes and reasons about evidence you already possess; it does not
  acquire, authenticate, or scan anything.
- **Not statistically validated on human reasoning yet.** WG-Study
  (§18) is designed to test whether Witnessgraph's provenance
  presentation helps human analysts specifically — as of this writing,
  no human participant data exists anywhere in this repository, and no
  claim of a validated human benefit is made.

## 4. Installation

```sh
git clone <this repository>
cd witnessgraph
python -m venv .venv
.venv/Scripts/activate   # or: source .venv/bin/activate
pip install -e ".[dev]"
```

**System requirements**: Python 3.11+ (see README.md's "Python version"
section — 3.12+ also works). No GPU, no external database, no internet
connection required for any step in this guide. For the optional web UI
(§9), also Node.js (see `frontend/package.json`'s engine requirement) to
build/run the frontend once.

## 5. Creating a demo case

```sh
witnessgraph case-package init demo.json
witnessgraph case-package validate demo.json
witnessgraph case-package import demo.json ./demo-case
```

This writes a minimal, clearly-labeled `DEMO / TEMPLATE DATA` case
package — two entities, one relationship, one evidence item, all
obviously synthetic — validates it, then imports it into a real case
directory. Open `demo.json` in a text editor to see the exact shape a
case package takes before writing your own; see
`docs/research/witnessgraph-case-format.md` for every field.

## 6. Importing a researcher case

Two ways to bring your own data in, depending on what you already have:

**(a) You already have structured case data (entities, relationships,
evidence, hypotheses) you can express directly**: write a case package
(`docs/research/witnessgraph-case-format.md`) — either by hand, or by
generating one from your own tooling — and import it:

```sh
witnessgraph case-package validate my-case.json
witnessgraph case-package import my-case.json ./my-case
```

**(b) You have raw evidence source files** (JSONL event logs, CSV
timelines, syslog) and want Witnessgraph's existing ingestion adapters
to parse them into evidence/normalized events first, then build
entities/relationships on top with individual CLI commands:

```sh
witnessgraph init ./my-case
witnessgraph ingest ./my-case jsonl ./events.jsonl --source-id host-a
witnessgraph entities create ./my-case host --derived-from <evidence-id> --id hostname=host-a
witnessgraph relationships create ./my-case connected_to --source <id> --target <id> --derived-from <evidence-id>
```

Both paths converge on the same `Case` directory shape and are usable
interchangeably from that point on (graph analysis, UI, export,
verify). A case package is generally faster for data you can already
express structurally; the ingestion adapters are for raw log-shaped
source files. Nothing in this codebase infers provenance you did not
explicitly declare either way — see
`docs/research/witnessgraph-case-format.md`'s "declared fact vs.
system-derived analysis vs. researcher hypothesis" section.

## 7. Validating a case

```sh
witnessgraph case-package validate my-case.json
```

Prints `VALID` with a short summary, or `INVALID` with every specific
error found (missing field, dangling reference, malformed timestamp,
duplicate id, ...) — never silently repairs or partially imports a
malformed package. Run this before `import` any time you hand-edit a
case package.

## 8. Opening it in the UI

```sh
witnessgraph-api ./my-case
```

in one terminal (binds to `127.0.0.1` only, serves exactly this one
case directory — see §10), then, from `frontend/` in another terminal
(once per checkout: `npm install`):

```sh
npm run dev
```

Open the printed local URL. **No changes were needed anywhere in the
API or frontend to support an imported case** — a case package-imported
case is an ordinary `Case` directory, exactly like one built via
`witnessgraph init`/`ingest`/`entities create`, so every existing view
(Graph, Evidence, Timeline, Contradictions, Gaps, Findings — see
README.md's "Web UI (v1)" section) already works against it.

## 9. Graph analysis

```sh
witnessgraph graph neighbors ./my-case <entity-id>
witnessgraph graph path ./my-case <source-entity-id> <target-entity-id> --explain
witnessgraph graph paths ./my-case <source-entity-id> <target-entity-id>
witnessgraph graph components ./my-case
```

`graph path`/`graph paths --explain` is where
`find_all_shortest_paths`/`analyze_paths_evidence_overlap` (§2) surface
directly — every step's cited evidence is printed alongside the
structural chain, never separated from it.

## 10. Provenance analysis

```sh
witnessgraph verify ./my-case
witnessgraph replay ./my-case
```

`verify` recomputes the case's provenance manifest and compares it
against the recorded one (MATCH/MISMATCH/NOT_COMPARABLE/
NO_RECORDED_MANIFEST). `replay` does the same and additionally confirms
the whole evidence→entity→relationship lineage resolves without a
dangling reference.

## 11. Evidence overlap

`graph paths --explain` (§9) includes each returned chain's resolved
root-evidence set and the overlap classification between chains — the
same computation WG-Bench (`docs/research/wg-bench.md`) validates
against independently-authored ground truth. See §3 for what this
computation does *not* establish.

## 12. Contradictions, gaps, findings

```sh
witnessgraph contradictions ./my-case
witnessgraph gaps ./my-case --min-gap-seconds 300
witnessgraph findings list ./my-case
witnessgraph contradiction-findings list ./my-case
```

These are **system-derived analysis** — computed from your declared
case, never declarable as input in a case package (see
`docs/research/witnessgraph-case-format.md`). `findings`/
`contradiction-findings ack` records a reviewer's acknowledgement of a
tracked finding; it never changes the underlying evidence.

## 13. Exporting a case

```sh
witnessgraph case-package export ./my-case exported.json --title "My case" --package-version 1.0.0
# or, for the integrity-verifiable archive form:
witnessgraph case-package export ./my-case exported.witnessgraph-case
```

Produces a declarative case package another researcher can read, diff,
and reimport (§15). For an exact binary copy instead (byte-for-byte
database + blob store), use `witnessgraph export ./my-case out.wgcase`.

## 14. Reproducibility

See §15 for the exact steps a third party needs. In short: share the
case package (or `.wgcase` archive) plus the Witnessgraph version you
used (`pip show witnessgraph`, or the git commit if running from
source); another researcher with the same version imports it and gets
the same provenance manifest hash (`witnessgraph verify`), which they
can compare against yours to confirm they have the exact same logical
case.

## 15. Privacy

- **Local-only.** No network call anywhere in `core`/`store`/`ingest`/
  `correlate`/`replay`/`casepkg`. The optional web UI's backend
  (`witnessgraph-api`) binds to `127.0.0.1` only, never `0.0.0.0` or a
  public interface, and is started manually by you.
- **No telemetry, no analytics, no automatic upload.** Nothing in this
  codebase reports usage or sends data anywhere on its own.
- **No mandatory authentication.** Every command and the local API
  require no login or credential.
- **You control what leaves your machine.** Exporting a case (`.wgcase`
  or a case package) writes a local file; nothing transmits it anywhere.
  If you share that file (email, USB drive, another tool), that step —
  and whatever data-governance/ethics/legal obligations apply to the
  evidence it contains — is entirely your responsibility. **Witnessgraph
  makes no claim of legal compliance** for any jurisdiction or
  regulatory regime; consult your own institution's data-governance
  policy before importing or sharing real evidence.
- See `SECURITY.md` for the full security boundary, including how
  imported archives (untrusted input) are hardened against path
  traversal and decompression bombs.

## 16. Limitations

- No automatic entity resolution/merging — you decide when two
  observations refer to the same real-world entity (DESIGN.md,
  `core/entities.py`'s module docstring).
- No inferential statistics or claim of statistical significance
  anywhere in this codebase's research tooling (WG-Bench, WG-Study) —
  see `docs/research/wg-study-reporting.md` for why.
- A case package caps a single evidence item's inline content at 50 MB
  and a package's total declared object count at 200,000
  (`docs/research/witnessgraph-case-format.md`) — a policy default, not
  a claim that larger cases are unsupported via the individual
  ingestion/CLI commands.
- The current UI is read-mostly (findings acknowledgement is the one
  write path) — see README.md's "Web UI (v1)" section for exactly what
  exists.

## 17. WG-Study

WG-Study (`docs/research/wg-study.md`) is a separate, controlled human
research protocol for testing whether Witnessgraph's provenance
presentation helps a human reader avoid false-corroboration
interpretations — structurally and architecturally independent of the
researcher case-import tooling this guide covers. See §18.

## 18. How to construct study cases

**A researcher case (this guide) and a WG-Study controlled case are not
the same thing, and the case-package importer never turns one into the
other.** WG-Study's fixed 9-case manifest
(`research.wg_study.case_builder.CASE_SELECTION`) is frozen, drawn only
from already-validated WG-Bench fixtures, and pairs each case with an
independently-authored answer key that a participant never sees
(`docs/research/wg-study.md` §5–§6). Feeding an arbitrary imported
researcher case into WG-Study directly would compromise that
experimental control — there is no code path that does this, and none
should be added.

If you want to author a *new* WG-Study-style case from your own
underlying data for a future study extension, the documented,
non-automatic pathway is:

1. Build your case data as you normally would (§6), or construct it
   directly in Python using `witnessgraph.core`'s domain types.
2. Write your own `StudyCase`/`ChainView` construction (mirroring
   `research/wg_study/case_builder.py`'s pattern), explicitly declaring
   the neutral, relabeled presentation a participant would see — never
   reusing your case's real entity/relationship labels directly (see
   `docs/research/wg-study.md` §5 on neutral labeling).
3. Separately and explicitly author the answer key (mirroring
   `research/wg_study/answer_key.py`'s pattern) from your own reasoning
   about the case's *intended* topology — **never** by calling
   `analyze_paths_evidence_overlap()` and copying its verdict
   (`docs/research/wg-study.md` §6 explains why: that would make the
   ground truth derived from the very engine being tested, collapsing
   the experiment).
4. Keep this new case and its answer key entirely separate from
   `research/wg_study/case_builder.py`'s existing fixed manifest — add
   it as a distinct, clearly-labeled module/case set, never merged into
   the controlled 9-case study without a documented, deliberate decision
   to do so (which would itself require updating the frozen study
   manifest — `docs/research/wg-study.md` §12 — and treating it as a new
   study version).

This is intentionally a manual, code-level pathway, not an automated
"import any case into WG-Study" feature — automating it is exactly what
would compromise experimental control, per the mission constraint this
guide operates under.

## 19. How to share a reproducible case package

See §15 (this guide's reproducibility section) for what to share. In
one place:

```sh
# You:
witnessgraph case-package export ./my-case my-case.witnessgraph-case
# share my-case.witnessgraph-case (or my-case.json) + your Witnessgraph version

# The other researcher:
witnessgraph case-package validate my-case.witnessgraph-case
witnessgraph case-package import my-case.witnessgraph-case ./their-copy
witnessgraph verify ./their-copy
# compare the printed manifest hash against yours
```

A `.witnessgraph-case` archive additionally lets them confirm the
archive itself was not corrupted or tampered with in transit
(`case-package validate`/`import` verify the archive's recorded content
hash before trusting anything inside it — see
`docs/research/witnessgraph-case-format.md`).
