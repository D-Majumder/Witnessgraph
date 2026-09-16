"""Import a validated case package into a brand-new ``Case``.

Mirrors ``witnessgraph.ingest.pipeline.ingest_source``'s crash/ordering
model exactly: every blob write happens before its corresponding
``put_evidence`` call, and every metadata write is grouped into one
``case.transaction()`` so a single ``case-package import`` invocation
either fully succeeds or leaves no partial case behind.
"""

from __future__ import annotations

from pathlib import Path

from witnessgraph.casepkg.build import BuildError, build_case_contents
from witnessgraph.casepkg.schema import CasePackage
from witnessgraph.store.case import Case


class CasePackageError(ValueError):
    """A case package failed validation and was not imported."""

    def __init__(self, errors: tuple[BuildError, ...] | tuple[str, ...]):
        self.errors = errors
        super().__init__("; ".join(str(e) for e in errors))


def import_case_package(package: CasePackage, dest_root: Path) -> Case:
    """Validate, then persist, ``package`` into a fresh ``Case`` at ``dest_root``.

    Raises ``CasePackageError`` (never creates or partially populates
    ``dest_root``) if the package does not resolve cleanly -- validation
    and import always run the exact same resolution logic
    (``build.build_case_contents``), so an import can never "succeed"
    with a package ``case-package validate`` would have rejected, or
    vice versa. Raises ``FileExistsError`` if ``dest_root`` already
    exists and is non-empty (mirrors ``Case.create``).
    """
    result = build_case_contents(package)
    if not result.is_valid or result.contents is None:
        raise CasePackageError(result.errors)
    contents = result.contents

    case = Case.create(dest_root)
    with case.transaction():
        for evidence, raw_bytes in contents.evidence:
            case.blobs.put(raw_bytes)  # blob-first ordering -- see module docstring
            case.store.put_evidence(evidence)
        for event in contents.normalized_events:
            case.store.put_normalized_event(event)
        for entity in contents.entities:
            case.store.put_entity(entity)
        for relationship in contents.relationships:
            case.store.put_relationship(relationship)
        for assertion in contents.time_assertions:
            case.store.put_time_assertion(assertion)
        for hypothesis in contents.hypotheses:
            case.store.put_hypothesis(hypothesis)
    case.record_manifest()
    return case
