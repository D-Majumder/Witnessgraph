# Sample case

A fully synthetic worked example demonstrating the v0.1 pipeline:
ingest → normalized events → entities → timeline → hypothesis → export →
fresh import → identical manifest hash.

All data in `data/` is hand-authored and synthetic. No real logs,
credentials, IPs, or personal data of any kind. See `SECURITY.md`.

## Run it

```sh
pip install -e ".[dev]"   # from the repo root, once
python examples/sample-case/run_example.py
```

This drives the real `witnessgraph` CLI end-to-end and prints the
provenance manifest hash of the original case and of a case imported
fresh from an exported `.wgcase` archive. The two must match — that is
the whole point (DESIGN.md principle 4).

## What it demonstrates

1. `witnessgraph init` — create an empty case.
2. `witnessgraph ingest` (×3) — JSONL, CSV timeline, and syslog adapters,
   each producing EvidenceItem/NormalizedEvent pairs and, where a
   `timestamp` was present and unambiguous, a TimeAssertion.
3. `witnessgraph entities create` — an entity is linked explicitly to the
   evidence it was derived from (v0.1 does not auto-resolve entities).
4. `witnessgraph timeline` — events ordered by their earliest known time.
5. `witnessgraph contradictions` — structural TimeAssertion conflict check.
6. `witnessgraph hypothesis propose` / `support` — an evidence-backed claim.
7. `witnessgraph export` / `import` — round-trip through a portable
   `.wgcase` archive.
8. `witnessgraph replay` — independently recompute the provenance
   manifest of both the original and the freshly imported case, and
   confirm the hashes match.
