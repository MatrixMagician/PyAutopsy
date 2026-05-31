"""Custom allow/block hash-list parsing + neutral matching (FILTER-01, D-38).

An examiner can supply newline-delimited hash lists alongside (or instead of)
the NSRL RDS — typically a small allow-list of locally-known-good build
artifacts, or a block-list of hashes of interest. This module parses those
lists tolerantly and answers the same neutral "is this hash *known* to the
list?" question the NSRL probe does.

Parsing (T-04-02-PARSE) tolerates the real shape of hand-maintained lists:

* blank lines and ``#`` comment lines are skipped,
* only the leading whitespace-delimited token of a line is read as the hash (a
  trailing ``  filename.bin`` comment is ignored),
* the algorithm is inferred from the hex *length* — ``32`` → md5, ``40`` →
  sha1, ``64`` → sha256 (the :data:`_LEN_TO_ALGO` map, extending
  ``evidence.integrity``'s md5/sha256 map with sha1) — and
* every token is hex-validated and lowercase-normalized, so a mixed-case or
  UPPERCASE list entry still matches our lowercase ``files`` row hashes.

A match is surfaced as a NEUTRAL ``known`` annotation carrying ``source``,
``list``, ``sense`` (``allow``|``block``) and ``matched_on`` only — never a
good/bad/malicious/verdict key (D-38). The allow/block ``sense`` is recorded as
provenance, NOT interpreted as a verdict. This module imports no
``pytsk3``/``pyewf`` (D-14): pure stdlib text parsing.
"""

from __future__ import annotations

__all__ = ["custom_match", "parse_hash_set"]

# Map a hash hex-digest length to the algorithm it identifies. Extends
# ``evidence.integrity._LEN_TO_ALGO`` (which only needs md5/sha256 for
# acquisition compare) with sha1, because custom lists and NSRL are commonly
# keyed on sha1 (D-37 md5→sha1→sha256).
_LEN_TO_ALGO: dict[int, str] = {32: "md5", 40: "sha1", 64: "sha256"}

# Probe order: md5 → sha1 → sha256 (D-37), matching the NSRL probe.
_HASH_COLUMNS: tuple[str, ...] = ("md5", "sha1", "sha256")


def parse_hash_set(text: str) -> dict[str, set[str]]:
    """Parse a newline-delimited custom hash list into per-algorithm sets.

    Tolerates ``#`` comment lines, blank lines, trailing per-line comments
    (only the leading token is read), and mixed-case hex (T-04-02-PARSE). The
    algorithm is inferred from the token's hex length via :data:`_LEN_TO_ALGO`;
    tokens that are not valid hex of a recognised length (32/40/64) are skipped
    rather than aborting the parse, so one malformed line never discards a whole
    list.

    Args:
        text: The raw text of the hash list (e.g. a list file's contents).

    Returns:
        ``{"md5": set, "sha1": set, "sha256": set}`` of lowercase hex digests
        (any of the sets may be empty).
    """
    parsed: dict[str, set[str]] = {algo: set() for algo in _HASH_COLUMNS}
    for raw_line in text.splitlines():
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


def custom_match(
    parsed: dict[str, set[str]],
    sense: str,
    list_name: str,
    *,
    md5: str | None,
    sha1: str | None,
    sha256: str | None,
) -> dict[str, str] | None:
    """Probe a parsed custom list for a file's hashes (md5 → sha1 → sha256).

    Each supplied hash is lowercase-folded and tested for membership in the
    matching algorithm set, in D-37 order. The first hit is surfaced as a
    NEUTRAL match dict carrying provenance only — ``source``/``list``/``sense``/
    ``matched_on`` — never a good/bad/verdict key (D-38). The ``sense`` is
    recorded as recorded provenance (allow vs block list), not a judgement.

    Args:
        parsed: A :func:`parse_hash_set` result.
        sense: The list's sense — ``"allow"`` or ``"block"`` (provenance only).
        list_name: The list's display name (surfaced in the report).
        md5: The file's MD5 hex (any case), or ``None``.
        sha1: The file's SHA-1 hex (any case), or ``None``.
        sha256: The file's SHA-256 hex (any case), or ``None``.

    Returns:
        ``{"source": "custom", "list": list_name, "sense": sense,
        "matched_on": col}`` on the first matching hash, else ``None``.
    """
    for col, val in zip(_HASH_COLUMNS, (md5, sha1, sha256), strict=True):
        if val and val.lower() in parsed[col]:
            return {
                "source": "custom",
                "list": list_name,
                "sense": sense,
                "matched_on": col,
            }
    return None
