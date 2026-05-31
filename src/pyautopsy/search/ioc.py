"""SEARCH-02 IOC-term + known-bad-hash matching (D-49, reuses filter/*).

Two arms, both reusing the Phase-4 ``filter`` infrastructure so search adds NO
new runtime dependency (D-43) and NO new matching logic to maintain:

* **IOC terms** — a tolerant newline-delimited indicator list (a sibling of
  :func:`pyautopsy.filter.hashsets.parse_hash_set`: ``#``-comments and blank
  lines skipped) whose terms are fed to the SEARCH-01 content scanner as
  ``term_kind="ioc"`` literals, so an IOC hit is reported by file + byte offset.
* **Known-bad hashes** — reuses :func:`pyautopsy.filter.hashsets.parse_hash_set`
  / :func:`~pyautopsy.filter.hashsets.custom_match` (and, when an NSRL DB is
  supplied, :func:`pyautopsy.filter.nsrl.nsrl_match`) verbatim against the
  ``files`` rows' hashes, recording each hit as a NEUTRAL
  :class:`~pyautopsy.case.KnownMatch` (FILTER-01 precedent, D-38).

This module imports no native binding (D-14): pure stdlib text parsing plus the
stdlib-only ``filter`` modules.
"""

from __future__ import annotations

from collections.abc import Iterable

from pyautopsy.case.models import FileRow, KnownMatch
from pyautopsy.filter import hashsets

__all__ = ["build_bad_hash_set", "match_bad_hashes", "parse_ioc_terms"]


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


def build_bad_hash_set(bad_hashes: Iterable[str]) -> dict[str, set[str]]:
    """Build a :func:`parse_hash_set`-shaped dict from raw known-bad hashes.

    Lets the known-bad-hash arm reuse :func:`pyautopsy.filter.hashsets.custom_match`
    verbatim: each hash is routed to the md5/sha1/sha256 set by its hex LENGTH
    (the same length→algo inference the filter parser uses), lowercase-normalized,
    and hex-validated (an unrecognised-length or non-hex entry is skipped rather
    than aborting the set).

    Args:
        bad_hashes: Raw known-bad hash hex strings (any algorithm/case).

    Returns:
        ``{"md5": set, "sha1": set, "sha256": set}`` of lowercase hex digests.
    """
    # Reuse the filter parser by feeding one hash per line — identical tolerant
    # length-inference + hex-validation + lowercase-folding, no logic duplicated.
    return hashsets.parse_hash_set("\n".join(bad_hashes))


def match_bad_hashes(
    files: Iterable[FileRow],
    bad: dict[str, set[str]],
    *,
    list_name: str = "known-bad",
) -> list[KnownMatch]:
    """Match ``files`` rows against a known-bad-hash set (reuses ``custom_match``).

    For each file row carrying hashes, probes the known-bad set via
    :func:`pyautopsy.filter.hashsets.custom_match` (sense ``"block"`` — the
    provenance of a known-bad list, never a verdict, D-38). Each hit becomes a
    NEUTRAL :class:`KnownMatch` (``source="custom"``) so it persists through the
    existing sole-writer ``insert_known_matches`` path.

    Args:
        files: The ``files`` rows to probe (e.g. ``store.get_files(...)``).
        bad: A :func:`build_bad_hash_set` result.
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
        hit = hashsets.custom_match(
            bad,
            "block",
            list_name,
            md5=row.md5,
            sha1=row.sha1,
            sha256=row.sha256,
        )
        if hit is not None:
            matches.append(
                KnownMatch(
                    file_id=row.id,
                    source="custom",
                    matched_on=hit["matched_on"],
                    list_name=list_name,
                    sense="block",
                )
            )
    return matches
