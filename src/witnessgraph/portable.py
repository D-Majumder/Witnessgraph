"""Export / import a Case as a single portable ``.wgcase`` archive.

See DESIGN.md principle 4: importing an exported case elsewhere and
recomputing its provenance manifest must produce the exact same manifest
hash as the original.

Security note on ``import_case``: a ``.wgcase`` archive may come from
another researcher and must be treated as untrusted input. Every member
name is validated to resolve strictly inside ``dest_root`` before
anything is extracted (defense in depth against path traversal / a
crafted absolute or ``..``-containing entry, on top of the sanitization
CPython's own ``zipfile`` already applies), and both a per-member and a
total uncompressed-size ceiling are enforced *before* any bytes are
decompressed, to bound a decompression-bomb archive's worst-case disk
usage. See ``tests/integration/test_portable_security.py``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from witnessgraph.store.case import Case
from witnessgraph.store.sqlite_store import SqliteStore

#: Ceilings applied to a ``.wgcase`` archive before extraction -- a
#: policy choice, not derived from any specific case's actual size, but
#: generous enough for any legitimate case while bounding a
#: decompression bomb's worst case. See this module's security note.
MAX_MEMBER_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024


class UnsafeArchiveError(ValueError):
    """A ``.wgcase`` archive failed a path-safety or size-ceiling check."""


def _safe_member_target(dest_root: Path, member_name: str) -> Path:
    """Resolve ``member_name`` under ``dest_root``, rejecting any path that
    would escape it (absolute path, ``..`` traversal, or a drive change)."""
    candidate = (dest_root / member_name).resolve()
    dest_resolved = dest_root.resolve()
    if candidate != dest_resolved and dest_resolved not in candidate.parents:
        raise UnsafeArchiveError(
            f"archive member {member_name!r} would extract outside the destination directory"
        )
    return candidate


def export_case(case: Case, output_path: Path) -> Path:
    """Package ``case``'s directory into a single ``.wgcase`` zip archive.

    The manifest is (re)computed and recorded before packaging, so the
    archive always contains an up-to-date, verifiable manifest.json.
    """
    if output_path.exists():
        raise FileExistsError(output_path)

    case.record_manifest()
    case.store.close()  # flush and unlock the sqlite file before copying it
    try:
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(case.root.rglob("*")):
                if path.is_file():
                    zf.write(path, arcname=path.relative_to(case.root).as_posix())
    finally:
        case.store = SqliteStore(case.root / "case.db")  # reopen for continued use
    return output_path


def import_case(archive_path: Path, dest_root: Path) -> Case:
    """Unpack a ``.wgcase`` archive into ``dest_root`` and open it as a Case.

    The archive is opened, and every member validated, before
    ``dest_root`` is created or anything is written, so a missing,
    invalid, or unsafe archive (``FileNotFoundError``/
    ``zipfile.BadZipFile``/``UnsafeArchiveError``) never leaves behind a
    partially-created, empty destination directory. See this module's
    security note.
    """
    if dest_root.exists() and any(dest_root.iterdir()):
        raise FileExistsError(f"{dest_root} already exists and is not empty")
    with zipfile.ZipFile(archive_path, "r") as zf:
        infos = zf.infolist()
        total_uncompressed = 0
        targets: list[tuple[zipfile.ZipInfo, Path]] = []
        for info in infos:
            if info.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES:
                raise UnsafeArchiveError(
                    f"archive member {info.filename!r} claims {info.file_size} uncompressed "
                    f"bytes, exceeding the maximum of {MAX_MEMBER_UNCOMPRESSED_BYTES} "
                    "this installation accepts"
                )
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise UnsafeArchiveError(
                    f"archive's total uncompressed size exceeds the maximum of "
                    f"{MAX_TOTAL_UNCOMPRESSED_BYTES} bytes this installation accepts"
                )
            target = _safe_member_target(dest_root, info.filename)
            targets.append((info, target))

        dest_root.mkdir(parents=True, exist_ok=True)
        for info, target in targets:
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())
    return Case.open(dest_root)
