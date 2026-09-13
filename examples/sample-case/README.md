# Sample case

A fully synthetic worked example demonstrating the full pipeline:
ingest → normalized events → entities → relationships → graph traversal
→ timeline → hypothesis → export → fresh import → identical manifest
hash.

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
3. `witnessgraph entities create` (×3) — a host, an ip, and a user
   entity, each linked explicitly to the evidence they were derived from
   (Witnessgraph does not auto-resolve entities).
4. `witnessgraph relationships create` (×2) — directed, evidence-backed
   edges: the user `authenticated_as` the host, and the host
   `connected_to` the ip (v1.1).
5. `witnessgraph graph neighbors` / `graph path` / `graph components` —
   the host's direct neighbors, the deterministic two-hop chain from the
   user entity through the host to the ip (with full relationship/
   evidence provenance for each step), and confirmation that all three
   entities fall into one connected cluster. `graph path ... --explain`
   then resolves that same chain's relationship evidence and entities to
   their full stored records (source adapter/locator, entity type/
   identifiers), so the chain is readable without a second, manual
   lookup.
6. `witnessgraph timeline` — events ordered by their earliest known time.
7. `witnessgraph contradictions` — structural TimeAssertion conflict check.
8. `witnessgraph hypothesis propose` / `support` — an evidence-backed claim.
9. `witnessgraph export` / `import` — round-trip through a portable
   `.wgcase` archive.
10. `witnessgraph replay` — independently recompute the provenance
    manifest of both the original and the freshly imported case, and
    confirm the hashes match.
