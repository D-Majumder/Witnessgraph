"""Validate a case package without ever touching a filesystem Case.

``validate_package_bytes`` parses raw ``case.json`` bytes and reports
every schema/reference error found; it never writes anything, never
creates a ``Case``, and never "repairs" a malformed package -- every
finding is a rejection with an explicit reason. See ``build.py`` for the
resolution logic this reuses so validation and import can never
disagree about what a package would produce.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from witnessgraph.casepkg.build import BuildError, build_case_contents
from witnessgraph.casepkg.schema import CasePackage


@dataclass(frozen=True)
class ValidationReport:
    is_valid: bool
    schema_errors: tuple[str, ...]
    build_errors: tuple[BuildError, ...]
    package: CasePackage | None

    def all_messages(self) -> tuple[str, ...]:
        return (*self.schema_errors, *(str(e) for e in self.build_errors))


def validate_package_bytes(raw: bytes) -> ValidationReport:
    """Parse and validate ``case.json`` bytes. Never raises -- every
    failure is reported in the returned ``ValidationReport``."""
    try:
        package = CasePackage.model_validate_json(raw)
    except ValidationError as exc:
        return ValidationReport(
            is_valid=False,
            schema_errors=tuple(_format_pydantic_error(exc)),
            build_errors=(),
            package=None,
        )
    result = build_case_contents(package)
    return ValidationReport(
        is_valid=result.is_valid,
        schema_errors=(),
        build_errors=result.errors,
        package=package,
    )


def _format_pydantic_error(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        messages.append(f"{location}: {error['msg']}")
    return messages
