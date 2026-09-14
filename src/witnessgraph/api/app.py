"""Build the FastAPI application, bound to exactly one case directory.

See ``docs/phase-ui-v1-architecture-design.md`` §11: the case directory
is chosen once, when the server process is started (``create_app``'s
``case_dir`` argument, itself only ever supplied from this process's own
command line -- see ``witnessgraph.api.__main__``), never from an
incoming request. No route, query parameter, or request body anywhere in
this package accepts a filesystem path.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from witnessgraph.api.errors import register_exception_handlers
from witnessgraph.api.routes import case as case_routes
from witnessgraph.api.routes import contradictions as contradictions_routes
from witnessgraph.api.routes import entities as entities_routes
from witnessgraph.api.routes import evidence as evidence_routes
from witnessgraph.api.routes import graph as graph_routes
from witnessgraph.api.routes import relationships as relationships_routes
from witnessgraph.service.case_service import open_case

#: The frontend's dev-server origins (Vite's default port). Never "*" --
#: see §11's CORS requirement. A packaged desktop build would add its own
#: exact origin here rather than widening this default.
DEFAULT_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
]


def create_app(case_dir: Path, *, allowed_origins: list[str] | None = None) -> FastAPI:
    """Build the app, bound to ``case_dir`` for its entire process lifetime.

    Fails fast: opens and immediately closes ``case_dir`` once, at build
    time, so a bad case directory is reported before the server ever
    starts listening -- mirroring ``cli.main._open_case_or_fail``'s own
    clean-failure convention, never a first-request surprise.
    """
    resolved_case_dir = case_dir.resolve()
    probe = open_case(resolved_case_dir)
    probe.close()

    app = FastAPI(
        title="Witnessgraph API",
        description=(
            "Local-only, read-mostly API over one bound Witnessgraph case "
            "directory. A thin wrapper over witnessgraph.service -- the "
            "existing engine (core/correlate/store) remains the single "
            "source of truth for every fact this API returns."
        ),
        version="1.0.0",
    )
    app.state.case_dir = resolved_case_dir
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins if allowed_origins is not None else DEFAULT_ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    register_exception_handlers(app)
    app.include_router(case_routes.router)
    app.include_router(entities_routes.router)
    app.include_router(relationships_routes.router)
    app.include_router(evidence_routes.router)
    app.include_router(graph_routes.router)
    app.include_router(contradictions_routes.router)
    return app
