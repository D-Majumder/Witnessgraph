"""Export / import a Case as a single portable ``.wgcase`` archive.

See DESIGN.md principle 4: importing an exported case elsewhere and
recomputing its provenance manifest must produce the exact same manifest
hash as the original.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from witnessgraph.store.case import Case
from witnessgraph.store.sqlite_store import SqliteStore


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
    """Unpack a ``.wgcase`` archive into ``dest_root`` and open it as a Case."""
    if dest_root.exists() and any(dest_root.iterdir()):
        raise FileExistsError(f"{dest_root} already exists and is not empty")
    dest_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(dest_root)
    return Case.open(dest_root)
