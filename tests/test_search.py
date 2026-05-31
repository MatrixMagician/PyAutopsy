"""RED Wave-0 scaffold for Phase-5 streaming content/unallocated search.

These stubs pin the exact pytest node IDs from 05-RESEARCH.md "Validation
Architecture > Test Map" for the search slices: SEARCH-01 (literal + regex over
allocated file content AND unallocated space, offsets correct; plus the
chunk-boundary-spanning guard, Pitfall 5) and SEARCH-02 (IOC list + known-bad
hash hits reported by file + offset, reusing the Phase-4 ``filter/*`` infra).

They reference the (not-yet-existing) ``pyautopsy.search`` package
(``search.content``, ``search.ioc``), the new sole-writer store methods
(``CaseStore.insert_search_hits`` / ``get_search_hits``), and the new FS-seam
generator ``evidence.filesystem.iter_unallocated_blocks`` — so each test FAILS
until the Wave-2/3 slices land. The not-yet-existing imports are inside each test
body so the file collects cleanly (in-body ``ImportError`` == RED, not a
collection error). None are ``xfail``/``skip``.

Ground truth (planted needles + offsets, IOC term, known-bad hash) comes from the
committed ``log_search_image`` + ``log_search_groundtruth`` sidecar. The upper
``search/`` tier imports NO ``pytsk3`` — all native access is via the two seams
(D-14, enforced by ``tests/test_seam_allowlist.py``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def test_streaming_search_all_regions(
    log_search_image: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """SEARCH-01: literal+regex over allocated file content + UNALLOCATED, w/ offsets.

    The allocated needle is found inside its file (region=allocated, file-relative
    offset matching the recorded ground truth); the distinct unallocated needle
    (left behind by the deleted file's surviving blocks) is found in an
    UNALLOCATED block via the new seam generator, reported with an absolute
    image/volume-relative offset. Streaming, never slurping (PERF-01).
    """
    from pyautopsy.search import content  # noqa: PLC0415 (RED stub)

    gt = log_search_groundtruth
    alloc_needle = gt["allocated_search"]["needle"].encode()
    unalloc_needle = gt["unallocated_search"]["needle"].encode()

    hits = list(
        content.search_image(
            str(log_search_image), terms=[alloc_needle, unalloc_needle]
        )
    )
    regions = {h.region for h in hits}
    assert "allocated" in regions, "allocated-content hit missing"
    assert "unallocated" in regions, "unallocated hit missing"

    # The allocated hit points at the planted file at the recorded offset.
    alloc_hits = [h for h in hits if h.region == "allocated" and h.term == alloc_needle]
    assert alloc_hits, "allocated needle not found in its file"
    assert any(gt["allocated_search"]["path"] in (h.path or "") for h in alloc_hits)

    # The unallocated hit carries a concrete (non-None) byte offset.
    unalloc_hits = [
        h for h in hits if h.region == "unallocated" and h.term == unalloc_needle
    ]
    assert unalloc_hits, "unallocated needle not found"
    assert all(h.byte_offset is not None for h in unalloc_hits)


def test_boundary_spanning_match() -> None:
    """SEARCH-01/Pitfall 5: a match straddling a chunk boundary is found ONCE.

    A term split across two streamed chunks must still be found (carry-over
    overlap window) and must NOT be double-reported when the overlap re-scans the
    seam between chunks. Asserts exactly one hit at the correct absolute offset.
    """
    from pyautopsy.search import content  # noqa: PLC0415 (RED stub)

    chunk = 16
    term = b"SPANSPAN"  # 8 bytes; planted to straddle a 16-byte chunk boundary
    # Place the term starting at offset 12 so bytes 12-15 are in chunk 0 and
    # bytes 16-19 are in chunk 1 (the term spans the chunk boundary).
    blob = b"\x00" * 12 + term + b"\x00" * 40
    assert blob.index(term) == 12

    hits = list(content.search_bytes(blob, terms=[term], chunk_size=chunk))
    matching = [h for h in hits if h.term == term]
    assert len(matching) == 1, (
        f"boundary-spanning match found {len(matching)} times, want 1"
    )
    assert matching[0].byte_offset == 12


def test_ioc_and_hash_hits(
    log_search_image: Path, case_dir: Path, log_search_groundtruth: dict[str, Any]
) -> None:
    """SEARCH-02: IOC + known-bad-hash hits reported by file + offset (reuse filter).

    The IOC term (a planted indicator appearing in a log line + allocated content)
    matches via the literal/IOC arm; the known-bad-hash file matches via the
    reused Phase-4 ``filter/hashsets`` matcher. Both are persisted as the new
    ``SearchHit`` rows (sole writer) and read back in the store-owned total order,
    each carrying its file reference and offset.
    """
    from pyautopsy.case import CaseStore  # noqa: PLC0415
    from pyautopsy.core.ingest import run_ingest  # noqa: PLC0415
    from pyautopsy.core.search import run_search  # noqa: PLC0415 (RED stub)
    from pyautopsy.core.walk import run_walk  # noqa: PLC0415

    gt = log_search_groundtruth
    ingested = run_ingest(log_search_image, case_dir, examiner="X", evidence_id="E1")
    run_walk(log_search_image, case_dir, timezone="UTC")
    run_search(
        log_search_image,
        case_dir,
        evidence_source_id=ingested.evidence_source_id,
        ioc_terms=[gt["ioc_term"].encode()],
        bad_hashes={gt["known_bad_hash"]["sha256"]},
    )

    with CaseStore.open(case_dir) as store:
        hits = store.get_search_hits(ingested.evidence_source_id)

    kinds = {h.term_kind for h in hits}
    assert "ioc" in kinds, "IOC term hit missing"
    assert "hash" in kinds, "known-bad-hash hit missing"

    # The known-bad-hash hit references the planted malware file.
    hash_hits = [h for h in hits if h.term_kind == "hash"]
    assert any(gt["known_bad_hash"]["path"] in (h.path or "") for h in hash_hits)

    # IOC hits carry a concrete byte offset (reported by file + offset, SEARCH-02).
    ioc_hits = [h for h in hits if h.term_kind == "ioc"]
    assert ioc_hits and all(h.byte_offset is not None for h in ioc_hits)


def test_iter_unallocated_blocks_seam(log_search_image: Path) -> None:
    """SEARCH-01 plumbing: the new FS-seam generator yields unallocated block bytes.

    pytsk3 exposes no block-flag/block-walk API, so the seam derives the allocated
    set (``allocated_data_blocks``) and yields ``(block_index, bytes)`` for the
    complement via the byte seam — keeping ALL native access inside
    ``evidence/filesystem.py`` (D-14). The deleted-file's surviving needle must
    appear in one of the yielded unallocated blocks.
    """
    from pyautopsy.evidence import filesystem as fs_seam  # noqa: PLC0415
    from pyautopsy.evidence import image as image_seam  # noqa: PLC0415

    needle = b"UNALLOCATED-NEEDLE-9c5d1e"
    handle = image_seam.open_image(str(log_search_image))
    try:
        found = False
        for vol in fs_seam.enumerate_volumes(handle.image):
            try:
                fs = fs_seam.open_fs(handle.image, vol.offset)
            except OSError:
                continue
            # The new seam generator (RED until Wave 2 adds it).
            for _block_index, data in fs_seam.iter_unallocated_blocks(handle, fs, vol):
                if needle in data:
                    found = True
                    break
            if found:
                break
        assert found, "unallocated needle not found via iter_unallocated_blocks"
    finally:
        handle.close()


# A typing import kept referenced so linters do not flag the Any-typed fixtures.
_: Any = None
