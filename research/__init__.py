"""Research infrastructure for Witnessgraph.

Deliberately outside ``src/witnessgraph`` (the installed, production
package): everything under ``research/`` is experimental evaluation
infrastructure -- benchmarks, fixtures, ground truth, and evaluation
harnesses used to study Witnessgraph's existing behavior. Nothing here
is imported by, or changes the behavior of, any production module.

See ``research/wg_bench`` and ``docs/research/wg-bench.md``.
"""

from __future__ import annotations
