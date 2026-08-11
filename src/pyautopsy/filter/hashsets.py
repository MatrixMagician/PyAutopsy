"""Known-hash list parsing + neutral matching (FILTER-01/SEARCH-02, D-38).

One parser and one probe serve every known-hash question the tool asks, whether
the hashes came from an examiner's allow/block list file (known-file filtering)
or from ``--hash-set-block`` on the search command (known-bad matching). Both
ask the same thing — *is this file's hash known to the supplied set?* — so both
go through the same code.

Parsing (T-04-02-PARSE) tolerates the real shape of hand-maintained lists:

* blank lines and ``#`` comment lines are skipped,
* only the leading whitespace-delimited token of a line is read as the hash (a
  trailing ``  filename.bin`` comment is ignored),
* the algorithm is inferred from the hex *length* — ``32`` → md5, ``40`` →
  sha1, ``64`` → sha256 (the :data:`_LEN_TO_ALGO` map, extending
  ``evidence.integrity``'s md5/sha256 map with sha1) — and
* every token is hex-validated and lowercase-normalized, so a mixed-case or
  UPPERCASE list entry still matches our lowercase ``files`` row hashes.

A malformed token is skipped rather than aborting the list: one bad line must
never discard an examiner's whole hash set.

**Neutrality.** A match records that a hash is *known* to a supplied list, with
the source, list name and list sense as provenance. It is never a good/bad
verdict (D-38) — a hash appearing on a block list is a fact about the list, not
a finding about the file. That is why :func:`to_known_match` is the single
place a hit becomes a persisted record: the neutrality rule is stated once.

This module imports no ``pytsk3``/``pyewf`` (D-14): pure stdlib text parsing.
"""

from __future__ import annotations

from collections.abc import Iterable

from pyautopsy.case.models import KnownMatch

__all__ = [
    "HashSet",
    "parse_hash_set",
    "probe_hash_set",
    "to_known_match",
]

# Map a hash hex-digest length to the algorithm it identifies. Extends
# ``evidence.integrity._LEN_TO_ALGO`` (which only needs md5/sha256 for
# acquisition compare) with sha1, because custom lists and NSRL are commonly
# keyed on sha1 (D-37 md5→sha1→sha256).
_LEN_TO_ALGO: dict[int, str] = {32: "md5", 40: "sha1", 64: "sha256"}

# Probe order: md5 → sha1 → sha256 (D-37), matching the NSRL probe.
_HASH_COLUMNS: tuple[str, ...] = ("md5", "sha1", "sha256")

# A parsed hash list: lowercase hex digests bucketed by algorithm.
HashSet = dict[str, set[str]]


def parse_hash_set(lines: Iterable[str]) -> HashSet:
    """Parse hash-list lines into per-algorithm sets.

    Takes any iterable of lines — a file's ``splitlines()``, or a sequence of
    hashes supplied on the command line — so callers never have to join text
    back together just to have it split again.

    Args:
        lines: The hash-list lines (or bare hashes), in any case, with or
            without comments and blank lines.

    Returns:
        ``{"md5": set, "sha1": set, "sha256": set}`` of lowercase hex digests
        (any of the sets may be empty).
    """
    parsed: HashSet = {algo: set() for algo in _HASH_COLUMNS}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        token = line.split()[0]
        algorithm = _LEN_TO_ALGO.get(len(token))
        if algorithm is None:
            continue
        normalized = token.lower()
        try:
            int(normalized, 16)
        except ValueError:
            continue
        parsed[algorithm].add(normalized)
    return parsed


def probe_hash_set(
    parsed: HashSet,
    *,
    md5: str | None,
    sha1: str | None,
    sha256: str | None,
) -> str | None:
    """Return which hash column matched the set, or ``None``.

    Each supplied hash is lowercase-folded and tested for membership in the
    matching algorithm set, in D-37 order (md5 → sha1 → sha256). The answer is
    just the column that matched: provenance and neutrality live in
    :func:`to_known_match`, so the probe stays a plain set lookup.

    Args:
        parsed: A :func:`parse_hash_set` result.
        md5: The file's MD5 hex (any case), or ``None``.
        sha1: The file's SHA-1 hex (any case), or ``None``.
        sha256: The file's SHA-256 hex (any case), or ``None``.

    Returns:
        ``"md5"`` / ``"sha1"`` / ``"sha256"`` for the first match, else ``None``.
    """
    for col, val in zip(_HASH_COLUMNS, (md5, sha1, sha256), strict=True):
        if val and val.lower() in parsed[col]:
            return col
    return None


def to_known_match(
    file_id: int, matched_on: str, *, list_name: str, sense: str
) -> KnownMatch:
    """Build the NEUTRAL record for one known-hash hit (D-38).

    The single place a hit becomes a persisted finding, so the neutrality rule
    is stated once: the record carries where the match came from — source, list
    name, list sense, and which hash column matched — and never a good/bad
    verdict. A ``sense`` of ``"block"`` is provenance about the list the hash
    was found on, not a judgement about the file.

    Args:
        file_id: The matched ``files`` row id.
        matched_on: The hash column that matched (from :func:`probe_hash_set`).
        list_name: The list's display name, surfaced in the report.
        sense: The list's sense — ``"allow"`` or ``"block"`` (provenance only).

    Returns:
        A :class:`~pyautopsy.case.models.KnownMatch` ready to persist.
    """
    return KnownMatch(
        file_id=file_id,
        source="custom",
        matched_on=matched_on,
        list_name=list_name,
        sense=sense,
    )
