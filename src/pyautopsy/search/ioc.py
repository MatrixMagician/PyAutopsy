"""SEARCH-02 IOC-term + known-bad-hash matching (D-49, reuses filter/*).

Two arms, both reusing the Phase-4 ``filter`` infrastructure so search adds NO
new runtime dependency (D-43) and NO new matching logic to maintain:

* **IOC terms** — a tolerant newline-delimited indicator list (a sibling of
  :func:`pyautopsy.filter.hashsets.parse_hash_set`: ``#``-comments and blank
  lines skipped) whose terms are fed to the SEARCH-01 content scanner as
  ``term_kind="ioc"`` literals, so an IOC hit is reported by file + byte offset.
* **Known-bad hashes** — goes through the shared known-hash path in
  :mod:`pyautopsy.filter.hashsets` (parse → probe → neutral record) against the
  ``files`` rows' hashes, recording each hit as a NEUTRAL
  :class:`~pyautopsy.case.KnownMatch` (FILTER-01 precedent, D-38).

This module imports no native binding (D-14): pure stdlib text parsing plus the
stdlib-only ``filter`` modules.
"""

from __future__ import annotations

from collections.abc import Iterable

from pyautopsy.case.models import FileRow, KnownMatch
from pyautopsy.filter import hashsets

__all__ = ["match_bad_hashes", "parse_ioc_terms"]


def parse_ioc_terms(text: str) -> list[bytes]:
    """Parse a tolerant newline-delimited IOC list into literal byte terms.

    A sibling of :func:`pyautopsy.filter.hashsets.parse_hash_set`: ``#`` comment
    lines and blank lines are skipped; every other line is taken verbatim (after
    stripping the trailing newline only) as one indicator. Terms are returned as
    ``bytes`` (UTF-8 encoded) so they feed the byte-oriented content scanner; a
    term's exact bytes are what the scanner matches.

    Args:
        text: The raw IOC-list text.

    Returns:
        The parsed indicator terms as ``bytes``, in file order, de-duplicated
        while preserving first-seen order (deterministic).
    """
    seen: set[bytes] = set()
    terms: list[bytes] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        term = line.encode("utf-8")
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def match_bad_hashes(
    files: Iterable[FileRow],
    bad: hashsets.HashSet,
    *,
    list_name: str = "known-bad",
) -> list[KnownMatch]:
    """Match ``files`` rows against a known-bad-hash set.

    Probes each file row's hashes through the shared
    :func:`pyautopsy.filter.hashsets.probe_hash_set` and records a hit through
    the shared :func:`~pyautopsy.filter.hashsets.to_known_match`, with sense
    ``"block"`` — the provenance of a known-bad list, never a verdict (D-38).

    Args:
        files: The ``files`` rows to probe (e.g. ``store.get_files(...)``).
        bad: A :func:`pyautopsy.filter.hashsets.parse_hash_set` result.
        list_name: The display name recorded on each match.

    Returns:
        One :class:`KnownMatch` per matched file (in input order).
    """
    matches: list[KnownMatch] = []
    for row in files:
        if row.id is None:
            continue
        if not (row.md5 or row.sha1 or row.sha256):
            continue
        matched_on = hashsets.probe_hash_set(
            bad, md5=row.md5, sha1=row.sha1, sha256=row.sha256
        )
        if matched_on is not None:
            matches.append(
                hashsets.to_known_match(
                    row.id, matched_on, list_name=list_name, sense="block"
                )
            )
    return matches
