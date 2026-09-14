"""Per-request Case binding.

Every request opens its own ``Case`` against the one directory this
server instance was started for (``app.state.case_dir`` -- set once, at
startup, by ``witnessgraph.api.app.create_app``, and never accepted from
a request) and closes it when the request finishes -- mirroring the
CLI's own per-invocation open/close lifecycle exactly (see
``docs/phase-ui-v1-architecture-design.md`` §3/§13). No request, query
parameter, or body anywhere in this API ever supplies a filesystem path;
this is the whole of this server's path-traversal defense.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from witnessgraph.service.case_service import open_case
from witnessgraph.store.case import Case


def get_case(request: Request) -> Iterator[Case]:
    case_dir = request.app.state.case_dir
    case = open_case(case_dir)
    try:
        yield case
    finally:
        case.close()
