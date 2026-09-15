"""WG-Bench V3: independent-adversarial validation of the V2 result.

V2 (``research.wg_bench.v2``) found that Witnessgraph's recursive
root-evidence resolution beats the strongest realistic non-recursive
baseline (Baseline 2: direct evidence-reference comparison) on exactly 4
fixtures, all requiring resolution through one ``NormalizedEvent``
indirection hop -- but all 4 were authored by the same person who wrote
the production code under test.

V3 exists to attack that result: independently-designed fixtures, built
from structurally different patterns than V1/V2 (not id permutations of
existing fixtures), deliberately including cases that are NOT expected
to favor Witnessgraph -- see ``docs/research/wg-bench.md``'s V3 section
for the full methodology, attack catalogue, and results.

V3 reuses V2's data model (``research.wg_bench.v2.model``), evaluation
harness (``research.wg_bench.v2.evaluation``), and all four methods
(Baseline 0/1/2, Witnessgraph) completely unmodified -- only the fixture
set and the aggregate metrics are new, since the comparison must use the
exact same scoring machinery V2 used for the result to be comparable at
all.
"""

from __future__ import annotations
