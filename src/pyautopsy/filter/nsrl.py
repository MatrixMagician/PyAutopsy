"""Read-only NSRL RDSv3 membership probe (FILTER-01, D-36/D-37).

The modern NSRL Reference Data Set is distributed as an RDSv3 **SQLite**
database. We never reimplement it: we open the examiner-supplied DB as a strict
read-only data source and ask, per file, whether one of its hashes is a member.

Three forensic-soundness controls are baked in:

* **Read-only access (T-04-02-DBRO).** The DB is opened with the
  ``file:...?mode=ro`` URI *and* ``PRAGMA query_only=ON``. We NEVER ``ATTACH``
  the file to the case connection and never open it writable — it is untrusted
  input treated as read-only bytes, distinct from ``case.db``.
* **No SQL injection (T-04-02-SQLI).** Hash values flow into the query ONLY via
  ``?`` placeholders — a hash is never string-formatted into SQL. The single
  identifier that is interpolated is the table name, and it is chosen from a
  FIXED ``{FILE, METADATA}`` allowlist discovered from ``sqlite_master`` — never
  taken from arbitrary input.
* **UPPERCASE normalization (T-04-02-CASE, Pitfall 4 — the #1 silent-zero-match
  trap).** RDSv3 stores hash hex values UPPERCASE while the project's own
  ``files`` rows store them lowercase. Every probe value is ``.upper()``-folded
  before comparison, so a known member matches despite the case mismatch.

A match is surfaced as a NEUTRAL ``known`` annotation dict carrying ``source``
and ``matched_on`` only — never a good/bad/malicious/verdict key (D-38). This
module imports no ``pytsk3``/``pyewf`` (D-14): it is pure stdlib ``sqlite3``.
"""

from __future__ import annotations

import sqlite3

__all__ = ["NSRL_TABLE_ALLOWLIST", "nsrl_match", "open_nsrl"]

# The fixed set of NSRL RDSv3 hash-table names we will query. The "minimal"
# variant exposes a ``FILE`` table; the "modern/full" variant exposes
# ``METADATA``. The table name is ONLY ever chosen from this allowlist — it is
# never interpolated from arbitrary user input (T-04-02-SQLI).
NSRL_TABLE_ALLOWLIST: tuple[str, ...] = ("FILE", "METADATA")

# Hash columns probed in NSRL-keying order: md5 → sha1 → sha256 (D-37). NSRL is
# keyed on md5/sha1, so those resolve first; sha256 is the fall-through.
_HASH_COLUMNS: tuple[str, ...] = ("md5", "sha1", "sha256")


def open_nsrl(path: str) -> tuple[sqlite3.Connection, str]:
    """Open an NSRL RDSv3 SQLite DB read-only and discover its hash table.

    Opens ``path`` with the ``?mode=ro`` URI (read-only — the file is never
    written or mounted) and asserts ``PRAGMA query_only=ON`` as defence in depth
    (T-04-02-DBRO). The hash table is then discovered from ``sqlite_master`` and
    chosen from the fixed :data:`NSRL_TABLE_ALLOWLIST` — ``FILE`` (minimal
    variant) is preferred, else ``METADATA`` (modern variant). The table name is
    never taken from arbitrary input.

    Args:
        path: Filesystem path to the examiner-supplied NSRL RDSv3 SQLite DB.

    Returns:
        ``(connection, table_name)`` where ``table_name`` is one of
        :data:`NSRL_TABLE_ALLOWLIST`. The caller owns the connection and must
        ``close()`` it.

    Raises:
        ValueError: If neither an allowlisted ``FILE`` nor ``METADATA`` hash
            table is present, so we refuse to guess a table from outside the
            allowlist.
        sqlite3.Error: If the database cannot be opened read-only.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    # Defence in depth on top of mode=ro: refuse any write attempt at the engine
    # level. The probe is a strictly read-only consumer of untrusted input.
    conn.execute("PRAGMA query_only=ON;")
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    for candidate in NSRL_TABLE_ALLOWLIST:
        if candidate in tables:
            return conn, candidate
    conn.close()
    raise ValueError(
        "no NSRL hash table found: expected one of "
        f"{NSRL_TABLE_ALLOWLIST} in {path!r}"
    )


def nsrl_match(
    conn: sqlite3.Connection,
    table: str,
    *,
    md5: str | None,
    sha1: str | None,
    sha256: str | None,
) -> dict[str, str] | None:
    """Probe NSRL membership for a file's hashes (md5 → sha1 → sha256, D-37).

    For each supplied hash (in NSRL-keying order) the value is ``.upper()``-folded
    to match RDSv3's UPPERCASE storage (Pitfall 4) and looked up with a
    ``?``-parameterized ``SELECT`` — the hash is NEVER string-formatted into SQL
    (T-04-02-SQLI). ``table`` must be an allowlisted name from
    :func:`open_nsrl`; a name outside :data:`NSRL_TABLE_ALLOWLIST` is rejected so
    the interpolated identifier can only ever be ``FILE`` or ``METADATA``.

    Args:
        conn: A read-only connection from :func:`open_nsrl`.
        table: The discovered hash table (``FILE`` or ``METADATA``).
        md5: The file's lowercase MD5 hex, or ``None``.
        sha1: The file's lowercase SHA-1 hex, or ``None``.
        sha256: The file's lowercase SHA-256 hex, or ``None``.

    Returns:
        A NEUTRAL match dict ``{"source": "nsrl", "matched_on": col}`` on the
        first hash found in the set, else ``None``. Carries no good/bad/verdict
        key (D-38).

    Raises:
        ValueError: If ``table`` is not an allowlisted NSRL table name.
    """
    if table not in NSRL_TABLE_ALLOWLIST:
        raise ValueError(
            f"refusing to query non-allowlisted NSRL table {table!r}; "
            f"expected one of {NSRL_TABLE_ALLOWLIST}"
        )
    for col, val in zip(_HASH_COLUMNS, (md5, sha1, sha256), strict=True):
        if not val:
            continue
        # ``table``/``col`` are from fixed allowlists (never user input); the
        # hash flows in ONLY as a ``?`` parameter (T-04-02-SQLI). .upper() folds
        # our lowercase row hash to RDSv3's UPPERCASE storage (Pitfall 4).
        hit = conn.execute(
            f"SELECT 1 FROM {table} WHERE {col} = ? LIMIT 1",  # noqa: S608
            (val.upper(),),
        ).fetchone()
        if hit is not None:
            return {"source": "nsrl", "matched_on": col}
    return None
