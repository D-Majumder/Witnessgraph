"""Open a case and produce its lightweight overview.

Mirrors ``cli.main._open_case_or_fail`` exactly (same two exceptions
translated), and ``correlate.overview.compute_case_overview`` for the
overview itself -- see ``docs/phase-ui-v1-architecture-design.md`` §5
gap #1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from witnessgraph.correlate.overview import case_overview_to_json, compute_case_overview
from witnessgraph.service.errors import CaseNotFoundError, CaseUnreadableError
from witnessgraph.store.case import Case


def open_case(case_dir: Path) -> Case:
    """Open ``case_dir`` as a Witnessgraph case, or raise a
    :class:`~witnessgraph.service.errors.ServiceError` describing exactly
    why not -- the same two failure conditions
    ``cli.main._open_case_or_fail`` already distinguishes."""
    try:
        return Case.open(case_dir)
    except FileNotFoundError as exc:
        raise CaseNotFoundError(str(case_dir)) from exc
    except sqlite3.DatabaseError as exc:
        raise CaseUnreadableError(str(case_dir)) from exc


def get_case_overview(case: Case) -> dict[str, object]:
    """Case identity, counts, and manifest verdict for ``case``."""
    recomputed_manifest = case.compute_manifest()
    recorded_manifest = case.load_recorded_manifest()
    overview = compute_case_overview(
        case.store,
        case_name=case.root.name,
        recomputed_manifest=recomputed_manifest,
        recorded_manifest=recorded_manifest,
    )
    return case_overview_to_json(overview)
