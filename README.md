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
analyst-declared time assertions, JSON reporting — is additive. See
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
449 tests. There is no AI integration, no graph database, and no web
UI — this is deliberately a local CLI over a SQLite + content-addressed
store; see `DESIGN.md` for what stays out of scope by design.

### CLI reference

| Command | Purpose |
| --- | --- |
| `init` | Create a new, empty case directory. |
| `ingest <case> <adapter> <source> [--source-id]` | Ingest one evidence source (`jsonl`, `csv_timeline`, or `syslog`) into a case, optionally under an analyst-declared source identity. |
| `timeline` | Print all normalized events, ordered by earliest known time. |
| `entities create / list / show` | Create and inspect entities explicitly linked to the evidence that established them. |
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
├── core/        # Frozen data model: evidence, events, entities, hypotheses, provenance
├── store/       # SQLite metadata store + content-addressed blob store
├── ingest/      # Source adapters (jsonl, csv_timeline, syslog) and the ingest pipeline
├── correlate/   # Contradiction detection and coverage-gap analysis
├── replay/      # Provenance manifest recomputation/verification
├── report/      # Deterministic Markdown/JSON report rendering
├── cli/         # Typer CLI wiring the above into `witnessgraph`
└── portable.py  # .wgcase export/import
```

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

449 tests (unit + integration) exercise the full pipeline, including
property-based tests (`hypothesis`) for serialization and provenance
determinism. `ruff` and `mypy --strict` are both clean on `src/`.

## Security

See `SECURITY.md` for the full boundary: no network calls, no network
listener, no telemetry, and — critically — **no redaction**. Evidence is
stored and exported verbatim; do not ingest evidence you are not
comfortable storing as-is.

## License

MIT — see `LICENSE`.
