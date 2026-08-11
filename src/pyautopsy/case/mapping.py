"""Derive each model's column mapping from its dataclass definition.

``CaseStore`` used to state every column name three times — in the dataclass
that models the row, in the ``INSERT`` parameter tuple, and in the
``SELECT``-to-dataclass constructor. A schema change meant editing three places
in lockstep with nothing to catch a miss.

Every model's field names match its table's column names exactly, so the
mapping is derived from the dataclass and each field is named once.

**What is not generic.** Three columns need real conversion, and they keep
explicit, individually tested treatment rather than being coerced by type
sniffing:

* ``attributes`` — a JSON object column, serialised with ``sort_keys=True`` so
  two runs of the same data produce byte-identical SQL parameters (D-25).
* ``allocated`` / ``recovered`` / ``is_orphan`` — nullable booleans stored as
  integers. ``None`` (unknown) must stay distinguishable from ``False``
  (known-not-allocated): a deleted entry and an entry whose allocation state
  could not be determined are different forensic statements.
* ``term`` — raw ``bytes`` round-tripped through latin-1, so a non-UTF-8 search
  needle survives storage byte-for-byte.

A mismatch between a dataclass and its table fails loudly at import time rather
than silently dropping a column (see :func:`validate_mapping`).
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:  # pragma: no cover - typing only
    from _typeshed import DataclassInstance

# ``ColumnCodec`` stays exported: it is the type of the per-column conversions
# a future column would have to declare, so it is part of how this module is
# extended.
__all__ = [
    "ColumnCodec",
    "RowMapper",
    "validate_mapping",
]

T = TypeVar("T", bound="DataclassInstance")


@dataclasses.dataclass(frozen=True, slots=True)
class ColumnCodec:
    """How one column converts between its Python value and its stored value.

    Attributes:
        to_db: Python value -> SQLite value.
        from_db: SQLite value -> Python value.
    """

    to_db: Callable[[Any], Any]
    from_db: Callable[[Any], Any]


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


# ``sort_keys=True`` is load-bearing, not tidiness: it keeps the serialised JSON
# byte-identical for equal data, which the reproducibility guarantee rests on.
ATTRIBUTES_CODEC = ColumnCodec(
    to_db=lambda value: json.dumps(value, sort_keys=True),
    from_db=_load_attributes,
)

# A nullable boolean stored as an integer. ``None`` must survive as ``None``:
# "not allocated" and "allocation state unknown" are different claims about the
# evidence, and collapsing them would make the inventory assert something it
# does not know.
NULLABLE_BOOL_CODEC = ColumnCodec(
    to_db=lambda value: None if value is None else int(value),
    from_db=lambda value: None if value is None else bool(value),
)

# Raw bytes round-tripped through latin-1 (a total, byte-preserving codec), so a
# non-UTF-8 search needle is stored and returned byte-for-byte.
BYTES_CODEC = ColumnCodec(
    to_db=lambda value: value.decode("latin-1"),
    from_db=lambda value: value.encode("latin-1"),
)

# Columns needing conversion, by field name. Everything else passes through
# untouched — SQLite's own types already match.
_CODECS: dict[str, ColumnCodec] = {
    "attributes": ATTRIBUTES_CODEC,
    "allocated": NULLABLE_BOOL_CODEC,
    "recovered": NULLABLE_BOOL_CODEC,
    "is_orphan": NULLABLE_BOOL_CODEC,
    "term": BYTES_CODEC,
}


class RowMapper(Generic[T]):
    """Maps one dataclass to and from its table, deriving the column names.

    Args:
        model: The dataclass modelling one row.
        table: The table name.
        skip_on_insert: Fields the database assigns rather than the caller —
            the surrogate ``id``. Excluded from the INSERT so SQLite assigns it.
    """

    __slots__ = ("_columns", "_model", "_table", "insert_sql")

    def __init__(
        self,
        model: type[T],
        table: str,
        *,
        skip_on_insert: tuple[str, ...] = ("id",),
    ) -> None:
        self._model = model
        self._table = table
        self._columns = tuple(
            f.name for f in dataclasses.fields(model) if f.name not in skip_on_insert
        )
        self.insert_sql = (
            f"INSERT INTO {table} ("
            + ", ".join(self._columns)
            + ") VALUES ("
            + ", ".join("?" for _ in self._columns)
            + ")"
        )

    @property
    def columns(self) -> tuple[str, ...]:
        """The INSERT column order, derived from the dataclass field order."""
        return self._columns

    @property
    def model(self) -> type[T]:
        """The dataclass this mapper derives its columns from."""
        return self._model

    @property
    def table(self) -> str:
        """The table this mapper reads and writes."""
        return self._table

    def to_params(self, row: T) -> tuple[Any, ...]:
        """Flatten a model instance into its INSERT parameter tuple."""
        return tuple(
            _CODECS[name].to_db(getattr(row, name))
            if name in _CODECS
            else getattr(row, name)
            for name in self._columns
        )

    def from_row(self, row: sqlite3.Row) -> T:
        """Rebuild a model instance from a ``SELECT *`` row."""
        values: dict[str, Any] = {}
        for field in dataclasses.fields(self._model):
            raw = row[field.name]
            codec = _CODECS.get(field.name)
            values[field.name] = codec.from_db(raw) if codec else raw
        return self._model(**values)


def validate_mapping(mapper: RowMapper[Any], connection: sqlite3.Connection) -> None:
    """Assert a model's fields and its table's columns agree exactly.

    Called once at store-open so a schema/dataclass drift fails loudly at the
    seam, rather than silently dropping a column: a field with no column would
    raise deep inside an INSERT, and a column with no field would be quietly
    omitted from every row the store returns.

    Args:
        mapper: The mapper to check.
        connection: An open connection to a database carrying the schema.

    Raises:
        ValueError: If the model and the table disagree on any name.
    """
    table_columns = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({mapper.table})")
    }
    if not table_columns:
        raise ValueError(f"case database has no table {mapper.table!r}")

    field_names = {f.name for f in dataclasses.fields(mapper.model)}
    missing_columns = field_names - table_columns
    missing_fields = table_columns - field_names
    if missing_columns or missing_fields:
        raise ValueError(
            f"case-store mapping drift for {mapper.table!r}: "
            f"fields with no column {sorted(missing_columns)}, "
            f"columns with no field {sorted(missing_fields)}"
        )
