"""Deterministic identifiers and canonical serialization primitives.

See DESIGN.md principle 5 (provenance is cryptographically verifiable):
every hash in Witnessgraph is computed over a canonical byte
representation so that the same logical content always produces the
same hash, on any machine, at any time.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any


def new_object_id() -> str:
    """A random identifier for a derived (non-content-addressed) object.

    Used for objects whose identity is established once, when they are
    first created within a case (NormalizedEvent, Entity, Hypothesis,
    TimeAssertion) -- as opposed to raw evidence, whose identity is its
    own content hash. See DESIGN.md principle 1.
    """
    return str(uuid.uuid4())


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("naive datetimes are not permitted in canonical serialization")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"object of type {type(value).__name__} is not canonically serializable")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize ``value`` to a deterministic, reproducible JSON byte string.

    Keys are sorted, whitespace is minimal, and datetimes are normalized
    to UTC ISO-8601 with a ``Z`` suffix. Two logically identical objects
    always produce byte-identical output, regardless of dict insertion
    order, timezone, or machine.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Hex-encoded SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """The content-address of ``value``: sha256 of its canonical JSON form."""
    return sha256_hex(canonical_json_bytes(value))
