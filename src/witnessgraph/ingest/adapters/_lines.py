"""Shared line-splitting/decoding helper for the built-in text-based adapters.

Splits raw file bytes into physical lines *before* decoding, and decodes
each line independently, so that a single line containing invalid UTF-8
bytes cannot prevent every other, validly-encoded line in the same file
from being read. This extends the adapters' existing "evidence is
preserved even when it cannot be normalized" philosophy (previously only
applied to content that failed to *parse*, e.g. malformed JSON) to also
cover content that fails to *decode*.
"""

from __future__ import annotations

from collections.abc import Iterator


def iter_raw_lines(raw_bytes: bytes) -> Iterator[tuple[int, bytes, str | None]]:
    """Yield ``(1-based line number, raw line bytes, decoded text or None)``.

    The decoded text is ``None`` exactly when that line's bytes are not
    valid UTF-8 -- callers should still treat the raw bytes as evidence
    in that case, they should just skip attempting to normalize them
    (the same way an adapter already treats a syntactically-invalid but
    validly-encoded line).
    """
    for line_no, raw_line in enumerate(raw_bytes.split(b"\n"), start=1):
        if raw_line.endswith(b"\r"):
            raw_line = raw_line[:-1]
        try:
            text: str | None = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        yield line_no, raw_line, text
