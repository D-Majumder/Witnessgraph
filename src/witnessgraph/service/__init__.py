"""witnessgraph.service: the thin application/service boundary.

See ``docs/phase-ui-v1-architecture-design.md`` §4. Every function here
opens (or accepts an already-open) ``Case`` and calls exactly the
``correlate.*``/``store.*`` function the CLI already calls, returning the
same dataclass-derived JSON dict tree the CLI's own JSON output already
produces. This package contains no new forensic reasoning, no duplicated
graph algorithm, and no frontend-specific business logic -- its only job
is giving the CLI and the API server one shared place to call instead of
each re-deriving "how do I open a case and run this analysis"
independently.
"""

from __future__ import annotations
