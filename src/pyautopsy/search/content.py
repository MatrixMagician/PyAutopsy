"""SEARCH-01 streaming literal/regex content scanner (D-49, Pitfall 5, PERF-01).

The scanner reads evidence in bounded chunks and applies compiled literal and/or
regex terms to each chunk, carrying a small overlap window between chunks so a
match that straddles a chunk boundary is found — and reported exactly ONCE — at
its correct absolute offset (Pitfall 5). It never slurps a whole region into
memory (PERF-01): allocated file content is read per-inode through the FS seam's
``read_random`` closure, and unallocated space streams block-by-block through the
new ``iter_unallocated_blocks`` seam generator.

This module imports NO native binding (D-14): the image is opened via the byte
seam (:func:`pyautopsy.evidence.image.open_image`) and walked via the FS seam
(:mod:`pyautopsy.evidence.filesystem`); all byte access goes through those two
seams. Examiner regexes are compiled with a documented match-length bound (a
ReDoS / unbounded-``.*`` guard, Security V5 / threat T-05-03-01).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

from pyautopsy.case.models import SearchHit
from pyautopsy.evidence import filesystem as fs_seam
from pyautopsy.evidence import image as image_seam

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "MAX_REGEX_MATCH_LEN",
    "SearchPatternError",
    "compile_regex",
    "search_bytes",
    "search_image",
]

# Default streaming chunk size (1 MiB). Bounds per-read memory (PERF-01) while
# staying large enough that per-chunk overhead is negligible.
DEFAULT_CHUNK_SIZE = 1 << 20

# Hard upper bound on how many bytes a single regex match may span (ReDoS /
# unbounded-``.*`` guard, Security V5 / T-05-03-01). A bounded match length also
# bounds the carry-over overlap window so the boundary-spanning guard stays cheap.
MAX_REGEX_MATCH_LEN = 4096

# Bytes of surrounding context captured around a hit (data only — the report
# autoescapes it). Bounded so a hit row can never balloon (T-05-03-04).
_CONTEXT_RADIUS = 32


class SearchPatternError(ValueError):
    """Raised when an examiner-supplied regex term cannot be compiled.

    A ``ValueError`` subclass so the orchestrator maps it to a clean
    ``SearchError`` operator failure, never a ``.crashed`` bug (T-05-03-05).
    """


def compile_regex(pattern: bytes) -> re.Pattern[bytes]:
    """Compile an examiner regex term with a documented complexity bound.

    Compiled against ``bytes`` (the scanner works on raw bytes so a non-UTF-8
    needle is exact). Compilation failure raises :class:`SearchPatternError` so a
    bad pattern is a clean operator error, not a crash (T-05-03-01/05). The ReDoS
    guard is enforced at *scan* time: every match is bounded to
    :data:`MAX_REGEX_MATCH_LEN` bytes and the stream is read in bounded chunks
    (PERF-01), so an unbounded ``.*`` can never run over a whole in-memory volume.

    Args:
        pattern: The regex source as raw ``bytes``.

    Returns:
        The compiled :class:`re.Pattern`.

    Raises:
        SearchPatternError: If the pattern is not a valid regex.
    """
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise SearchPatternError(f"invalid search regex {pattern!r}: {exc}") from exc


def _context_snippet(window: bytes, start: int, end: int) -> str:
    """Return a bounded, decoded context snippet around ``[start:end]`` (data)."""
    lo = max(0, start - _CONTEXT_RADIUS)
    hi = min(len(window), end + _CONTEXT_RADIUS)
    return window[lo:hi].decode("latin-1")


def _iter_window_matches(
    window: bytes,
    *,
    literals: Sequence[bytes],
    regexes: Sequence[re.Pattern[bytes]],
    carry_len: int,
) -> Iterator[tuple[int, int, bytes, str]]:
    """Yield ``(start, end, term, kind)`` matches in ``window`` (dedup-aware).

    A match is emitted only when it ENDS in the new data — its end position is
    strictly past ``carry_len`` (the carried overlap prefix). A match lying
    entirely within the carried prefix was already emitted while scanning the
    previous chunk, so skipping it here is the exactly-once boundary-spanning
    guard (Pitfall 5). Positions are window-relative; the caller maps them to an
    absolute offset.
    """
    for term in literals:
        if not term:
            continue
        pos = window.find(term)
        while pos != -1:
            end = pos + len(term)
            if end > carry_len:
                yield pos, end, term, "literal"
            pos = window.find(term, pos + 1)
    for rx in regexes:
        for m in rx.finditer(window):
            start, end = m.start(), m.end()
            if end - start > MAX_REGEX_MATCH_LEN:
                # ReDoS / unbounded-``.*`` guard: ignore an over-long match
                # (Security V5 / T-05-03-01) rather than emit a giant hit.
                continue
            if end > carry_len:
                yield start, end, m.group(0), "regex"


def _overlap_for(
    literals: Sequence[bytes], regexes: Sequence[re.Pattern[bytes]]
) -> int:
    """Return the carry-over overlap: longest literal-1, or the regex bound."""
    overlap = 0
    for term in literals:
        overlap = max(overlap, len(term) - 1)
    if regexes:
        overlap = max(overlap, MAX_REGEX_MATCH_LEN - 1)
    return max(overlap, 0)


def _stream_scan(
    chunks: Iterator[tuple[int, bytes]],
    *,
    literals: Sequence[bytes],
    regexes: Sequence[re.Pattern[bytes]],
    overlap: int,
) -> Iterator[tuple[int, bytes, str, str]]:
    """Scan a stream of ``(base_offset, data)`` chunks with a carry-over overlap.

    Yields ``(absolute_offset, term, term_kind, context)`` per match. The
    carry-over overlap (``overlap`` tail bytes of the previous chunk) is prepended
    to each CONTIGUOUS chunk so a boundary-spanning match is seen; the dedup in
    :func:`_iter_window_matches` makes it emit exactly once (Pitfall 5).

    ``base_offset`` is the absolute offset of each chunk's first byte. A stream
    that signals a gap (a base that is not ``prev_base + prev_len``) drops the
    stale carry so a spurious cross-gap match is never reported.
    """
    carry = b""
    carry_base = 0
    expected_base: int | None = None
    for base, data in chunks:
        if not data:
            continue
        if expected_base is not None and base == expected_base and carry:
            window = carry + data
            window_base = carry_base
            carry_len = len(carry)
        else:
            window = data
            window_base = base
            carry_len = 0
        for start, end, term, kind in _iter_window_matches(
            window, literals=literals, regexes=regexes, carry_len=carry_len
        ):
            yield window_base + start, term, kind, _context_snippet(
                window, start, end
            )
        if overlap > 0 and len(window) > overlap:
            carry = window[-overlap:]
            carry_base = window_base + len(window) - overlap
        else:
            carry = window
            carry_base = window_base
        expected_base = base + len(data)


def _emit(
    matches: Iterator[tuple[int, bytes, str, str]],
    *,
    term_kind: str,
    region: str,
    evidence_source_id: int,
    volume_id: int,
    volume_offset: int,
    path: str | None,
    block_size: int,
    block_offset_base: int,
) -> Iterator[SearchHit]:
    """Map scan ``(offset, term, kind, context)`` tuples to :class:`SearchHit`."""
    for abs_off, term, kind, context in matches:
        block_index = None
        if region == "unallocated" and block_size > 0:
            block_index = (abs_off - block_offset_base) // block_size
        yield SearchHit(
            evidence_source_id=evidence_source_id,
            region=region,
            term=term,
            # Literal hits adopt the caller's kind (literal|ioc); regex stays regex.
            term_kind=term_kind if kind == "literal" else kind,
            volume_id=volume_id,
            volume_offset=volume_offset,
            byte_offset=abs_off,
            path=path,
            block_index=block_index,
            context=context,
        )


def search_bytes(
    blob: bytes,
    *,
    terms: Sequence[bytes] = (),
    regexes: Sequence[bytes] = (),
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    term_kind: str = "literal",
    region: str = "unallocated",
    evidence_source_id: int = 0,
    volume_id: int = 0,
    volume_offset: int = 0,
    base_offset: int = 0,
    path: str | None = None,
) -> Iterator[SearchHit]:
    """Stream-scan a single ``bytes`` blob for literal/regex terms (SEARCH-01).

    The blob is sliced into ``chunk_size`` chunks and scanned with a carry-over
    overlap so a match spanning a chunk boundary is found exactly once at its
    correct absolute offset (Pitfall 5). ``byte_offset`` is ``base_offset`` plus
    the match position within the blob.

    Args:
        blob: The bytes to scan.
        terms: Literal byte needles.
        regexes: Regex byte sources (compiled with the ReDoS bound).
        chunk_size: Streaming chunk size (must be > 0).
        term_kind: ``term_kind`` for literal hits (``"literal"`` or ``"ioc"``).
        region/evidence_source_id/volume_id/volume_offset/path/base_offset:
            Provenance copied onto every emitted hit.

    Yields:
        A :class:`SearchHit` per match, in ascending offset order.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    literals = [t for t in terms if t]
    compiled = [compile_regex(r) for r in regexes]
    overlap = _overlap_for(literals, compiled)

    def _chunks() -> Iterator[tuple[int, bytes]]:
        for off in range(0, len(blob), chunk_size):
            yield base_offset + off, blob[off : off + chunk_size]

    yield from _emit(
        _stream_scan(_chunks(), literals=literals, regexes=compiled, overlap=overlap),
        term_kind=term_kind,
        region=region,
        evidence_source_id=evidence_source_id,
        volume_id=volume_id,
        volume_offset=volume_offset,
        path=path,
        block_size=0,
        block_offset_base=base_offset,
    )


