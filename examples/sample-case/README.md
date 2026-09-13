# Sample case

A fully synthetic worked example demonstrating the full pipeline:
ingest → normalized events → entities → relationships → timeline →
hypothesis → export → fresh import → identical manifest hash.

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
3. `witnessgraph entities create` (×2) — a host and an ip entity, each
   linked explicitly to the evidence they were derived from (Witnessgraph
   does not auto-resolve entities).
4. `witnessgraph relationships create` — a directed, evidence-backed
   edge (`connected_to`) between the two entities (v1.1).
5. `witnessgraph timeline` — events ordered by their earliest known time.
6. `witnessgraph contradictions` — structural TimeAssertion conflict check.
7. `witnessgraph hypothesis propose` / `support` — an evidence-backed claim.
8. `witnessgraph export` / `import` — round-trip through a portable
   `.wgcase` archive.
9. `witnessgraph replay` — independently recompute the provenance
   manifest of both the original and the freshly imported case, and
   confirm the hashes match.
