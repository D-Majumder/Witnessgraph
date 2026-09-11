# Witnessgraph Investigation Report

Case: `sample-case`

Recorded manifest hash: `3a66689a99bba96eeda1facca8b0336e149246e44c72ea81fadcf3ff1b344acf`

This report's own content is not covered by the manifest hash above -- see the Integrity Summary section for the exact coverage boundary.

## Evidence Inventory

- Evidence `23da92a458f02aa20db9198ff4df4f31f15547b40b58a3e6b9fa55aa312c7ef2`
  - source_adapter: `jsonl`
  - adapter_version: `0.1.0`
  - source_locator: `examples/sample-case/data/events.jsonl`
  - raw_size_bytes: 561
  - collected_at: 2026-01-01T00:00:00Z
  - observed_at: (not set)
  - chain_of_custody:
    - actor: `adapter:jsonl@0.1.0`, action: `ingested`, timestamp: 2026-01-01T00:00:00Z, source_locator: `examples/sample-case/data/events.jsonl`
- Evidence `704c1143475a2165aac8af1d0a7330e79e0d0ca99fb4fef3cbb2db47e0fa37e2`
  - source_adapter: `syslog`
  - adapter_version: `0.1.0`
  - source_locator: `examples/sample-case/data/auth.syslog`
  - raw_size_bytes: 164
  - collected_at: 2026-01-01T00:00:00Z
  - observed_at: (not set)
  - chain_of_custody:
    - actor: `adapter:syslog@0.1.0`, action: `ingested`, timestamp: 2026-01-01T00:00:00Z, source_locator: `examples/sample-case/data/auth.syslog`
- Evidence `b2651b60d40d64679b4ee7506795fbc6f7baf76aa1882a63bbbf43d281623ead`
  - source_adapter: `csv_timeline`
  - adapter_version: `0.1.0`
  - source_locator: `examples/sample-case/data/timeline.csv`
  - raw_size_bytes: 296
  - collected_at: 2026-01-01T00:00:00Z
  - observed_at: (not set)
  - chain_of_custody:
    - actor: `adapter:csv_timeline@0.1.0`, action: `ingested`, timestamp: 2026-01-01T00:00:00Z, source_locator: `examples/sample-case/data/timeline.csv`

## Timeline

- Event `a0000000-0000-0000-0000-000000000001` (`process_start`)
  - entity_ids: (none)
  - derived_from: `23da92a458f02aa20db9198ff4df4f31f15547b40b58a3e6b9fa55aa312c7ef2`
  - attributes:
    - `host`: `corp-ws-042`
    - `process`: `powershell.exe`
  - time_assertions:
    - `b0000000-0000-0000-0000-000000000001`: value=2026-01-01T08:30:00Z, precision=second, asserted_by=`adapter:jsonl`, source_evidence_id=`23da92a458f02aa20db9198ff4df4f31f15547b40b58a3e6b9fa55aa312c7ef2`

## Entities

- Entity `c0000000-0000-0000-0000-000000000001` (`host`)
  - first_seen: (not set)
  - last_seen: (not set)
  - derived_from: `23da92a458f02aa20db9198ff4df4f31f15547b40b58a3e6b9fa55aa312c7ef2`
  - identifiers:
    - `hostname`: `corp-ws-042`

## Hypotheses

- Hypothesis `d0000000-0000-0000-0000-000000000001`
  - statement: `corp-ws-042 ran obfuscated PowerShell after opening a macro document`
  - status: supported
  - inferred_by: `analyst:golden-report-test`
  - created_at: 2026-01-01T00:00:00Z
  - Supporting evidence:
    - kind=evidence_item, id=`23da92a458f02aa20db9198ff4df4f31f15547b40b58a3e6b9fa55aa312c7ef2`
    - kind=evidence_item, id=`704c1143475a2165aac8af1d0a7330e79e0d0ca99fb4fef3cbb2db47e0fa37e2`
  - Contradicting evidence: (none)

## Contradictions

(none)

## Integrity Summary

Recomputed manifest hash: `3a66689a99bba96eeda1facca8b0336e149246e44c72ea81fadcf3ff1b344acf`
Recorded manifest hash: `3a66689a99bba96eeda1facca8b0336e149246e44c72ea81fadcf3ff1b344acf`
Verdict: MATCH

This verdict covers only: EvidenceItem.raw_content_hash for every evidence item, and the full canonical content of every NormalizedEvent, Entity, TimeAssertion, and Hypothesis. It does NOT cover the following fields displayed elsewhere in this report, which are excluded from the manifest hash by design: EvidenceItem.chain_of_custody, EvidenceItem.collected_at, EvidenceItem.source_locator, EvidenceItem.source_adapter, EvidenceItem.adapter_version, EvidenceItem.ingest_parameters, and EvidenceItem.observed_at. A MATCH verdict does not, by itself, prove those specific fields are untampered.
