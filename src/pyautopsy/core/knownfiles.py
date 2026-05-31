"""Known-file filtering orchestrator — the post-walk noise-reduction pass.

:func:`run_filter` is the FILTER-01 vertical slice's coordinator (D-39). It runs
AFTER the walk (and, when present, recovery), reading every ``files`` row for an
evidence source — allocated AND recovered alike — and, for each row that carries
hashes, asking two neutral membership questions:

* is this hash in the examiner-supplied **NSRL RDS**? (via
  :func:`pyautopsy.filter.nsrl.open_nsrl` + :func:`~pyautopsy.filter.nsrl.nsrl_match`)
* is it in any supplied **custom allow/block list**? (via
  :func:`pyautopsy.filter.hashsets.parse_hash_set` +
  :func:`~pyautopsy.filter.hashsets.custom_match`)

Every match becomes a NEUTRAL :class:`~pyautopsy.case.KnownMatch` annotation —
source + list + sense + matched_on, never a good/bad/clean/malicious verdict
(D-38) — written through :class:`~pyautopsy.case.CaseStore` inside ONE
transaction (the store stays the sole DB writer, D-08/D-39). Ordering is owned
by the store's :meth:`~pyautopsy.case.CaseStore.get_known_matches` total order;
this module never re-sorts (D-41).

This module imports no ``pytsk3``/``pyewf`` (D-14): filtering is stdlib
``sqlite3`` (the read-only external NSRL DB) + text parsing. The only DB it
mutates is the case ``case.db``, and only via :class:`CaseStore`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore, KnownMatch
from pyautopsy.filter import hashsets, nsrl

__all__ = ["FilterError", "FilterResult", "run_filter"]


class FilterError(Exception):
    """Raised when filtering cannot proceed for a non-integrity reason.

    Chiefly: the case directory has no ``case.db`` (ingest/walk was never run) or
    no evidence source to filter. A malformed/unopenable NSRL DB surfaces as the
    underlying :class:`sqlite3.Error` (recorded as ``filter.error``).
    """


@dataclass(frozen=True, slots=True)
class FilterResult:
    """The reproducible outcome of a filtering run (no wall-clock).

    Carries only analytical counts so the CLI prints a deterministic summary and
    the reproducibility test can compare two runs (D-41).

    Attributes:
        evidence_source_id: The evidence source the annotations attached to.
        files_matched: How many distinct ``files`` rows matched at least once.
        nsrl_matches: Total NSRL match annotations written.
        custom_matches: Total custom-list match annotations written.
    """

    evidence_source_id: int
    files_matched: int
    nsrl_matches: int
    custom_matches: int


# The operational exception set filtering legitimately expects (mirrors
# recover._EXPECTED_RECOVER_ERRORS). Recorded as a ``filter.error`` FAIL and
# re-raised; anything OUTSIDE this set is a genuine bug recorded under
# ``filter.crashed``.
_EXPECTED_FILTER_ERRORS: tuple[type[BaseException], ...] = (
    FilterError,
    OSError,
    sqlite3.Error,
)


def _latest_evidence_source_id(store: CaseStore) -> int:
    """Return the latest ``evidence_sources`` id, or raise :class:`FilterError`.

    Reads through the CaseStore (WR-02: no raw SQL outside the store boundary).
    """
    source_id = store.get_latest_evidence_source_id()
    if source_id is None:
        raise FilterError(
            "no evidence source in the case; run `pyautopsy ingest` + `walk` "
            "first so filtering has an inventory to filter"
        )
    return source_id


def run_filter(
    case_dir: str | Path,
    *,
    nsrl_db: str | Path | None = None,
    hash_sets: Sequence[tuple[str | Path, str]] = (),
    evidence_source_id: int | None = None,
) -> FilterResult:
    """Run the post-walk known-file filtering pass over one evidence source.

    Reads every ``files`` row for the source in :meth:`CaseStore.get_files` id
    order (allocated + recovered), and for each row with hashes probes the NSRL
    RDS (when ``nsrl_db`` is supplied) then each custom list, collecting a
    NEUTRAL :class:`KnownMatch` per hit and writing them all via
    :meth:`CaseStore.insert_known_matches` inside ONE transaction. The store owns
    ordering (D-41); this never re-sorts.

    Args:
        case_dir: The case directory containing ``case.db`` (ingest/walk made it).
        nsrl_db: Path to an examiner-supplied NSRL RDSv3 SQLite DB, opened
            read-only; ``None`` skips NSRL filtering.
        hash_sets: ``(path, sense)`` pairs for custom lists, where ``sense`` is
            ``"allow"`` or ``"block"``. The list name surfaced in the report is
            the path's filename stem.
        evidence_source_id: The source to filter; defaults to the latest one.

    Returns:
        A :class:`FilterResult` with reproducible match counts (no wall-clock).

    Raises:
        FilterError: If the case has no ``case.db`` or no evidence source.
        sqlite3.Error: If the NSRL DB cannot be opened/queried read-only.
    """
    case_path = Path(case_dir).resolve()

    try:
        store = CaseStore.open(case_path)
    except FileNotFoundError as exc:
        raise FilterError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        ) from exc

    # WR-03: resolve the NSRL path ONCE and use the same resolved path for both
    # the audit record and the open_nsrl call, so the chain-of-custody audit
    # trail can never name a different file than the one actually queried (a CWD
    # divergence would otherwise let the audited and opened paths drift apart).
    nsrl_path = Path(nsrl_db).resolve() if nsrl_db is not None else None

    audit = AuditLog(case_path)
    audit.write(
        "filter.start",
        case_dir=str(case_path),
        nsrl_db=str(nsrl_path) if nsrl_path is not None else None,
        hash_set_count=len(hash_sets),
    )

    nsrl_matches = 0
    custom_matches = 0
    matched_file_ids: set[int] = set()

    try:
        source_id = (
            evidence_source_id
            if evidence_source_id is not None
            else _latest_evidence_source_id(store)
        )

        # Parse each custom list once: (list_name, sense, parsed-sets).
        parsed_lists: list[tuple[str, str, dict[str, set[str]]]] = []
        for raw_path, sense in hash_sets:
            list_path = Path(raw_path)
            # WR-01: a binary / non-UTF-8 custom list makes read_text raise
            # UnicodeDecodeError (a ValueError subclass) which is NOT in
            # _EXPECTED_FILTER_ERRORS, so it would be mis-recorded as a
            # filter.crashed "programming bug". It is actually operator bad
            # input — convert it to a FilterError naming the offending list so
            # it surfaces as a clean filter.error + handled exit.
            try:
                list_text = list_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise FilterError(
                    f"hash-set list {list_path} is not valid UTF-8 text "
                    f"(binary or wrong encoding?): {exc}"
                ) from exc
            parsed = hashsets.parse_hash_set(list_text)
            parsed_lists.append((list_path.stem, sense, parsed))

        # Open the NSRL DB once (read-only), reused for every probe.
        nsrl_conn: sqlite3.Connection | None = None
        nsrl_table = ""
        if nsrl_path is not None:
            nsrl_conn, nsrl_table = nsrl.open_nsrl(str(nsrl_path))

        matches: list[KnownMatch] = []
        try:
            # get_files yields allocated + recovered rows in id order (D-39); we
            # never re-sort — the store owns the read order (D-41).
            for file_row in store.get_files(source_id):
                if file_row.id is None:
                    continue
                if not (file_row.md5 or file_row.sha1 or file_row.sha256):
                    continue

                if nsrl_conn is not None:
                    nsrl_hit = nsrl.nsrl_match(
                        nsrl_conn,
                        nsrl_table,
                        md5=file_row.md5,
                        sha1=file_row.sha1,
                        sha256=file_row.sha256,
                    )
                    if nsrl_hit is not None:
                        matches.append(
                            KnownMatch(
                                file_id=file_row.id,
                                source="nsrl",
                                matched_on=nsrl_hit["matched_on"],
                            )
                        )
                        nsrl_matches += 1
                        matched_file_ids.add(file_row.id)

                for list_name, sense, parsed in parsed_lists:
                    custom_hit = hashsets.custom_match(
                        parsed,
                        sense,
                        list_name,
                        md5=file_row.md5,
                        sha1=file_row.sha1,
                        sha256=file_row.sha256,
                    )
                    if custom_hit is not None:
                        matches.append(
                            KnownMatch(
                                file_id=file_row.id,
                                source="custom",
                                matched_on=custom_hit["matched_on"],
                                list_name=list_name,
                                sense=sense,
                            )
                        )
                        custom_matches += 1
                        matched_file_ids.add(file_row.id)
        finally:
            if nsrl_conn is not None:
                nsrl_conn.close()

        with store.transaction():
            store.insert_known_matches(matches)

        audit.write(
            "filter.end",
            outcome="SUCCESS",
            evidence_source_id=source_id,
            files_matched=len(matched_file_ids),
            nsrl_matches=nsrl_matches,
            custom_matches=custom_matches,
        )
    except _EXPECTED_FILTER_ERRORS as exc:
        audit.write(
            "filter.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    except Exception as exc:
        audit.write(
            "filter.crashed",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    finally:
        store.close()

    return FilterResult(
        evidence_source_id=source_id,
        files_matched=len(matched_file_ids),
        nsrl_matches=nsrl_matches,
        custom_matches=custom_matches,
    )
