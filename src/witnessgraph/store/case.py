"""Case: one portable Witnessgraph investigation, backed by a single directory.

See DESIGN.md principle 4. A case directory contains ``case.db``
(metadata), ``blobs/`` (raw evidence, content-addressed), and, once a
manifest has been recorded, ``manifest.json``. The whole directory is
what "portable" means -- copy it, zip it, or hand it to another analyst,
and it is everything needed to reopen and verify the investigation. See
``witnessgraph.portable`` for packaging a case into a single archive.
"""

from __future__ import annotations

from pathlib import Path

from witnessgraph.core.provenance import ProvenanceManifest, compute_manifest
from witnessgraph.store.sqlite_store import FileBlobStore, SqliteStore

MANIFEST_FILENAME = "manifest.json"
DB_FILENAME = "case.db"
BLOBS_DIRNAME = "blobs"


class Case:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = SqliteStore(root / DB_FILENAME)
        self.blobs = FileBlobStore(root / BLOBS_DIRNAME)

    @classmethod
    def create(cls, root: Path) -> Case:
        if root.exists() and any(root.iterdir()):
            raise FileExistsError(f"{root} already exists and is not empty")
        root.mkdir(parents=True, exist_ok=True)
        return cls(root)

    @classmethod
    def open(cls, root: Path) -> Case:
        if not (root / DB_FILENAME).exists():
            raise FileNotFoundError(
                f"{root} does not look like a Witnessgraph case (no {DB_FILENAME})"
            )
        return cls(root)

    def close(self) -> None:
        self.store.close()

    def compute_manifest(self) -> ProvenanceManifest:
        return compute_manifest(self.store)

    def record_manifest(self) -> ProvenanceManifest:
        """Compute the current manifest and persist it as manifest.json."""
        manifest = self.compute_manifest()
        (self.root / MANIFEST_FILENAME).write_text(manifest.model_dump_json(indent=2))
        return manifest

    def load_recorded_manifest(self) -> ProvenanceManifest | None:
        path = self.root / MANIFEST_FILENAME
        if not path.exists():
            return None
        return ProvenanceManifest.model_validate_json(path.read_text())
