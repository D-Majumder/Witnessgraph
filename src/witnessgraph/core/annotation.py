"""Shared analyst-annotation invariant, reused by every "tracked inference"
type (``TrackedGapFinding``, ``TrackedTimeContradiction``, ...).

This is a narrow, stable, function-level share -- not a model, table, or
base class -- and does not merge any of the tracked-inference types into
one type or one collection (see docs/phase4-v0.4-gap-analysis-design.md
§9's structural-separation rule, which this module does not touch).
"""

from __future__ import annotations

from datetime import datetime


def validate_annotation_pairing(annotated_by: str | None, annotated_at: datetime | None) -> None:
    """Enforce the annotation-pairing/non-blank invariant.

    Must be called explicitly from BOTH a model's own construction-time
    validator AND its update path (e.g. a ``with_annotation()`` method)
    -- these are NOT the same code path in Pydantic v2:
    ``model_copy(update=...)`` deliberately does not re-run validators
    (documented Pydantic behavior, not a bug), so relying on the
    construction-time validator alone would silently let an update method
    produce an invalid object (e.g. a whitespace-only ``annotated_by``)
    that the constructor would have rejected. This was found and fixed
    during v0.7's adversarial implementation review; every subsequent
    tracked-inference type must call this function from both places from
    the start, not re-discover the same gap.
    """
    has_by = annotated_by is not None
    has_at = annotated_at is not None
    if has_by != has_at:
        raise ValueError(
            "annotated_by and annotated_at must both be set or both be "
            "None -- a never-annotated record has neither"
        )
    if has_by and not annotated_by.strip():  # type: ignore[union-attr]
        raise ValueError("annotated_by must not be blank when present")
