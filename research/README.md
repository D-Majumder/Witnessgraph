# research/

Experimental research infrastructure, kept deliberately separate from
`src/witnessgraph` (the installed, production package) and from
`tests/` (Witnessgraph's own correctness test suite). Code here studies
Witnessgraph's *existing* behavior; it never changes it.

## wg_bench

WG-Bench is a deterministic benchmark evaluating whether
`witnessgraph.correlate.graph.analyze_paths_evidence_overlap`'s
root-evidence overlap analysis reduces false-corroboration
interpretations relative to path-count-only reasoning. See
[`docs/research/wg-bench.md`](../docs/research/wg-bench.md) for the full
research report (question, hypotheses, fixture taxonomy, methodology,
results, and limitations).

Reproduce it from the repository root:

```sh
python -m research.wg_bench
```

Its own infrastructure (fixtures, baseline, evaluation, and metrics
logic) is tested in `tests/unit/test_wg_bench.py`, run automatically by
the project's normal `pytest` invocation.
