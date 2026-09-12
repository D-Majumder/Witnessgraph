# Witnessgraph

An evidence-first, reproducible cybersecurity investigation platform.

> Cybersecurity investigations should be reproducible from evidence, not
> dependent on opaque conclusions.

Witnessgraph is a **local-first, defensive/research** tool: it ingests
evidence you already have, keeps it immutable and content-addressed,
represents hypotheses as explicitly evidence-backed claims (never bare
facts), and lets a case be exported, handed to someone else, and
independently reproduced — provenance hash and all.

This is v0.1: the foundation only. See `DESIGN.md` for the locked
architectural principles and `SECURITY.md` for what this tool does and
does not do.

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
witnessgraph ingest ./my-case jsonl ./events.jsonl
witnessgraph timeline ./my-case
witnessgraph hypothesis propose ./my-case "the statement" --evidence <id>
witnessgraph export ./my-case ./my-case.wgcase
witnessgraph import ./my-case.wgcase ./my-case-restored
witnessgraph replay ./my-case-restored
```

See `examples/sample-case/` for a full worked example.

## Status

v0.1 foundation: core data model, provenance/manifest hashing, SQLite +
content-addressed storage, three ingestion adapters (JSONL, CSV timeline,
syslog), structural time-contradiction detection, and a CLI. No AI
integration, no graph database, no web UI — see `DESIGN.md` for what is
deliberately out of scope for this version.

## Coverage gap analysis — known limitations

`witnessgraph gaps <case> --min-gap-seconds <N>` reports intervals where
one analyst-declared source (`--source-id` at ingest time) has no
observed evidence while a different, independently-declared source has
corroborating activity in that same interval. Two limitations apply that
users must understand before relying on its output:

- **`source_id` collisions.** Witnessgraph cannot independently verify
  physical source identity — it only compares the labels an analyst
  supplied. If two genuinely distinct systems are accidentally given the
  same `source_id`, their evidence is merged into one source group, and
  a real coverage gap in either one can be silently masked.
- **Clock skew.** Gap analysis operates entirely on recorded timestamps
  and does not estimate or correct for clock offsets between sources.
  Skew between an absent and a corroborating source can affect both
  cross-source corroboration and the attribution of a finding to a
  specific interval.

A finding is a structural statement about the absence of *recorded*
evidence relative to another source, never a claim about what did or
did not physically occur — findings must not be interpreted as proof
that an event did or did not happen.
