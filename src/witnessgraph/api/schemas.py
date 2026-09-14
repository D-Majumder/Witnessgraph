"""Request body models.

The only place this API needs a genuine Pydantic *request* model: every
other endpoint is a GET with plain query parameters. ``AckRequest`` is
not a domain model competing with ``core.tracked_finding``/
``core.tracked_time_contradiction`` -- it exists purely to validate one
POST body's shape (a required, non-blank ``status``/``by`` and an
optional ``note``), then hands its fields straight to
``witnessgraph.service``, which does the actual validation/writing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from witnessgraph.core.tracked_finding import FindingStatus


class AckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FindingStatus
    by: str
    note: str | None = None
