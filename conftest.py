"""Repository-root pytest configuration.

The only thing this file does is make the repository root importable as
a plain directory on ``sys.path``, so that ``research/`` -- WG-Bench's
research benchmark infrastructure (see docs/research/wg-bench.md), which
deliberately lives outside the installed ``witnessgraph`` package under
``src/`` -- can be imported by its own tests regardless of how pytest is
invoked (``pytest``, ``python -m pytest``, or from a different working
directory). This file contains no test collection logic and defines no
fixtures.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
