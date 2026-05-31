"""The SQLite case store — the single writer abstraction for the case DB.

:class:`CaseStore` is the ONLY sanctioned way to read or write ``case.db`` (no
raw SQL is permitted elsewhere, enforcing the normalized contract — ARCHITECTURE
Pattern 1 / Internal Boundaries). It owns the D-01 case-directory layout, opens
the database WAL with foreign-key enforcement (D-03, PITFALLS P3), runs the
typed-columns + JSON-``attributes`` schema (D-02), and exposes typed repository
methods that round-trip the chain-of-custody models.

All timestamps written here come from :mod:`pyautopsy.util.timeutil` (D-10).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import TracebackType
from typing import Any

import pyautopsy
from pyautopsy.case.models import (
    Case,
    EvidenceSource,
    FileRow,
    TimelineEvent,
    VolumeLimitation,
)
from pyautopsy.util.timeutil import iso_utc

__all__ = ["CaseStore"]

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
_DB_NAME = "case.db"
_SUBDIRS = ("logs", "exports")


def _tool_version() -> str:
    """Return the installed PyAutopsy version for the COC record.

    Prefers installed package metadata; falls back to the in-tree
    ``__version__`` (the single source of truth) when the distribution is not
    installed (e.g. running straight from a source checkout).
    """
    try:
        return version("pyautopsy")
    except PackageNotFoundError:
        return pyautopsy.__version__


class CaseStore:
    """A repository over a case's ``case.db`` (the sole DB writer abstraction)."""

    def __init__(self, case_dir: Path, connection: sqlite3.Connection) -> None:
        """Wrap an already-opened connection. Use :meth:`create` or :meth:`open`.

        Args:
            case_dir: Root directory of the case.
            connection: An open, configured SQLite connection to ``case.db``.
        """
        self.case_dir = case_dir
        self.connection = connection
        # When inside a :meth:`transaction` block, the per-insert methods defer
        # their own ``commit()`` so several writes land atomically (WR-01).
        self._in_transaction = False

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def create(cls, case_dir: Path | str) -> CaseStore:
        """Create the case directory layout and an initialised ``case.db``.

        Builds ``<case_dir>/`` with ``logs/`` and ``exports/`` subdirectories
        (D-01), opens ``case.db`` WAL with foreign keys on, and applies the
        schema.

        Args:
            case_dir: Target case-directory path (created if absent).

        Returns:
            An open :class:`CaseStore`.

        Raises:
            OSError: If the directory layout cannot be created.
        """
        case_dir = Path(case_dir)
        try:
            case_dir.mkdir(parents=True, exist_ok=True)
            for sub in _SUBDIRS:
                (case_dir / sub).mkdir(exist_ok=True)
        except OSError as exc:
            raise OSError(
                f"failed to create case directory layout at {case_dir}: {exc}"
            ) from exc
        conn = cls._connect(case_dir / _DB_NAME)
        try:
            schema = _SCHEMA_PATH.read_text(encoding="utf-8")
            conn.executescript(schema)
            conn.commit()
        except (OSError, sqlite3.Error) as exc:
            conn.close()
            raise RuntimeError(
                f"failed to initialise case schema at {case_dir}: {exc}"
            ) from exc
        return cls(case_dir, conn)

    @classmethod
    def open(cls, case_dir: Path | str) -> CaseStore:
        """Open an existing case directory's ``case.db``.

        Args:
            case_dir: Root directory of an existing case.

        Returns:
            An open :class:`CaseStore`.

        Raises:
            FileNotFoundError: If ``case.db`` does not exist under ``case_dir``.
        """
        case_dir = Path(case_dir)
        db_path = case_dir / _DB_NAME
        if not db_path.is_file():
            raise FileNotFoundError(f"no case database at {db_path}")
        return cls(case_dir, cls._connect(db_path))

    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        """Open a SQLite connection configured WAL + foreign keys (D-03)."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def close(self) -> None:
        """Close the underlying database connection."""
        self.connection.close()

    def __enter__(self) -> CaseStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # -- transactions ------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[CaseStore]:
        """Group several inserts into one atomic unit (WR-01).

        Inside the block, the per-insert methods defer their own ``commit()``;
        the single commit happens once on clean exit. Any exception rolls the
        whole unit back so a partial chain-of-custody record (e.g. an orphaned
        ``cases`` row with no ``evidence_sources`` row) can never be persisted.

        Nesting is not supported and raises :class:`RuntimeError`.

        Yields:
            This :class:`CaseStore`, for convenient ``with store.transaction()``.

        Raises:
            RuntimeError: If a transaction is already active.
        """
        if self._in_transaction:
            raise RuntimeError("CaseStore.transaction() does not support nesting")
        self._in_transaction = True
        try:
            yield self
        except BaseException:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()
        finally:
            self._in_transaction = False

    def _commit_unless_in_transaction(self) -> None:
        """Commit immediately unless a :meth:`transaction` is deferring it."""
        if not self._in_transaction:
            self.connection.commit()

    # -- cases -------------------------------------------------------------

    def insert_case(self, case: Case) -> int:
        """Persist a :class:`Case` and return its new id.

        ``created_utc`` and ``pyautopsy_version`` are assigned here when the
        model leaves them unset, keeping the timestamp source single (D-10).

        Args:
            case: The case to insert.

        Returns:
            The autoincrement id of the inserted row.

        Raises:
            sqlite3.IntegrityError: On a constraint violation.
        """
        created = case.created_utc or iso_utc()
        tool = case.pyautopsy_version or _tool_version()
        cur = self.connection.execute(
            "INSERT INTO cases "
            "(name, examiner, created_utc, pyautopsy_version, notes, "
            "attributes) VALUES (?, ?, ?, ?, ?, ?)",
            (
                case.name,
                case.examiner,
                created,
                tool,
                case.notes,
                json.dumps(case.attributes, sort_keys=True),
            ),
        )
        self._commit_unless_in_transaction()
        if cur.lastrowid is None:
            raise RuntimeError("INSERT INTO cases did not return a row id")
        return cur.lastrowid

    def get_case(self, case_id: int) -> Case:
        """Read a case back by id.

        Args:
            case_id: The case id to look up.

        Returns:
            The reconstructed :class:`Case`.

        Raises:
            LookupError: If no case has the given id.
        """
        row = self.connection.execute(
            "SELECT * FROM cases WHERE id = ?", (case_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no case with id {case_id}")
        return Case(
            name=row["name"],
            examiner=row["examiner"],
            notes=row["notes"],
            created_utc=row["created_utc"],
            pyautopsy_version=row["pyautopsy_version"],
            attributes=_load_attributes(row["attributes"]),
            id=row["id"],
        )

    # -- evidence sources --------------------------------------------------

    def insert_evidence_source(self, source: EvidenceSource) -> int:
        """Persist an :class:`EvidenceSource` and return its new id.

        Args:
            source: The evidence-source record to insert.

        Returns:
            The autoincrement id of the inserted row.

        Raises:
            sqlite3.IntegrityError: On a foreign-key or constraint violation.
        """
        cur = self.connection.execute(
            "INSERT INTO evidence_sources "
            "(case_id, evidence_id, path, image_type, sha256, md5, "
            "byte_size, acquired_utc, tsk_version, attributes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source.case_id,
                source.evidence_id,
                source.path,
                source.image_type,
                source.sha256,
                source.md5,
                source.byte_size,
                source.acquired_utc,
                source.tsk_version,
                json.dumps(source.attributes, sort_keys=True),
            ),
        )
        self._commit_unless_in_transaction()
        if cur.lastrowid is None:
            raise RuntimeError(
                "INSERT INTO evidence_sources did not return a row id"
            )
        return cur.lastrowid

    def get_evidence_source(self, source_id: int) -> EvidenceSource:
        """Read an evidence source back by id.

        Args:
            source_id: The evidence-source id to look up.

        Returns:
            The reconstructed :class:`EvidenceSource`.

        Raises:
            LookupError: If no evidence source has the given id.
        """
        row = self.connection.execute(
            "SELECT * FROM evidence_sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no evidence source with id {source_id}")
        return EvidenceSource(
            case_id=row["case_id"],
            evidence_id=row["evidence_id"],
            path=row["path"],
            image_type=row["image_type"],
            sha256=row["sha256"],
            md5=row["md5"],
            byte_size=row["byte_size"],
            acquired_utc=row["acquired_utc"],
            tsk_version=row["tsk_version"],
            attributes=_load_attributes(row["attributes"]),
            id=row["id"],
        )

    # -- files (walk inventory) -------------------------------------------

    def insert_file(self, file_row: FileRow) -> int:
        """Persist a single :class:`FileRow` and return its new id.

        Args:
            file_row: The inventoried file row to insert.

        Returns:
            The autoincrement id of the inserted row.

        Raises:
            sqlite3.IntegrityError: On a foreign-key or constraint violation.
        """
        cur = self.connection.execute(_FILES_INSERT_SQL, _file_row_params(file_row))
        self._commit_unless_in_transaction()
        if cur.lastrowid is None:
            raise RuntimeError("INSERT INTO files did not return a row id")
        return cur.lastrowid

    def insert_files(self, rows: Iterable[FileRow]) -> int:
        """Bulk-persist many :class:`FileRow` rows in one ``executemany`` (WR-01).

        Like the per-insert methods this still calls
        :meth:`_commit_unless_in_transaction`, so it composes with an outer
        :meth:`transaction` block: the orchestrator opens one transaction and
        every per-volume batch defers its commit to the single outer commit.

        Args:
            rows: The file rows to insert (any iterable; materialised once).

        Returns:
            The number of rows inserted.
        """
        params = [_file_row_params(row) for row in rows]
        if params:
            self.connection.executemany(_FILES_INSERT_SQL, params)
        self._commit_unless_in_transaction()
        return len(params)

    def get_file(self, file_id: int) -> FileRow:
        """Read a file row back by id.

        Args:
            file_id: The file row id to look up.

        Returns:
            The reconstructed :class:`FileRow`.

        Raises:
            LookupError: If no file row has the given id.
        """
        row = self.connection.execute(
            "SELECT * FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no file with id {file_id}")
        return FileRow(
            evidence_source_id=row["evidence_source_id"],
            volume_id=row["volume_id"],
            volume_offset=row["volume_offset"],
            path=row["path"],
            name=row["name"],
            parent_addr=row["parent_addr"],
            meta_addr=row["meta_addr"],
            fs_type=row["fs_type"],
            size=row["size"],
            allocated=None if row["allocated"] is None else bool(row["allocated"]),
            meta_type=row["meta_type"],
            uid=row["uid"],
            gid=row["gid"],
            mode=row["mode"],
            md5=row["md5"],
            sha1=row["sha1"],
            sha256=row["sha256"],
            mtime_utc=row["mtime_utc"],
            atime_utc=row["atime_utc"],
            ctime_utc=row["ctime_utc"],
            crtime_utc=row["crtime_utc"],
            timestamp_source=row["timestamp_source"],
            file_type=row["file_type"],
            recovered=(
                None if row["recovered"] is None else bool(row["recovered"])
            ),
            confidence_tier=row["confidence_tier"],
            recovered_path=row["recovered_path"],
            is_orphan=(
                None if row["is_orphan"] is None else bool(row["is_orphan"])
            ),
            attributes=_load_attributes(row["attributes"]),
            id=row["id"],
        )

    def get_files(self, evidence_source_id: int) -> list[FileRow]:
        """Read every file row for an evidence source, ordered by id.

        Args:
            evidence_source_id: The owning evidence-source id to filter on.

        Returns:
            All matching :class:`FileRow` rows (possibly empty).
        """
        rows = self.connection.execute(
            "SELECT id FROM files WHERE evidence_source_id = ? ORDER BY id",
            (evidence_source_id,),
        ).fetchall()
        return [self.get_file(row["id"]) for row in rows]

    # -- recovered files (RECOV-01/02/03, D-35) ---------------------------

    def insert_recovered_files(self, rows: Iterable[FileRow]) -> int:
        """Bulk-persist recovered :class:`FileRow` rows (RECOV-01, D-35).

        Identical write path to :meth:`insert_files` (same lockstep insert SQL,
        the recovery columns just stop being NULL): one ``executemany`` plus
        :meth:`_commit_unless_in_transaction`, so it composes under the recovery
        orchestrator's outer :meth:`transaction` block (WR-01). CaseStore stays
        the sole DB writer (D-08) — recovered rows never bypass this method.

        Args:
            rows: The recovered file rows to insert (any iterable; materialised
                once).

        Returns:
            The number of rows inserted.
        """
        params = [_file_row_params(row) for row in rows]
        if params:
            self.connection.executemany(_FILES_INSERT_SQL, params)
        self._commit_unless_in_transaction()
        return len(params)

    def get_recovered_files(self, evidence_source_id: int) -> list[FileRow]:
        """Read recovered files for a source in the D-26 total order (RECOV-01).

        Filters to rows the recovery pass wrote (``recovered = 1``) and returns
        them in the store's deterministic D-26 total order so the report's
        "Recovered Files" section is byte-stable across runs (D-41) — the report
        never re-sorts outside the store. Orphan rows are EXCLUDED here so they
        are reported separately via :meth:`get_orphan_files` (RECOV-02/D-25).

        Args:
            evidence_source_id: The owning evidence-source id to filter on.

        Returns:
            The matching recovered :class:`FileRow` rows (possibly empty).
        """
        rows = self.connection.execute(
            "SELECT id FROM files "
            "WHERE evidence_source_id = ? AND recovered = 1 "
            "AND (is_orphan IS NULL OR is_orphan = 0) "
            "ORDER BY mtime_utc, volume_id, volume_offset, path, meta_addr, id",
            (evidence_source_id,),
        ).fetchall()
        return [self.get_file(row["id"]) for row in rows]

    def get_orphan_files(self, evidence_source_id: int) -> list[FileRow]:
        """Read recovered ORPHAN files for a source in the D-26 total order.

        An orphan (parent directory gone) is a provenance fact independent of the
        recovery tier (RECOV-02/D-25): orphans are surfaced in their OWN list, not
        mixed into :meth:`get_recovered_files`. Same deterministic total order so
        the report's "Orphan Files" section is byte-stable (D-41).

        Args:
            evidence_source_id: The owning evidence-source id to filter on.

        Returns:
            The matching orphan :class:`FileRow` rows (possibly empty).
        """
        rows = self.connection.execute(
            "SELECT id FROM files "
            "WHERE evidence_source_id = ? AND recovered = 1 AND is_orphan = 1 "
            "ORDER BY mtime_utc, volume_id, volume_offset, path, meta_addr, id",
            (evidence_source_id,),
        ).fetchall()
        return [self.get_file(row["id"]) for row in rows]

    # -- volume limitations (D-20 findings) -------------------------------

    def insert_volume_limitation(self, limitation: VolumeLimitation) -> int:
        """Persist a :class:`VolumeLimitation` finding and return its new id.

        Args:
            limitation: The D-20 known-limitation finding to record.

        Returns:
            The autoincrement id of the inserted row.

        Raises:
            sqlite3.IntegrityError: On a foreign-key or constraint violation.
        """
        cur = self.connection.execute(
            "INSERT INTO volume_limitations "
            "(evidence_source_id, volume_id, volume_offset, detected_desc, "
            "reason, attributes) VALUES (?, ?, ?, ?, ?, ?)",
            (
                limitation.evidence_source_id,
                limitation.volume_id,
                limitation.volume_offset,
                limitation.detected_desc,
                limitation.reason,
                json.dumps(limitation.attributes, sort_keys=True),
            ),
        )
        self._commit_unless_in_transaction()
        if cur.lastrowid is None:
            raise RuntimeError(
                "INSERT INTO volume_limitations did not return a row id"
            )
        return cur.lastrowid

    def get_volume_limitation(self, limitation_id: int) -> VolumeLimitation:
        """Read a volume-limitation finding back by id.

        Args:
            limitation_id: The finding id to look up.

        Returns:
            The reconstructed :class:`VolumeLimitation`.

        Raises:
            LookupError: If no finding has the given id.
        """
        row = self.connection.execute(
            "SELECT * FROM volume_limitations WHERE id = ?", (limitation_id,)
        ).fetchone()
        if row is None:
            raise LookupError(f"no volume limitation with id {limitation_id}")
        return VolumeLimitation(
            evidence_source_id=row["evidence_source_id"],
            volume_id=row["volume_id"],
            volume_offset=row["volume_offset"],
            detected_desc=row["detected_desc"],
            reason=row["reason"],
            attributes=_load_attributes(row["attributes"]),
            id=row["id"],
        )

    def get_volume_limitations(
        self, evidence_source_id: int
    ) -> list[VolumeLimitation]:
        """Read every limitation finding for an evidence source, ordered by id.

        Args:
            evidence_source_id: The owning evidence-source id to filter on.

        Returns:
            All matching :class:`VolumeLimitation` rows (possibly empty).
        """
        rows = self.connection.execute(
            "SELECT id FROM volume_limitations "
            "WHERE evidence_source_id = ? ORDER BY id",
            (evidence_source_id,),
        ).fetchall()
        return [self.get_volume_limitation(row["id"]) for row in rows]

    # -- timeline events (TIME-01 / D-23/D-24/D-26) -----------------------

    def insert_timeline_events(self, rows: Iterable[TimelineEvent]) -> int:
        """Bulk-persist many :class:`TimelineEvent` rows in one ``executemany``.

        Like :meth:`insert_files` this calls
        :meth:`_commit_unless_in_transaction`, so it composes inside an outer
        :meth:`transaction` block: the timeline producer opens one transaction
        and every batch of exploded events defers its commit to the single
        outer commit (WR-01).

        Args:
            rows: The timeline events to insert (any iterable; materialised
                once).

        Returns:
            The number of rows inserted.
        """
        params = [_timeline_event_params(row) for row in rows]
        if params:
            self.connection.executemany(_TIMELINE_INSERT_SQL, params)
        self._commit_unless_in_transaction()
        return len(params)

    def get_timeline_events(
        self, evidence_source_id: int, *, limit: int | None = None
    ) -> list[TimelineEvent]:
        """Read timeline events for a source in the D-26 total order.

        This is the SINGLE place the timeline read ordering is defined (no raw
        SQL outside the store): ``ts_utc → volume_id → volume_offset → path →
        event_type → meta_addr → source → actor → id``. The first six columns
        are the human-sensible D-26 grouping, but they are NOT a total order:
        two DISTINCT deleted/orphan events can tie on all six when ``meta_addr``
        is NULL (a reclaimed path/volume/ts/event_type collision, CR-01). The
        content-derived ``source`` and ``actor`` columns break most such ties,
        and the surrogate ``id`` is the final guaranteed-unique tiebreak. ``id``
        is a deterministic insertion-order key here because ``build_timeline``
        explodes and inserts events in ``get_files`` id order within one
        transaction (builder.py → store.py:get_files ``ORDER BY id``), so the
        same fixture always assigns the same ``id`` to the same event. THIS
        insertion-order determinism is load-bearing for the byte-identical
        report bodies CLI-02/D-25 require — it replaces the earlier (false)
        claim that the six-column order could never tie.

        Args:
            evidence_source_id: The owning evidence-source id to filter on.
            limit: When given, return only the first ``limit`` events in D-26
                order (the D-27 bounded-HTML slice). ``None`` returns all.

        Returns:
            The matching :class:`TimelineEvent` rows in D-26 total order
            (possibly empty).
        """
        sql = (
            "SELECT * FROM timeline_events WHERE evidence_source_id = ? "
            "ORDER BY ts_utc, volume_id, volume_offset, path, event_type, "
            "meta_addr, source, actor, id"
        )
        params: tuple[Any, ...] = (evidence_source_id,)
        if limit is not None:
            sql += " LIMIT ?"
            params = (evidence_source_id, limit)
        rows = self.connection.execute(sql, params).fetchall()
        return [
            TimelineEvent(
                evidence_source_id=row["evidence_source_id"],
                ts_utc=row["ts_utc"],
                source=row["source"],
                event_type=row["event_type"],
                volume_id=row["volume_id"],
                volume_offset=row["volume_offset"],
                path=row["path"],
                meta_addr=row["meta_addr"],
                actor=row["actor"],
                action=row["action"],
                outcome=row["outcome"],
                file_id=row["file_id"],
                attributes=_load_attributes(row["attributes"]),
                id=row["id"],
            )
            for row in rows
        ]


# The ``files`` insert column order, used by both insert_file and the bulk
# insert_files ``executemany`` so the single SQL statement and the parameter
# tuple stay in lockstep.
_FILES_COLUMNS: tuple[str, ...] = (
    "evidence_source_id",
    "volume_id",
    "volume_offset",
    "path",
    "name",
    "parent_addr",
    "meta_addr",
    "fs_type",
    "size",
    "allocated",
    "meta_type",
    "uid",
    "gid",
    "mode",
    "md5",
    "sha1",
    "sha256",
    "mtime_utc",
    "atime_utc",
    "ctime_utc",
    "crtime_utc",
    "timestamp_source",
    "file_type",
    "recovered",
    "confidence_tier",
    "recovered_path",
    "is_orphan",
    "attributes",
)

_FILES_INSERT_SQL = (
    "INSERT INTO files ("
    + ", ".join(_FILES_COLUMNS)
    + ") VALUES ("
    + ", ".join("?" for _ in _FILES_COLUMNS)
    + ")"
)


def _file_row_params(file_row: FileRow) -> tuple[Any, ...]:
    """Flatten a :class:`FileRow` into the :data:`_FILES_COLUMNS` insert tuple."""
    return (
        file_row.evidence_source_id,
        file_row.volume_id,
        file_row.volume_offset,
        file_row.path,
        file_row.name,
        file_row.parent_addr,
        file_row.meta_addr,
        file_row.fs_type,
        file_row.size,
        None if file_row.allocated is None else int(file_row.allocated),
        file_row.meta_type,
        file_row.uid,
        file_row.gid,
        file_row.mode,
        file_row.md5,
        file_row.sha1,
        file_row.sha256,
        file_row.mtime_utc,
        file_row.atime_utc,
        file_row.ctime_utc,
        file_row.crtime_utc,
        file_row.timestamp_source,
        file_row.file_type,
        None if file_row.recovered is None else int(file_row.recovered),
        file_row.confidence_tier,
        file_row.recovered_path,
        None if file_row.is_orphan is None else int(file_row.is_orphan),
        json.dumps(file_row.attributes, sort_keys=True),
    )


# The ``timeline_events`` insert column order, kept in lockstep with
# :func:`_timeline_event_params` exactly like ``files`` (WR-01).
_TIMELINE_COLUMNS: tuple[str, ...] = (
    "evidence_source_id",
    "file_id",
    "ts_utc",
    "source",
    "event_type",
    "volume_id",
    "volume_offset",
    "path",
    "meta_addr",
    "actor",
    "action",
    "outcome",
    "attributes",
)

_TIMELINE_INSERT_SQL = (
    "INSERT INTO timeline_events ("
    + ", ".join(_TIMELINE_COLUMNS)
    + ") VALUES ("
    + ", ".join("?" for _ in _TIMELINE_COLUMNS)
    + ")"
)


def _timeline_event_params(event: TimelineEvent) -> tuple[Any, ...]:
    """Flatten a :class:`TimelineEvent` into the :data:`_TIMELINE_COLUMNS` tuple."""
    return (
        event.evidence_source_id,
        event.file_id,
        event.ts_utc,
        event.source,
        event.event_type,
        event.volume_id,
        event.volume_offset,
        event.path,
        event.meta_addr,
        event.actor,
        event.action,
        event.outcome,
        json.dumps(event.attributes, sort_keys=True),
    )


def _load_attributes(raw: str | None) -> dict[str, Any]:
    """Deserialise a JSON ``attributes`` column to a dict (empty when null)."""
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"corrupt attributes JSON in case store: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("attributes column must deserialise to a JSON object")
    return loaded
