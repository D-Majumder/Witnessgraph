"""Read/write a ``.witnessgraph-case`` archive: a portable, verifiable
case-package wrapper around one ``case.json``.

Security note: unlike ``witnessgraph.portable.import_case`` (which
extracts an entire ``.wgcase`` directory tree and therefore needs its own
path-traversal hardening -- see that module), this archive format never
calls ``ZipFile.extractall`` at all. It reads exactly two fixed,
hard-coded member names (``case.json``, ``manifest.json``) by name and
ignores everything else in the zip -- there is no code path here that
turns any zip-entry-supplied name into a filesystem path, so path
traversal, absolute paths, and symlink members are structurally not a
concern for this format specifically.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from witnessgraph import __version__ as WITNESSGRAPH_VERSION
from witnessgraph.core.ids import canonical_json_bytes, sha256_hex

CASE_JSON_MEMBER = "case.json"
MANIFEST_JSON_MEMBER = "manifest.json"

#: A ceiling on the *compressed* size of any single member this reader
#: will decompress -- a coarse but effective decompression-bomb guard,
#: applied before any bytes are read into memory. A legitimate case
#: package's ``case.json`` is plain, non-adversarial JSON; there is no
#: reason for it to compress an amount of data anywhere near this limit.
MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES = 200 * 1024 * 1024


class ArchiveError(ValueError):
    """A ``.witnessgraph-case`` archive is malformed or fails a safety check."""


@dataclass(frozen=True)
class ArchiveManifest:
    schema_version: int
    package_version: str
    content_sha256: str
    witnessgraph_version: str


def read_case_package_archive(path: Path) -> tuple[bytes, ArchiveManifest]:
    """Read and verify a ``.witnessgraph-case`` archive's ``case.json``.

    Returns the raw ``case.json`` bytes (still unvalidated as a
    ``CasePackage`` -- see ``validate.py``/``importer.py`` for that) and
    the archive's own recorded manifest, after confirming the recorded
    ``content_sha256`` actually matches the bytes read -- this is what
    lets a researcher verify "this is exactly the package that was
    analyzed" (see docs/research/witnessgraph-case-format.md).
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = set(zf.namelist())
            if CASE_JSON_MEMBER not in names:
                raise ArchiveError(f"archive is missing required member {CASE_JSON_MEMBER!r}")
            if MANIFEST_JSON_MEMBER not in names:
                raise ArchiveError(f"archive is missing required member {MANIFEST_JSON_MEMBER!r}")

            for member_name in (CASE_JSON_MEMBER, MANIFEST_JSON_MEMBER):
                info = zf.getinfo(member_name)
                if info.file_size > MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES:
                    raise ArchiveError(
                        f"archive member {member_name!r} claims {info.file_size} uncompressed "
                        f"bytes, exceeding the maximum of {MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES} "
                        "this installation accepts"
                    )

            case_json_bytes = zf.read(CASE_JSON_MEMBER)
            manifest_bytes = zf.read(MANIFEST_JSON_MEMBER)
    except zipfile.BadZipFile as exc:
        raise ArchiveError(f"{path} is not a valid .witnessgraph-case archive: {exc}") from exc

    try:
        manifest_raw = json.loads(manifest_bytes)
    except ValueError as exc:
        raise ArchiveError(f"manifest.json is not valid JSON: {exc}") from exc

    try:
        manifest = ArchiveManifest(
            schema_version=int(manifest_raw["schema_version"]),
            package_version=str(manifest_raw["package_version"]),
            content_sha256=str(manifest_raw["content_sha256"]),
            witnessgraph_version=str(manifest_raw["witnessgraph_version"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ArchiveError(f"manifest.json is missing or has a malformed field: {exc}") from exc

    actual_hash = sha256_hex(case_json_bytes)
    if actual_hash != manifest.content_sha256:
        raise ArchiveError(
            f"integrity check failed: manifest.json records content_sha256="
            f"{manifest.content_sha256!r} but case.json actually hashes to {actual_hash!r} "
            "-- the archive may be corrupted or tampered with"
        )

    return case_json_bytes, manifest


def write_case_package_archive(
    case_json_bytes: bytes, *, schema_version: int, package_version: str, output_path: Path
) -> Path:
    """Write ``case_json_bytes`` and a matching, verifiable manifest into a new archive."""
    if output_path.exists():
        raise FileExistsError(output_path)
    manifest = {
        "schema_version": schema_version,
        "package_version": package_version,
        "content_sha256": sha256_hex(case_json_bytes),
        "witnessgraph_version": WITNESSGRAPH_VERSION,
    }
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(CASE_JSON_MEMBER, case_json_bytes)
        zf.writestr(MANIFEST_JSON_MEMBER, canonical_json_bytes(manifest))
    return output_path