def _file_chunks(
    reader: object, size: int, chunk_size: int
) -> Iterator[tuple[int, bytes]]:
    """Yield ``(file_offset, data)`` chunks of an allocated file (read-only)."""
    off = 0
    while off < size:
        want = min(chunk_size, size - off)
        try:
            data = reader.read_random(off, want)  # type: ignore[attr-defined]
        except OSError:
            return
        if not data:
            return
        yield off, data
        off += len(data)


def _unallocated_chunks(
    handle: object, fs: object, vol: object, block_bytes: int, base_offset: int
) -> Iterator[tuple[int, bytes]]:
    """Yield ``(absolute_image_offset, data)`` for each unallocated block.

    Wraps the FS seam's ``(block_index, bytes)`` stream, mapping every block index
    to its absolute image offset (``base_offset + index * block_bytes``). Taking
    ``fs``/``vol`` as arguments (rather than closing over loop variables) keeps the
    per-volume mapping unambiguous (no late-binding hazard, B023).
    """
    for block_index, data in fs_seam.iter_unallocated_blocks(handle, fs, vol):  # type: ignore[arg-type]
        yield base_offset + block_index * block_bytes, data


def search_image(
    image_path: str,
    *,
    terms: Sequence[bytes] = (),
    regexes: Sequence[bytes] = (),
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    term_kind: str = "literal",
    evidence_source_id: int = 0,
) -> Iterator[SearchHit]:
    """Stream-scan an image's allocated content + unallocated space (SEARCH-01).

    Opens the image read-only through the byte seam, enumerates volumes through
    the FS seam, and for each volume scans (a) every allocated regular file's
    content via its ``read_random`` closure (``region="allocated"``,
    file-relative offset) and (b) the unallocated-block stream via
    :func:`~pyautopsy.evidence.filesystem.iter_unallocated_blocks`
    (``region="unallocated"``, image/volume-relative offset). Streaming
    throughout (PERF-01); boundary-spanning matches handled per file and within
    contiguous unallocated runs (Pitfall 5).

    Args:
        image_path: Path to the evidence image (raw/dd or first E01 segment).
        terms: Literal byte needles.
        regexes: Regex byte sources (compiled with the ReDoS bound).
        chunk_size: Streaming chunk size.
        term_kind: ``term_kind`` for literal hits (``"literal"`` or ``"ioc"``).
        evidence_source_id: Provenance id copied onto every emitted hit.

    Yields:
        A :class:`SearchHit` per match (allocated + unallocated regions).
    """
    literals = [t for t in terms if t]
    compiled = [compile_regex(r) for r in regexes]
    overlap = _overlap_for(literals, compiled)

    handle = image_seam.open_image(image_path)
    try:
        for vol in fs_seam.enumerate_volumes(handle.image):
            try:
                fs = fs_seam.open_fs(handle.image, vol.offset)
            except OSError:
                # Encrypted/unsupported volume: nothing to scan (D-20).
                continue

            # (a) Allocated regular-file content (file-relative offsets).
            for entry in fs_seam.walk_fs(fs, vol.volume_id, vol.offset):
                if entry.meta_type != "reg" or not entry.allocated:
                    continue
                if entry.read_random is None or entry.size <= 0:
                    continue
                scan = _stream_scan(
                    _file_chunks(entry, entry.size, chunk_size),
                    literals=literals,
                    regexes=compiled,
                    overlap=overlap,
                )
                yield from _emit(
                    scan,
                    term_kind=term_kind,
                    region="allocated",
                    evidence_source_id=evidence_source_id,
                    volume_id=vol.volume_id,
                    volume_offset=vol.offset,
                    path=entry.path,
                    block_size=0,
                    block_offset_base=0,
                )

            # (b) Unallocated space (image/volume-relative offsets) via the seam.
            bs = fs_seam.block_size(fs)
            scan = _stream_scan(
                _unallocated_chunks(handle, fs, vol, bs, vol.offset),
                literals=literals,
                regexes=compiled,
                overlap=overlap,
            )
            yield from _emit(
                scan,
                term_kind=term_kind,
                region="unallocated",
                evidence_source_id=evidence_source_id,
                volume_id=vol.volume_id,
                volume_offset=vol.offset,
                path=None,
                block_size=bs,
                block_offset_base=vol.offset,
            )
    finally:
        handle.close()
