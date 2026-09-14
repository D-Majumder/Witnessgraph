"""witnessgraph.api: a local-only FastAPI backend bound to one case directory.

See ``docs/phase-ui-v1-architecture-design.md`` §11/§14. This package
never talks to ``correlate``/``store`` directly -- every route calls
``witnessgraph.service`` and returns exactly the dict tree the service
layer produces, encoded with ``core.ids.canonical_json_bytes`` (see
``witnessgraph.api.responses``). Binds to ``127.0.0.1`` only; see
``witnessgraph.api.__main__``.
"""

from __future__ import annotations
