"""Streaming content / IOC / known-bad-hash search orchestrator (SEARCH-01/02).

:func:`run_search` is the search vertical slice's coordinator (D-49). It composes
two arms over one evidence source, both read-only and streaming (PERF-01):

* **content arm** (SEARCH-01) — literal/regex terms (and IOC terms) streamed over
  every volume's allocated file content and unallocated space via
  :mod:`pyautopsy.search.content` (which goes through the byte + FS seams; the
  novel unallocated read uses the new ``iter_unallocated_blocks`` seam). Each hit
  is a :class:`~pyautopsy.case.SearchHit` reported by file + absolute byte offset,
  including boundary-spanning matches (Pitfall 5).
* **hash arm** (SEARCH-02) — known-bad-hash matching over ``get_files`` rows,
  reusing the Phase-4 ``filter/hashsets`` matcher (:mod:`pyautopsy.search.ioc`).
  Each hit is recorded BOTH as a NEUTRAL :class:`~pyautopsy.case.KnownMatch`
  (FILTER-01 precedent, D-38) and as a ``term_kind="hash"`` ``SearchHit`` so the
  examiner sees it by file in the unified search results.

All rows are written through :class:`~pyautopsy.case.CaseStore` inside ONE
transaction (the store stays the sole DB writer and owns hit ordering, D-08/D-41);
this module never re-sorts. It re-asserts the not-mounted read-only guard before
AND after opening the image (D-42/P1). It imports no native binding (D-14): the
content scanner and the seams own all byte access. A bad regex / non-UTF-8 IOC
list is a clean :class:`SearchError` (operator error), never a ``.crashed`` bug
(T-05-03-05).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pyautopsy.audit import AuditLog
from pyautopsy.case import CaseStore, KnownMatch, SearchHit
from pyautopsy.core.epilogue import audited_step
from pyautopsy.errors import PyAutopsyError
from pyautopsy.evidence import integrity
from pyautopsy.search import content as content_mod
from pyautopsy.search import ioc as ioc_mod

__all__ = ["SearchError", "SearchResult", "run_search"]


class SearchError(PyAutopsyError):
    """Raised when search cannot proceed for a non-integrity reason.

    Chiefly: the case has no ``case.db`` (ingest was never run) or no evidence
    source; a bad examiner regex; or a non-UTF-8 IOC list. Surfaced as a clean
    ``search.error`` FAIL + non-zero exit, never a ``.crashed`` bug.
    """


@dataclass(frozen=True, slots=True)
class SearchResult:
    """The reproducible outcome of a search run (no wall-clock).

    Carries only analytical counts so the CLI prints a deterministic summary and
    the reproducibility tests can compare two runs (D-41).

    Attributes:
        evidence_source_id: The evidence source the hits attached to.
        hits: Total :class:`SearchHit` rows written (content + hash).
        unallocated_hits: How many of those hits were in unallocated space.
        hash_hits: How many known-bad-hash hits were recorded.
    """

    evidence_source_id: int
    hits: int
    unallocated_hits: int
    hash_hits: int




def _latest_evidence_source_id(store: CaseStore) -> int:
    """Return the latest ``evidence_sources`` id, or raise :class:`SearchError`.

    Reads through the CaseStore (WR-02: no raw SQL outside the store boundary).
    """
    source_id = store.get_latest_evidence_source_id()
    if source_id is None:
        raise SearchError(
            "no evidence source in the case; run `pyautopsy ingest` first so "
            "search has an image + inventory to scan"
        )
    return source_id


def _read_ioc_file(path: Path) -> list[bytes]:
    """Read + parse an IOC list, re-raising a non-UTF-8 file as SearchError."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # Mirror knownfiles.py: operator bad input → clean SearchError (a clean
        # search.error + handled exit), never a .crashed programming-bug record.
        raise SearchError(
            f"IOC list {path} is not valid UTF-8 text (binary or wrong "
            f"encoding?): {exc}"
        ) from exc
    return ioc_mod.parse_ioc_terms(text)


