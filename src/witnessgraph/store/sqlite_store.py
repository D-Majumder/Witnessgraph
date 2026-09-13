"""SqliteStore / FileBlobStore: the v0.1 local-first Store/BlobStore implementations.

See DESIGN.md principle 6: ``db_path`` and blob ``root`` are always local
filesystem paths; nothing here opens a socket.

See docs/phase3-v0.3-design.md §8: ``transaction()`` lets a caller (in
practice, ``witnessgraph.ingest.pipeline.ingest_source``) group multiple
``put_*`` calls into one atomic SQLite transaction, committed only once
the whole group succeeds and rolled back in full on any exception --
closing the crash-atomicity gap this module's docstring used to describe
as a known limitation of v0.1. Outside of an explicit ``transaction()``
block, each ``put_*`` call still commits immediately on its own, exactly
as in v0.1/v0.2, so every other caller (``entities create``,
``hypothesis propose``, etc.) is unaffected.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from witnessgraph.core.entities import Entity
from witnessgraph.core.events import NormalizedEvent
from witnessgraph.core.evidence import EvidenceItem
from witnessgraph.core.hypothesis import Hypothesis
from witnessgraph.core.ids import sha256_hex
from witnessgraph.core.time_model import TimeAssertion
from witnessgraph.core.tracked_finding import FindingStatus, TrackedGapFinding
from witnessgraph.core.tracked_time_contradiction import TrackedTimeContradiction

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_items (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS normalized_events (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS time_assertions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hypotheses (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tracked_gap_findings (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tracked_time_contradictions (id TEXT PRIMARY KEY, data TEXT NOT NULL);
"""


