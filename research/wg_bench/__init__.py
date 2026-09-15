"""WG-Bench: a deterministic benchmark evaluating whether Witnessgraph's
root-evidence overlap analysis (``correlate.graph.analyze_paths_evidence_overlap``)
reduces false-corroboration interpretations relative to path-count-only
reasoning over graph path multiplicity.

See ``docs/research/wg-bench.md`` for the full research report. This
package makes no changes to Witnessgraph's production reasoning code
(``src/witnessgraph``) -- it only calls existing, unmodified public
functions and records what they return.

Terminology: this package reports "root-evidence independence at the
provenance level" or "root-evidence disjointness" -- never "epistemic
independence," "evidentiary truth," "corroboration proof,"
"authenticity," "causality," or "attribution." Root-evidence
disjointness is a provenance property (do two chains' relationships
ultimately trace to different content-addressed ``EvidenceItem`` ids) --
it is not, and cannot be, a guarantee that the underlying real-world
observations are independent. See the BYTE_DISTINCT_SAME_SOURCE fixture
and ``docs/research/wg-bench.md``'s "adversarial byte-distinct
limitation" section for exactly why.
"""

from __future__ import annotations