def run_search(
    image: str | Path,
    case_dir: str | Path,
    *,
    terms: Sequence[bytes] = (),
    regexes: Sequence[bytes] = (),
    ioc_terms: Sequence[bytes] = (),
    ioc_file: str | Path | None = None,
    bad_hashes: Iterable[str] = (),
    evidence_source_id: int | None = None,
) -> SearchResult:
    """Run the streaming content + IOC + known-bad-hash search over one source.

    Args:
        image: Path to the evidence image (raw/dd or first E01 segment).
        case_dir: The case directory containing ``case.db`` (ingest made it).
        terms: Literal byte needles (``term_kind="literal"``).
        regexes: Regex byte sources (``term_kind="regex"``; ReDoS-bounded).
        ioc_terms: IOC literal terms supplied directly (``term_kind="ioc"``).
        ioc_file: Optional IOC list file; its terms are parsed + scanned as IOC.
        bad_hashes: Known-bad hash hex strings (any algorithm/case) matched
            against the inventory's ``files`` rows.
        evidence_source_id: The source to search; defaults to the latest one.

    Returns:
        A :class:`SearchResult` with reproducible counts (no wall-clock).

    Raises:
        SearchError: No ``case.db`` / no source / bad regex / non-UTF-8 IOC list.
        MountedSourceError: If the source path is a mounted filesystem (P1).
        ImageOpenError: If the image cannot be opened read-only.
    """
    image_path = Path(image).resolve()
    case_path = Path(case_dir).resolve()

    # Bind the audit log BEFORE the first guard so a pre-open mounted-source
    # rejection is recorded as a FAIL event (WR-03), honoring the D-08 "record
    # FAIL before non-zero exit" contract. ``run_search`` requires a prior ingest,
    # so the case dir already exists; AuditLog creates the journal lazily on write.
    # The audit log lives inside the case directory, so a case that does not
    # exist has nowhere to record a FAIL event. Check for it BEFORE binding the
    # log, otherwise the audit write's own OSError masks this actionable message
    # with a raw traceback (``run_search`` requires a prior ingest).
    if not CaseStore.exists(case_path):
        raise SearchError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        )

    audit = AuditLog(case_path)

    # (1) Re-assert the read-only / not-mounted guard before any access (D-42/P1).
    #     Audited: a mounted source is a FAIL event, not a silent clean exit.
    try:
        integrity.assert_source_not_mounted(image_path)
    except integrity.MountedSourceError as exc:
        audit.write(
            "search.error",
            outcome="FAIL",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise

    # (2) Open the existing case store (ingest created it).
    try:
        store = CaseStore.open(case_path)
    except FileNotFoundError as exc:
        audit.write(
            "search.error",
            outcome="FAIL",
            error=str(exc),
            error_type="SearchError",
        )
        raise SearchError(
            f"no case database under {case_path}; run `pyautopsy ingest` first"
        ) from exc

    # Resolve IOC-file terms up front so a bad list fails before any image read.
    ioc_all: list[bytes] = list(ioc_terms)
    if ioc_file is not None:
        ioc_all.extend(_read_ioc_file(Path(ioc_file)))

    bad_set = ioc_mod.build_bad_hash_set(bad_hashes)

    audit.write(
        "search.start",
        image=str(image_path),
        case_dir=str(case_path),
        literal_terms=len(terms),
        regex_terms=len(regexes),
        ioc_terms=len(ioc_all),
        bad_hash_count=sum(len(s) for s in bad_set.values()),
    )

    hits: list[SearchHit] = []
    matches: list[KnownMatch] = []
    unallocated_hits = 0
    hash_hits = 0

    with audited_step(audit, store, "search", SearchError):
        source_id = (
            evidence_source_id
            if evidence_source_id is not None
            else _latest_evidence_source_id(store)
        )

        # -- content arm (SEARCH-01): literal/regex/ioc over the image --------
        # The scanner compiles regexes with the ReDoS bound; a bad regex raises
        # SearchPatternError (a ValueError) which we map to a clean SearchError so
        # it is recorded as a handled search.error, never a .crashed bug.
        try:
            if terms or regexes:
                hits.extend(
                    content_mod.search_image(
                        str(image_path),
                        terms=terms,
                        regexes=regexes,
                        term_kind="literal",
                        evidence_source_id=source_id,
                    )
                )
            if ioc_all:
                hits.extend(
                    content_mod.search_image(
                        str(image_path),
                        terms=ioc_all,
                        term_kind="ioc",
                        evidence_source_id=source_id,
                    )
                )
        except content_mod.SearchPatternError as exc:
            raise SearchError(str(exc)) from exc

        # (D-42/P1) Re-assert not-mounted after the image was opened + read.
        integrity.assert_source_not_mounted(image_path)

        unallocated_hits = sum(1 for h in hits if h.region == "unallocated")

        # -- hash arm (SEARCH-02): known-bad-hash over the inventory ----------
        has_bad = any(bad_set.values())
        if has_bad:
            files = store.get_files(source_id)
            matches = ioc_mod.match_bad_hashes(files, bad_set)
            # Each known-bad-hash match is ALSO surfaced as a term_kind="hash"
            # SearchHit so the examiner sees it by file in the unified results.
            file_by_id = {f.id: f for f in files}
            for m in matches:
                fr = file_by_id.get(m.file_id)
                matched_hex = getattr(fr, m.matched_on) if fr is not None else None
                hits.append(
                    SearchHit(
                        evidence_source_id=source_id,
                        region="metadata",
                        term=(matched_hex or m.matched_on).encode("latin-1"),
                        term_kind="hash",
                        volume_id=fr.volume_id if fr is not None else 0,
                        volume_offset=fr.volume_offset if fr is not None else 0,
                        byte_offset=None,
                        file_id=m.file_id,
                        path=fr.path if fr is not None else None,
                        block_index=None,
                        context=None,
                        attributes={"list": m.list_name, "matched_on": m.matched_on},
                    )
                )
            hash_hits = len(matches)

        with store.transaction():
            store.insert_search_hits(hits)
            store.insert_known_matches(matches)

        audit.write(
            "search.end",
            outcome="SUCCESS",
            evidence_source_id=source_id,
            hits=len(hits),
            unallocated_hits=unallocated_hits,
            hash_hits=hash_hits,
        )

    return SearchResult(
        evidence_source_id=source_id,
        hits=len(hits),
        unallocated_hits=unallocated_hits,
        hash_hits=hash_hits,
    )