class NormalizedEventConflictError(RuntimeError):
    """Raised when an incoming NormalizedEvent shares an id with a stored one
    but its content is not the same, aside from ``created_at``.

    Content-addressing guarantees that ``event_type``/``attributes``/
    ``derived_from`` already match on an id collision (barring a SHA-256
    collision, out of scope). The one field this cannot guarantee is
    ``entity_ids``, which is deliberately excluded from identity (see
    ``NormalizedEvent.identity_hash``) -- so a real conflict here means an
    incoming record disagrees with the stored one on ``entity_ids`` (or,
    in principle, on an id collision that should be practically
    impossible). Either way this is a genuine data-integrity conflict,
    never something to silently discard or silently merge -- see
    docs/phase3-v0.3-design.md §7's identity design and the review that
    flagged this as an untested silent-data-loss vector.
    """

    def __init__(self, event_id: str) -> None:
        super().__init__(
            f"NormalizedEvent {event_id!r} already exists in the store with "
            "different content (entity_ids or another field differs from the "
            "incoming record, aside from created_at) -- refusing to silently "
            "discard or merge the incoming record"
        )
        self.event_id = event_id


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
        self._in_transaction = False

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Group every ``put_*`` call made inside this block into one atomic commit.

        On success, all writes made inside the block are committed
        together, once, when the block exits. On any exception, every
        write made inside the block is rolled back -- the store ends up
        exactly as it was before the block started, with no partial
        writes visible. Re-entrant: a nested ``transaction()`` call (e.g.
        library code calling into another function that also opens one)
        joins the outermost transaction rather than committing early.
        """
        if self._in_transaction:
            yield
            return
        self._in_transaction = True
        try:
            yield
        except BaseException:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()
        finally:
            self._in_transaction = False

    def _maybe_commit(self) -> None:
        """Commit immediately unless a ``transaction()`` block is grouping this write."""
        if not self._in_transaction:
            self._conn.commit()

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
            self._maybe_commit()
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
        self._maybe_commit()

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
        """Store ``event``, as an insert-if-absent that verifies before it ignores.

        See docs/phase3-v0.3-design.md §6.2/§21.6: a v0.3 ``.create()``-built
        ``NormalizedEvent``'s id is itself a content hash of its
        identity-relevant fields (``event_type``/``attributes``/
        ``derived_from``), so those three fields are already guaranteed
        equal on an id collision. The one field this cannot guarantee is
        ``entity_ids`` (deliberately excluded from identity), plus
        ``created_at`` (also excluded, and *expected* to differ between
        two genuine re-derivations at different wall-clock times -- see
        the reproducibility regression tests). So on a collision:

        - if the incoming event is identical to the stored one in every
          field except ``created_at``, this is a safe, idempotent no-op
          (the ordinary re-ingest case);
        - otherwise (most concretely: ``entity_ids`` differs, or -- in
          principle only -- a SHA-256 collision produced two genuinely
          different objects under the same id) this raises
          ``NormalizedEventConflictError`` rather than silently keeping
          the first-written version and discarding the incoming one, or
          silently merging ``entity_ids``. Raising here, inside an active
          ``transaction()`` block, is what triggers that transaction's
          own rollback -- see ``SqliteStore.transaction``.
        """
        existing = self.get_normalized_event(event.id)
        if existing is not None:
            if existing.model_copy(update={"created_at": event.created_at}) != event:
                raise NormalizedEventConflictError(event.id)
            return  # identical aside from created_at -- safe, idempotent no-op
        self._conn.execute(
            "INSERT INTO normalized_events (id, data) VALUES (?, ?)",
            (event.id, event.model_dump_json()),
        )
        self._maybe_commit()

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
        self._maybe_commit()

    def get_entity(self, id: str) -> Entity | None:
        row = self._conn.execute("SELECT data FROM entities WHERE id = ?", (id,)).fetchone()
        return Entity.model_validate_json(row[0]) if row else None

    def list_entities(self) -> list[Entity]:
        rows = self._conn.execute("SELECT data FROM entities ORDER BY id").fetchall()
        return [Entity.model_validate_json(r[0]) for r in rows]

    # -- time assertions ---------------------------------------------
    def put_time_assertion(self, assertion: TimeAssertion) -> None:
        """Store ``assertion``, as an insert-if-absent -- see ``put_normalized_event``."""
        self._conn.execute(
            "INSERT OR IGNORE INTO time_assertions (id, data) VALUES (?, ?)",
            (assertion.id, assertion.model_dump_json()),
        )
        self._maybe_commit()

    def get_time_assertion(self, id: str) -> TimeAssertion | None:
        row = self._conn.execute(
            "SELECT data FROM time_assertions WHERE id = ?", (id,)
        ).fetchone()
        return TimeAssertion.model_validate_json(row[0]) if row else None

    def list_time_assertions(self) -> list[TimeAssertion]:
        rows = self._conn.execute("SELECT data FROM time_assertions ORDER BY id").fetchall()
        return [TimeAssertion.model_validate_json(r[0]) for r in rows]

    # -- hypotheses ------------------------------------------------------
    def put_hypothesis(self, hypothesis: Hypothesis) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO hypotheses (id, data) VALUES (?, ?)",
            (hypothesis.id, hypothesis.model_dump_json()),
        )
        self._maybe_commit()

    def get_hypothesis(self, id: str) -> Hypothesis | None:
        row = self._conn.execute("SELECT data FROM hypotheses WHERE id = ?", (id,)).fetchone()
        return Hypothesis.model_validate_json(row[0]) if row else None

    def list_hypotheses(self) -> list[Hypothesis]:
        rows = self._conn.execute("SELECT data FROM hypotheses ORDER BY id").fetchall()
        return [Hypothesis.model_validate_json(r[0]) for r in rows]

    # -- tracked gap findings (v0.7) --------------------------------------
    def create_tracked_finding(self, finding: TrackedGapFinding) -> TrackedGapFinding:
        """Insert-if-absent by ``finding.id`` (content-derived).

        If a row with this id already exists, it is returned UNCHANGED --
        re-discovery of an already-tracked finding never resets or
        overwrites its status/annotated_by/annotated_at/note, even if the
        incoming ``finding`` object (e.g. freshly built by the caller
        with status=OPEN) differs in those fields. Callers
        (``gaps --track``) are expected to always pass a freshly
        constructed, never-annotated finding here; this method's own
        insert-if-absent behavior is what makes that safe regardless.
        """
        existing = self.get_tracked_finding(finding.id)
        if existing is not None:
            return existing
        self._conn.execute(
            "INSERT INTO tracked_gap_findings (id, data) VALUES (?, ?)",
            (finding.id, finding.model_dump_json()),
        )
        self._maybe_commit()
        return finding

    def annotate_tracked_finding(
        self,
        id: str,
        *,
        status: FindingStatus,
        annotated_by: str,
        annotated_at: datetime,
        note: str | None,
    ) -> TrackedGapFinding:
        """Update ONLY the annotation of an existing tracked finding.

        Anchor fields are never parameters to this method and are always
        copied byte-for-byte from the stored row via
        ``TrackedGapFinding.with_annotation()`` -- there is no parameter
        through which a caller could supply a different anchor value.
        Raises ``ValueError`` if no row with this id exists (annotating
        requires the finding to have been tracked first; this never
        silently creates one). There is no history: the previous
        annotation is permanently discarded, not archived.
        """
        existing = self.get_tracked_finding(id)
        if existing is None:
            raise ValueError(f"no tracked finding {id!r} to annotate")
        updated = existing.with_annotation(
            status=status, annotated_by=annotated_by, annotated_at=annotated_at, note=note
        )
        assert updated.id == existing.id  # defense-in-depth: anchor cannot have moved
        self._conn.execute(
            "UPDATE tracked_gap_findings SET data = ? WHERE id = ?",
            (updated.model_dump_json(), id),
        )
        self._maybe_commit()
        return updated

    def get_tracked_finding(self, id: str) -> TrackedGapFinding | None:
        row = self._conn.execute(
            "SELECT data FROM tracked_gap_findings WHERE id = ?", (id,)
        ).fetchone()
        return TrackedGapFinding.model_validate_json(row[0]) if row else None

    def list_tracked_findings(self) -> list[TrackedGapFinding]:
        rows = self._conn.execute(
            "SELECT data FROM tracked_gap_findings ORDER BY id"
        ).fetchall()
        return [TrackedGapFinding.model_validate_json(r[0]) for r in rows]

    # -- tracked time contradictions (v0.8) -------------------------------
    #
    # Structurally independent of tracked_gap_findings: separate table,
    # separate model, never iterated or joined together -- see
    # docs/phase4-v0.4-gap-analysis-design.md §9.
    def create_tracked_contradiction(
        self, contradiction: TrackedTimeContradiction
    ) -> TrackedTimeContradiction:
        """Insert-if-absent by ``contradiction.id`` (content-derived).

        If a row with this id already exists, it is returned UNCHANGED --
        re-discovery of an already-tracked contradiction never resets or
        overwrites its status/annotated_by/annotated_at/note, mirroring
        ``create_tracked_finding``'s exact semantics.
        """
        existing = self.get_tracked_contradiction(contradiction.id)
        if existing is not None:
            return existing
        self._conn.execute(
            "INSERT INTO tracked_time_contradictions (id, data) VALUES (?, ?)",
            (contradiction.id, contradiction.model_dump_json()),
        )
        self._maybe_commit()
        return contradiction

    def annotate_tracked_contradiction(
        self,
        id: str,
        *,
        status: FindingStatus,
        annotated_by: str,
        annotated_at: datetime,
        note: str | None,
    ) -> TrackedTimeContradiction:
        """Update ONLY the annotation of an existing tracked contradiction.

        Anchor fields (``subject_event_id``, ``assertion_ids``) are never
        parameters to this method and are always copied byte-for-byte
        from the stored row via
        ``TrackedTimeContradiction.with_annotation()`` -- there is no
        parameter through which a caller could supply a different anchor
        value. Raises ``ValueError`` if no row with this id exists.
        """
        existing = self.get_tracked_contradiction(id)
        if existing is None:
            raise ValueError(f"no tracked contradiction {id!r} to annotate")
        updated = existing.with_annotation(
            status=status, annotated_by=annotated_by, annotated_at=annotated_at, note=note
        )
        assert updated.id == existing.id  # defense-in-depth: anchor cannot have moved
        self._conn.execute(
            "UPDATE tracked_time_contradictions SET data = ? WHERE id = ?",
            (updated.model_dump_json(), id),
        )
        self._maybe_commit()
        return updated

    def get_tracked_contradiction(self, id: str) -> TrackedTimeContradiction | None:
        row = self._conn.execute(
            "SELECT data FROM tracked_time_contradictions WHERE id = ?", (id,)
        ).fetchone()
        return TrackedTimeContradiction.model_validate_json(row[0]) if row else None

    def list_tracked_contradictions(self) -> list[TrackedTimeContradiction]:
        rows = self._conn.execute(
            "SELECT data FROM tracked_time_contradictions ORDER BY id"
        ).fetchall()
        return [TrackedTimeContradiction.model_validate_json(r[0]) for r in rows]


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
