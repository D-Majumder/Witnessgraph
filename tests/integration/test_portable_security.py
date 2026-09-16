"""Security hardening tests for untrusted archive import.

Covers both ``witnessgraph.portable.import_case`` (the existing
``.wgcase`` binary case archive, hardened by this milestone against
path traversal and decompression bombs) and
``witnessgraph.casepkg.archive`` (the new ``.witnessgraph-case`` case
package wrapper, which never calls ``extractall`` at all -- see that
module's docstring)."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from witnessgraph.casepkg.archive import (
    MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES as _MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES,
)
from witnessgraph.casepkg.archive import (
    ArchiveError,
    read_case_package_archive,
    write_case_package_archive,
)
from witnessgraph.portable import (
    MAX_MEMBER_UNCOMPRESSED_BYTES,
    UnsafeArchiveError,
    export_case,
    import_case,
)
from witnessgraph.store.case import Case


def _build_trivial_case(root: Path) -> Case:
    case = Case.create(root)
    case.record_manifest()
    return case


def _lie_about_uncompressed_size(zip_path: Path, new_size: int) -> None:
    """Patch every central-directory record's recorded uncompressed size,
    without actually writing that much data -- exactly the shape of a
    real decompression-bomb archive's lie, and exactly what our size
    checks (which read ``ZipInfo.file_size`` from the central directory
    before decompressing anything) must catch."""
    data = bytearray(zip_path.read_bytes())
    offset = 0
    while True:
        offset = data.find(b"PK\x01\x02", offset)
        if offset == -1:
            break
        size_field_offset = offset + 24
        data[size_field_offset : size_field_offset + 4] = new_size.to_bytes(4, "little")
        offset += 4
    zip_path.write_bytes(bytes(data))


def test_legitimate_wgcase_archive_still_imports_after_hardening(tmp_path: Path) -> None:
    case = _build_trivial_case(tmp_path / "original")
    archive = export_case(case, tmp_path / "case.wgcase")
    case.close()
    restored = import_case(archive, tmp_path / "restored")
    assert restored.compute_manifest().manifest_hash is not None
    restored.close()


def test_wgcase_rejects_path_traversal_member(tmp_path: Path) -> None:
    malicious = tmp_path / "evil.wgcase"
    with zipfile.ZipFile(malicious, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")
    dest = tmp_path / "dest"
    # Either our own UnsafeArchiveError (if traversal reaches our check) or
    # some other failure (e.g. Case.open's FileNotFoundError, if CPython's
    # own zipfile sanitization neutralized the entry name first) is an
    # acceptable outcome -- what must NEVER happen is a file landing
    # outside dest, checked below regardless of which exception fired.
    with pytest.raises(Exception):  # noqa: B017
        import_case(malicious, dest)
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()


def test_wgcase_rejects_absolute_path_member(tmp_path: Path) -> None:
    malicious = tmp_path / "evil.wgcase"
    target_outside = tmp_path / "outside" / "evil.txt"
    with zipfile.ZipFile(malicious, "w") as zf:
        zf.writestr(str(target_outside), "pwned")
    dest = tmp_path / "dest"
    with pytest.raises(Exception):  # noqa: B017 -- see traversal test above
        import_case(malicious, dest)
    assert not target_outside.exists()


def test_wgcase_rejects_oversized_member(tmp_path: Path) -> None:
    malicious = tmp_path / "bomb.wgcase"
    with zipfile.ZipFile(malicious, "w") as zf:
        zf.writestr("case.db", b"x")
    _lie_about_uncompressed_size(malicious, MAX_MEMBER_UNCOMPRESSED_BYTES + 1)
    dest = tmp_path / "dest"
    with pytest.raises(UnsafeArchiveError):
        import_case(malicious, dest)
    assert not dest.exists() or not any(dest.iterdir())


def test_case_package_archive_rejects_tampered_content(tmp_path: Path) -> None:
    archive = write_case_package_archive(
        b'{"hello": "world"}',
        schema_version=1,
        package_version="1.0",
        output_path=tmp_path / "case.witnessgraph-case",
    )
    # Tamper with case.json in place without updating the recorded hash.
    with zipfile.ZipFile(archive, "r") as zf:
        manifest_bytes = zf.read("manifest.json")
    tampered = tmp_path / "tampered.witnessgraph-case"
    with zipfile.ZipFile(tampered, "w") as zf:
        zf.writestr("case.json", b'{"hello": "tampered"}')
        zf.writestr("manifest.json", manifest_bytes)
    with pytest.raises(ArchiveError, match="integrity check failed"):
        read_case_package_archive(tampered)


def test_case_package_archive_rejects_missing_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "no-manifest.witnessgraph-case"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("case.json", b"{}")
    with pytest.raises(ArchiveError, match="missing required member"):
        read_case_package_archive(archive)


def test_case_package_archive_never_calls_extractall() -> None:
    """Static guard: this format must never gain a path-traversal surface
    by someone later "simplifying" it to an actual `zf.extractall(...)`
    call (a bare docstring mention of the name, as in this module's own
    security note, is fine and must not trip this check)."""
    import inspect

    from witnessgraph.casepkg import archive as archive_module

    source = inspect.getsource(archive_module)
    assert "extractall(" not in source


def test_case_package_archive_rejects_oversized_declared_member(tmp_path: Path) -> None:
    archive = write_case_package_archive(
        b"{}",
        schema_version=1,
        package_version="1.0",
        output_path=tmp_path / "bomb.witnessgraph-case",
    )
    _lie_about_uncompressed_size(archive, _MAX_ARCHIVE_MEMBER_UNCOMPRESSED_BYTES + 1)
    with pytest.raises(ArchiveError, match="exceeding the maximum"):
        read_case_package_archive(archive)
