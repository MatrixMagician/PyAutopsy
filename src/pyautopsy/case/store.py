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
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import TracebackType
from typing import Any

import pyautopsy
from pyautopsy.case.models import Case, EvidenceSource
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
        try:
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
            self.connection.commit()
        except sqlite3.IntegrityError:
            raise
        assert cur.lastrowid is not None
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
        try:
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
            self.connection.commit()
        except sqlite3.IntegrityError:
            raise
        assert cur.lastrowid is not None
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
