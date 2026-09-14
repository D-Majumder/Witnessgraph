"""Service-layer error types.

Deliberately a small, closed set mirroring the clean, non-traceback
failures ``cli/main.py`` already produces for the same conditions (see
``_open_case_or_fail``, `"no such entity"`/`"no such relationship"`,
`typer.BadParameter`) -- callers (the CLI, the API server) translate
these into their own surface's idiom (an exit code + stderr line, or an
HTTP status + JSON body) without the service layer knowing anything
about either surface.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for every error this package raises deliberately."""


class CaseNotFoundError(ServiceError):
    """``case_dir`` does not look like a Witnessgraph case (no case.db)."""


class CaseUnreadableError(ServiceError):
    """``case_dir`` has a case.db that exists but cannot be read."""


class EntityNotFoundError(ServiceError):
    """No entity with the given id exists in this case."""


class RelationshipNotFoundError(ServiceError):
    """No relationship with the given id exists in this case."""


class TrackedFindingNotFoundError(ServiceError):
    """No tracked gap finding with the given id exists in this case."""


class TrackedContradictionNotFoundError(ServiceError):
    """No tracked contradiction with the given id exists in this case."""


class ValidationError(ServiceError):
    """An application-level input failed validation (e.g. max_depth/limit
    out of range) -- mirrors what ``typer.BadParameter`` already reports
    for the same condition on the CLI side."""
