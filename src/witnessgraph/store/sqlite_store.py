"""SqliteStore / FileBlobStore: the v0.1 local-first Store/BlobStore implementations.

See DESIGN.md principle 6: ``db_path`` and blob ``root`` are always local
filesystem paths; nothing here opens a socket.

Known limitation (see SECURITY.md for the full explanation): each ``put_*``
call is its own committed write. A multi-record ingest is not wrapped in a
single transaction, so a process killed mid-ingest can leave a case with
some, but not all, of a source's records -- there is no atomicity guarantee
across a batch of writes in v0.1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import Hypothesis
from witnessgraph.core.ids import sha256_hex
from witnessgraph.core.time_model import TimeAssertion

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_items (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS normalized_events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS time_assertions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hypotheses (id TEXT PRIMARY KEY, data TEXT NOT NULL);
"""


class SqliteStore:
    """A Store implementation backed by a single local SQLite file.

    Evidence/normalized-events/entities/time-assertions are effectively
    append-only (their ids are either content hashes or freshly generated
    UUIDs that are never expected to collide with different content).
    Hypotheses are the one object type with a real lifecycle
    (proposed -> supported/contradicted/withdrawn) and are stored as an
    upsert-by-id, since a status change is a legitimate new state for
    the *same* hypothesis, not a different one -- see
    ``witnessgraph.core.hypothesis.Hypothesis.with_status``.
    """

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- evidence -----------------------------------------------------
    def put_evidence(self, item: EvidenceItem) -> None:
        """Store ``item``, merging with any existing record for the same content id.

        Evidence ids are content hashes, so two calls with the same id
        always describe byte-identical content -- but they may come from
        different sources (e.g. the same line present in two different
        collected files). A naive overwrite would silently destroy the
        first source's ``source_locator``/``collected_at``/custody
        history, which would violate DESIGN.md principle 1 exactly as
        badly as mutating the raw bytes would. So: the first-known
        source identity fields are never overwritten, and only genuinely
        new custody records (by value, which includes each record's own
        ``source_locator``) are appended -- re-ingesting the exact same
        source again is therefore a safe no-op, not a duplicate entry.
        """
        existing = self.get_evidence(item.id)
        if existing is None:
            self._conn.execute(
                "INSERT INTO evidence_items (id, data) VALUES (?, ?)",
                (item.id, item.model_dump_json()),
            )
            self._conn.commit()
            return

        new_records = tuple(
            record for record in item.chain_of_custody if record not in existing.chain_of_custody
        )
        if not new_records:
            return  # nothing new to record -- avoid a redundant write

        merged = existing.model_copy(
            update={"chain_of_custody": (*existing.chain_of_custody, *new_records)}
        )
        self._conn.execute(
            "UPDATE evidence_items SET data = ? WHERE id = ?",
            (merged.model_dump_json(), merged.id),
        )
        self._conn.commit()

    def get_evidence(self, id: str) -> EvidenceItem | None:
        row = self._conn.execute(
            "SELECT data FROM evidence_items WHERE id = ?", (id,)
        ).fetchone()
        return EvidenceItem.model_validate_json(row[0]) if row else None

    def list_evidence(self) -> list[EvidenceItem]:
        rows = self._conn.execute("SELECT data FROM evidence_items ORDER BY id").fetchall()
        return [EvidenceItem.model_validate_json(r[0]) for r in rows]

    # -- normalized events ---------------------------------------------
    def put_normalized_event(self, event: NormalizedEvent) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO normalized_events (id, data) VALUES (?, ?)",
            (event.id, event.model_dump_json()),
        )
        self._conn.commit()

    def get_normalized_event(self, id: str) -> NormalizedEvent | None:
        row = self._conn.execute(
            "SELECT data FROM normalized_events WHERE id = ?", (id,)
        ).fetchone()
        return NormalizedEvent.model_validate_json(row[0]) if row else None

    def list_normalized_events(self) -> list[NormalizedEvent]:
        rows = self._conn.execute("SELECT data FROM normalized_events ORDER BY id").fetchall()
        return [NormalizedEvent.model_validate_json(r[0]) for r in rows]

    # -- entities --------------------------------------------------------
    def put_entity(self, entity: Entity) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO entities (id, data) VALUES (?, ?)",
            (entity.id, entity.model_dump_json()),
        )
        self._conn.commit()

    def get_entity(self, id: str) -> Entity | None:
        row = self._conn.execute("SELECT data FROM entities WHERE id = ?", (id,)).fetchone()
        return Entity.model_validate_json(row[0]) if row else None

    def list_entities(self) -> list[Entity]:
        rows = self._conn.execute("SELECT data FROM entities ORDER BY id").fetchall()
        return [Entity.model_validate_json(r[0]) for r in rows]

    # -- time assertions ---------------------------------------------
    def put_time_assertion(self, assertion: TimeAssertion) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO time_assertions (id, data) VALUES (?, ?)",
            (assertion.id, assertion.model_dump_json()),
        )
        self._conn.commit()

    def list_time_assertions(self) -> list[TimeAssertion]:
        rows = self._conn.execute("SELECT data FROM time_assertions ORDER BY id").fetchall()
        return [TimeAssertion.model_validate_json(r[0]) for r in rows]

    # -- hypotheses ------------------------------------------------------
    def put_hypothesis(self, hypothesis: Hypothesis) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO hypotheses (id, data) VALUES (?, ?)",
            (hypothesis.id, hypothesis.model_dump_json()),
        )
        self._conn.commit()

    def get_hypothesis(self, id: str) -> Hypothesis | None:
        row = self._conn.execute("SELECT data FROM hypotheses WHERE id = ?", (id,)).fetchone()
        return Hypothesis.model_validate_json(row[0]) if row else None

    def list_hypotheses(self) -> list[Hypothesis]:
        rows = self._conn.execute("SELECT data FROM hypotheses ORDER BY id").fetchall()
        return [Hypothesis.model_validate_json(r[0]) for r in rows]


class FileBlobStore:
    """Content-addressed blob storage on the local filesystem.

    Blobs live at ``<root>/<hash[:2]>/<hash>`` and are written once and
    never modified afterward (DESIGN.md principle 1). Writing the same
    bytes again is a cheap no-op, not a second write. Writes are staged
    to a temp file and atomically renamed into place.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str) -> Path:
        return self._root / digest[:2] / digest

    def put(self, data: bytes) -> str:
        digest = sha256_hex(data)
        path = self._path_for(digest)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_name(path.name + ".tmp")
            tmp_path.write_bytes(data)
            tmp_path.replace(path)
        return digest

    def get(self, content_hash: str) -> bytes:
        return self._path_for(content_hash).read_bytes()

    def has(self, content_hash: str) -> bool:
        return self._path_for(content_hash).exists()
