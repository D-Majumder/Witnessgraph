"""TimeAssertion: an explicit, source-attributed claim about when something happened.

See DESIGN.md principle 3: Witnessgraph never silently collapses
disagreeing evidence into one "true" timestamp. Multiple TimeAssertions
about the same logical event are preserved side by side; disagreement is
detected structurally, not resolved silently. See
witnessgraph.correlate.contradictions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from witnessgraph.core.ids import new_object_id


class TimePrecision(str, Enum):
    EXACT = "exact"
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAY = "day"
    APPROXIMATE = "approximate"


_PRECISION_TOLERANCE_SECONDS: dict[TimePrecision, float] = {
    TimePrecision.EXACT: 0.0,
    TimePrecision.SECOND: 1.0,
    TimePrecision.MINUTE: 60.0,
    TimePrecision.HOUR: 3600.0,
    TimePrecision.DAY: 86400.0,
    TimePrecision.APPROXIMATE: 6 * 3600.0,
}


class TimeAssertion(BaseModel):
    """A claim, made by one source, about when a NormalizedEvent occurred.

    Immutable once created (DESIGN.md principle 1). ``subject_event_id``
    references the NormalizedEvent this is a claim about, and
    ``source_evidence_id`` references the EvidenceItem the claim was
    derived from -- both are required, so a TimeAssertion always has
    explicit lineage (principle 2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(default_factory=new_object_id)
    subject_event_id: str
    value: datetime
    precision: TimePrecision
    source_evidence_id: str
    asserted_by: str
    created_at: datetime

    def tolerance_seconds(self) -> float:
        return _PRECISION_TOLERANCE_SECONDS[self.precision]

    def disagrees_with(self, other: TimeAssertion) -> bool:
        """True if these two assertions, about the same event, cannot both be correct.

        Two assertions disagree when the gap between their claimed
        values exceeds the sum of what each precision allows for.
        """
        if self.subject_event_id != other.subject_event_id:
            return False
        delta = abs((self.value - other.value).total_seconds())
        tolerance = self.tolerance_seconds() + other.tolerance_seconds()
        return delta > tolerance
