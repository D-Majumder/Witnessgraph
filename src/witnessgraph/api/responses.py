"""Shared JSON response encoding for every route.

Per ``docs/phase-ui-v1-architecture-design.md`` §5's canonicalization
note: the service layer's dict trees are encoded with
``core.ids.canonical_json_bytes`` and returned as a raw ``Response``
body, rather than letting FastAPI/Starlette's own ``JSONResponse`` do a
second, different JSON encoding -- this is the "simplest, zero new
formatting code" option that document identifies, and it guarantees the
API's datetime formatting (UTC, ``Z``-suffixed) is byte-identical to the
CLI's own ``--format json`` output for the same underlying dict tree.
"""

from __future__ import annotations

from typing import Any

from fastapi import Response

from witnessgraph.core.ids import canonical_json_bytes


def json_response(doc: Any, *, status_code: int = 200) -> Response:
    return Response(
        content=canonical_json_bytes(doc),
        media_type="application/json",
        status_code=status_code,
    )
