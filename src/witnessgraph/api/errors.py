"""Translate service-layer errors into HTTP responses.

Mirrors the CLI's own clean-failure convention (``_open_case_or_fail``,
"no such entity"/"no such relationship", ``typer.BadParameter``) instead
of letting an exception escape as a raw 500 traceback -- see
``docs/phase-ui-v1-architecture-design.md`` §14's error-handling
paragraph. A 404 names an unknown id with the same message text the CLI
prints; a 400 names an invalid parameter the same way.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from witnessgraph.service.errors import (
    CaseNotFoundError,
    CaseUnreadableError,
    EntityNotFoundError,
    RelationshipNotFoundError,
    TrackedContradictionNotFoundError,
    TrackedFindingNotFoundError,
    ValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EntityNotFoundError)
    async def _entity_not_found(request: Request, exc: EntityNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"no such entity: {exc}"})

    @app.exception_handler(RelationshipNotFoundError)
    async def _relationship_not_found(
        request: Request, exc: RelationshipNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"no such relationship: {exc}"})

    @app.exception_handler(TrackedFindingNotFoundError)
    async def _finding_not_found(
        request: Request, exc: TrackedFindingNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": f"no such tracked finding: {exc}"}
        )

    @app.exception_handler(TrackedContradictionNotFoundError)
    async def _contradiction_finding_not_found(
        request: Request, exc: TrackedContradictionNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=404, content={"detail": f"no such tracked contradiction: {exc}"}
        )

    @app.exception_handler(ValidationError)
    async def _validation_error(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(CaseNotFoundError)
    async def _case_not_found(request: Request, exc: CaseNotFoundError) -> JSONResponse:
        # Only reachable if the bound case directory is removed/moved after
        # server startup (create_app already probes it once) -- a server
        # integrity problem, not a malformed client request.
        return JSONResponse(
            status_code=500,
            content={"detail": f"the bound case directory is no longer a valid case: {exc}"},
        )

    @app.exception_handler(CaseUnreadableError)
    async def _case_unreadable(request: Request, exc: CaseUnreadableError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"detail": f"the bound case's database could not be read: {exc}"},
        )
