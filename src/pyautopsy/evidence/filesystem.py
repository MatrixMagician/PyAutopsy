"""The FS-layer native seam — volume/filesystem/directory walking (D-14).

This is the **second** member of the D-14 native-binding allowlist (alongside
:mod:`pyautopsy.evidence.image`, the byte-layer seam). It is the only module
besides ``image.py`` permitted to ``import pytsk3``, and it owns the *filesystem*
surface of TSK: :class:`pytsk3.Volume_Info` (partition enumeration, the ``mmls``
equivalent), :class:`pytsk3.FS_Info` (filesystem open + type detection),
``open_dir``/``as_directory`` recursion, and per-entry ``File`` access.

Like the byte-layer seam, **no native type escapes this module**: the walk yields
plain-Python :class:`FileEntry` value objects (frozen dataclasses of primitive
fields plus a single ``read_random`` byte-reader closure over the TSK ``File``),
so the orchestrator, hashing, typing, and case-store tiers stay unit-testable
with fakes and the native dependency stays confined (D-14, D-19).

The evidence is read **read-only and is never mounted** (D-05, PITFALLS P1): every
byte comes through the TSK ``File`` object's ``read_random`` — there is no
mount/losetup/write path anywhere in this module.

API names here were empirically verified against the installed pytsk3 4.15.0 on
real ext4/NTFS/FAT32 fixtures (02-RESEARCH.md §Code Examples).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytsk3

__all__ = [
    "EXT_FS_TYPES",
    "FAT_FS_TYPES",
    "FileEntry",
    "FilesystemError",
    "NTFS_FS_TYPES",
    "DeletedInode",
    "RecoveredEntry",
    "VolumeEntry",
    "allocated_data_blocks",
    "allocated_inodes",
    "enumerate_volumes",
    "fs_type_int",
    "iter_deleted_inodes",
    "open_fs",
    "recover_meta",
    "walk_fs",
]

# The TSK fs-type integers, captured here as PLAIN INTS. These are the seam's
# pytsk3-free contract: ``core/walk.py`` (which MUST NOT import pytsk3, D-14) can
# classify a filesystem family — and thus apply the right D-16 timestamp handling
# / label — by membership-testing ``fs_ftype in <SET>`` without ever touching the
# native binding. Deriving each set from the pytsk3 enums (rather than hard-coding
# magic ints in the orchestrator) means the labels can never silently drift from
# the installed binding (CR-02). Exported as ``frozenset[int]`` so they are
# immutable.
FAT_FS_TYPES: frozenset[int] = frozenset(
    {
        int(pytsk3.TSK_FS_TYPE_FAT12),
        int(pytsk3.TSK_FS_TYPE_FAT16),
        int(pytsk3.TSK_FS_TYPE_FAT32),
    }
)

# ext2/ext3/ext4 — verified against pytsk3 4.15.0: EXT2=128, EXT3=256, EXT4=8192.
# Derived from the enums (NOT the literal ``{2,4,8}`` which are in fact the FAT
# values) so ext2/ext3 images are correctly labelled ``ext`` and not ``unknown``.
EXT_FS_TYPES: frozenset[int] = frozenset(
    {
        int(pytsk3.TSK_FS_TYPE_EXT2),
        int(pytsk3.TSK_FS_TYPE_EXT3),
        int(pytsk3.TSK_FS_TYPE_EXT4),
    }
)

# NTFS — a single TSK fs-type integer, exported as a set for a uniform,
# pytsk3-free membership contract alongside FAT/EXT.
NTFS_FS_TYPES: frozenset[int] = frozenset(
    {
        int(pytsk3.TSK_FS_TYPE_NTFS),
    }
)

# Internal flag constants (kept here so they never leak past the seam).
_VS_PART_FLAG_ALLOC = int(pytsk3.TSK_VS_PART_FLAG_ALLOC)
_FS_NAME_FLAG_ALLOC = int(pytsk3.TSK_FS_NAME_FLAG_ALLOC)
_FS_META_FLAG_ALLOC = int(pytsk3.TSK_FS_META_FLAG_ALLOC)
_FS_META_TYPE_DIR = int(pytsk3.TSK_FS_META_TYPE_DIR)
_FS_META_TYPE_VIRT_DIR = int(pytsk3.TSK_FS_META_TYPE_VIRT_DIR)

# Recovery-path flag constants (Plan 04-01, D-29/D-30/D-31). Derived from the
# pytsk3 enums (never hard-coded ints, CR-02) and kept inside the seam so the
# orchestrator (``core/recover.py``, which MUST NOT import pytsk3, D-14) never
# touches the native binding. ``UNALLOC``/``ORPHAN`` drive the Pitfall-5
# reallocation re-check and the RECOV-02 orphan flag; ``NONRES``/``SPARSE`` gate
# the data-block-run enumeration (resident data and sparse runs occupy no real
# blocks — RESEARCH §Pattern 2 / Pitfall 3).
_FS_META_FLAG_UNALLOC = int(pytsk3.TSK_FS_META_FLAG_UNALLOC)
_FS_META_FLAG_ORPHAN = int(pytsk3.TSK_FS_META_FLAG_ORPHAN)
_TSK_FS_ATTR_NONRES = int(pytsk3.TSK_FS_ATTR_NONRES)
_TSK_FS_ATTR_RUN_FLAG_SPARSE = int(pytsk3.TSK_FS_ATTR_RUN_FLAG_SPARSE)

# (WR-04) Hard cap on directory-recursion depth. Real filesystems nest far
# shallower than this; a crafted image with thousands of nested directories
# (the directory-cycle/deep-nesting DoS, threat T-2-01-CYCLE) would otherwise
# exhaust Python's C call stack and raise ``RecursionError``, aborting the whole
# walk. At the cap we stop descending (the entries at that depth are still
# yielded by their parent's loop) rather than crash. The inode seen-set already
# stops true cycles; this bounds adversarial *acyclic* deep nesting too.
_MAX_WALK_DEPTH = 512

# Map the TSK meta-type integer to a stable, pytsk3-free label string. Anything
# unmapped falls back to ``"unknown"`` so a label always exists for a row.
_META_TYPE_LABELS: dict[int, str] = {
    int(pytsk3.TSK_FS_META_TYPE_REG): "reg",
    int(pytsk3.TSK_FS_META_TYPE_DIR): "dir",
    int(pytsk3.TSK_FS_META_TYPE_LNK): "lnk",
    int(pytsk3.TSK_FS_META_TYPE_FIFO): "fifo",
    int(pytsk3.TSK_FS_META_TYPE_CHR): "chr",
    int(pytsk3.TSK_FS_META_TYPE_BLK): "blk",
    int(pytsk3.TSK_FS_META_TYPE_SOCK): "sock",
    int(pytsk3.TSK_FS_META_TYPE_VIRT): "virt",
    int(pytsk3.TSK_FS_META_TYPE_VIRT_DIR): "virt_dir",
}

# Map the TSK *name*-entry type integer to the SAME stable labels. The directory
# entry carries its own type byte (the ``TSK_FS_NAME_TYPE_*`` enum, which is a
# DIFFERENT integer space from the meta-type enum) and is the authoritative type
# source when the inode's meta-type is UNDEF — e.g. ext4 files written by
# ``debugfs`` carry ``meta.type == UNDEF`` but a correct ``name.type == REG``.
# Falling back to it mirrors TSK's own ``fls`` behaviour and keeps a genuine
# regular file from being mislabelled ``unknown`` (which would wrongly exclude it
# from META-04/META-05 content hashing/typing).
_NAME_TYPE_LABELS: dict[int, str] = {
    int(pytsk3.TSK_FS_NAME_TYPE_REG): "reg",
    int(pytsk3.TSK_FS_NAME_TYPE_DIR): "dir",
    int(pytsk3.TSK_FS_NAME_TYPE_LNK): "lnk",
    int(pytsk3.TSK_FS_NAME_TYPE_FIFO): "fifo",
    int(pytsk3.TSK_FS_NAME_TYPE_CHR): "chr",
    int(pytsk3.TSK_FS_NAME_TYPE_BLK): "blk",
    int(pytsk3.TSK_FS_NAME_TYPE_SOCK): "sock",
    int(pytsk3.TSK_FS_NAME_TYPE_VIRT): "virt",
    int(pytsk3.TSK_FS_NAME_TYPE_VIRT_DIR): "virt_dir",
}


class FilesystemError(Exception):
    """Raised when the FS-layer seam cannot enumerate or walk a filesystem.

    Mirrors :class:`pyautopsy.evidence.image.ImageOpenError`: it carries an
    actionable message rather than leaking a native ``IOError``/``OSError`` stack
    trace. Note that an *unsupported/encrypted volume* is **not** surfaced as this
    error — :func:`open_fs` lets the native ``OSError`` propagate so the
    orchestrator can record it as a D-20 known-limitation finding and continue.
    """


@dataclass(frozen=True, slots=True)
class VolumeEntry:
    """A plain-Python descriptor of one enumerated volume (D-15).

    Attributes:
        volume_id: The volume/partition id (``part.addr``; ``0`` for bare-FS).
        offset: Byte offset of the volume within the image (sectors × block
            size — PITFALLS Pitfall 7).
        length: Length of the volume in bytes.
        description: Human-readable description (partition type string, or the
            bare-filesystem note).
    """

    volume_id: int
    offset: int
    length: int
    description: str


@dataclass(frozen=True, slots=True)
class FileEntry:
    """A frozen, pytsk3-free value object for one filesystem entry (META-01..05).

    Every field is a plain Python primitive (or ``None``); the only non-primitive
    is :attr:`read_random`, a byte-reader closure over the underlying TSK ``File``
    so the orchestrator can hash/type the content (D-17/D-19) WITHOUT ever seeing
    a native ``File``/``Directory``/``meta`` object. No native type escapes this
    seam (D-14).

    MACB times are raw epoch integers exactly as TSK reports them (``0`` means
    "not recorded"); normalisation to UTC ISO-8601 happens in the orchestrator
    (Plan 02-02), keeping this seam free of timezone policy.

    Attributes:
        name: The entry's own name (decoded ``utf-8``/``errors="replace"`` — data
            only, never used as a path to write, Security V5).
        path: Full path of the entry within its filesystem.
        parent_addr: Parent directory inode/MFT address, when known.
        meta_addr: The entry's inode/MFT address (META-01), or ``None``.
        allocated: ``True`` only if both the name and meta slots are allocated;
            ``False`` for a deleted/unallocated entry (META-01/D-18).
        meta_type: Stable meta-type label (``reg``/``dir``/``lnk``/...).
        size: Logical size in bytes (``0`` when meta is absent).
        uid: Owning user id (META-03), or ``None``.
        gid: Owning group id (META-03), or ``None``.
        mode: POSIX permission/mode bits (META-03), or ``None``.
        mtime: Modified epoch seconds (raw TSK int).
        atime: Accessed epoch seconds (raw TSK int).
        ctime: Changed/metadata epoch seconds (raw TSK int).
        crtime: Created/born epoch seconds (raw TSK int).
        mtime_nano: Sub-second nanoseconds for mtime, when present.
        atime_nano: Sub-second nanoseconds for atime, when present.
        ctime_nano: Sub-second nanoseconds for ctime, when present.
        crtime_nano: Sub-second nanoseconds for crtime, when present.
        fs_ftype: The filesystem type integer (``fs.info.ftype``); test against
            :data:`FAT_FS_TYPES` for FAT local-time handling.
        volume_id: The volume this entry was found in (D-15).
        volume_offset: Byte offset of that volume within the image (D-15).
        read_random: ``(offset, size) -> bytes`` reader over the entry's content
            (read-only). ``None`` for entries with no readable content (no meta).
    """

    name: str
    path: str
    parent_addr: int | None
    meta_addr: int | None
    allocated: bool
    meta_type: str
    size: int
    uid: int | None
    gid: int | None
    mode: int | None
    mtime: int
    atime: int
    ctime: int
    crtime: int
    mtime_nano: int
    atime_nano: int
    ctime_nano: int
    crtime_nano: int
    fs_ftype: int
    volume_id: int
    volume_offset: int
    read_random: Callable[[int, int], bytes] | None = field(default=None)


@dataclass(frozen=True, slots=True)
class RecoveredEntry:
    """A frozen, pytsk3-free descriptor of one reopened deleted inode (RECOV-01).

    The recovery analogue of :class:`FileEntry`: every field is a plain Python
    primitive plus a single :attr:`read_random` byte-reader closure over the
    underlying TSK ``File`` from ``open_meta``, so the recovery orchestrator
    (:mod:`pyautopsy.core.recover`, which MUST NOT import pytsk3 — D-14) can
    classify the confidence tier, hash, and write the recovered bytes WITHOUT ever
    seeing a native ``File``/``Attribute``/``TSK_FS_ATTR_RUN`` object. No native
    type escapes this seam.

    Attributes:
        meta_addr: The reopened inode/MFT address (``meta.addr``).
        size: Logical size in bytes (``meta.size``; ``0`` when no readable data).
        meta_type: Stable meta-type label (``reg``/``dir``/...), same space as
            :class:`FileEntry`.
        is_orphan: ``True`` when ``meta.flags & ORPHAN`` — the entry's parent
            directory is gone (RECOV-02, Pattern 3).
        now_allocated: ``True`` when ``meta.flags & ALLOC`` at recover time — the
            inode-reuse hazard (Pitfall 5); a reopened inode now owned by a live
            file must never be presented as the deleted file's content.
        data_blocks: The deleted file's non-resident, non-sparse data-block
            addresses as plain ascending ``int``s (RESEARCH §Pattern 2). Empty for
            a resident file (NTFS small files) or an ext4 zeroed-pointer delete.
        has_resident_data: ``True`` when readable bytes exist with NO non-resident
            runs — a resident file recovered straight from the MFT record
            (Pitfall 3).
        read_random: ``(offset, size) -> bytes`` read-only reader over the
            recovered content, or ``None`` when there is nothing to read.
    """

    meta_addr: int
    size: int
    meta_type: str
    is_orphan: bool
    now_allocated: bool
    data_blocks: tuple[int, ...]
    has_resident_data: bool
    read_random: Callable[[int, int], bytes] | None = field(default=None)


def _iter_block_runs(f: object) -> Iterator[int]:
    """Yield the non-resident, non-sparse data-block addresses of a TSK ``File``.

    Iterates the ``File``'s attributes → each attribute's ``TSK_FS_ATTR_RUN``
    linked list (both verified iterable in pytsk3 — RESEARCH §Pattern 2), skipping
    resident attributes (no real blocks) and sparse runs (occupy no blocks). The
    addresses are emitted as plain ``int``s so no native ``Attribute``/run object
    escapes the seam (D-14).
    """
    for attr in f:  # type: ignore[attr-defined]
        ai = attr.info
        if not (int(ai.flags) & _TSK_FS_ATTR_NONRES):
            # Resident data (NTFS small files) has no data-block runs.
            continue
        for run in attr:
            if int(run.flags) & _TSK_FS_ATTR_RUN_FLAG_SPARSE:
                # Sparse runs occupy no real blocks (Pattern 2).
                continue
            yield from range(int(run.addr), int(run.addr) + int(run.len))


def _runs_and_residency(f: object, *, size: int) -> tuple[list[int], bool]:
    """Return a recovered file's block-run list + whether its data is resident.

    ``has_resident_data`` is ``True`` when the file has readable bytes
    (``size > 0``) but NO non-resident data-block runs — the NTFS resident-$DATA
    case (Pitfall 3), where the content lives inside the MFT record itself.
    """
    blocks = sorted(_iter_block_runs(f))
    has_resident_data = bool(size > 0 and not blocks)
    return blocks, has_resident_data


def recover_meta(fs: pytsk3.FS_Info, inode: int) -> RecoveredEntry | None:
    """Reopen a (deleted) inode by address and describe its recoverable content.

    The TSK ``icat`` equivalent (RESEARCH §Pattern 1): ``fs.open_meta(inode=...)``
    reopens any inode regardless of allocation status and ``File.read_random``
    returns the bytes its surviving data runs still point at. Returns a
    pytsk3-free :class:`RecoveredEntry` (a ``read_random`` closure plus plain-int
    block runs and meta flags) so no native object escapes the seam (D-14).

    A missing/invalid inode address makes ``open_meta`` raise ``OSError`` — that
    is mapped to ``None`` (mirrors :func:`open_fs`'s OSError idiom) rather than
    propagating, so the orchestrator can simply skip it.

    Args:
        fs: The open filesystem (from :func:`open_fs`).
        inode: The inode/MFT address recorded by the Phase-2 walk.

    Returns:
        A :class:`RecoveredEntry`, or ``None`` when the inode cannot be opened or
        carries no meta record.
    """
    try:
        f = fs.open_meta(inode=inode)
    except OSError:
        return None
    m = f.info.meta
    if m is None:
        return None
    size = int(m.size)
    blocks, has_resident_data = _runs_and_residency(f, size=size)
    # Bind the File in the closure so its lifetime spans the read (read-only;
    # never writes or mounts the source — D-05/P1).
    reader: Callable[[int, int], bytes] | None = None
    if size:

        def read_random(offset: int, length: int) -> bytes:
            return f.read_random(offset, length)

        reader = read_random
    return RecoveredEntry(
        meta_addr=int(m.addr),
        size=size,
        meta_type=_meta_type_label(int(m.type)),
        is_orphan=bool(int(m.flags) & _FS_META_FLAG_ORPHAN),
        now_allocated=bool(int(m.flags) & _FS_META_FLAG_ALLOC),
        data_blocks=tuple(blocks),
        has_resident_data=has_resident_data,
        read_random=reader,
    )


@dataclass(frozen=True, slots=True)
class DeletedInode:
    """A pytsk3-free descriptor of one deleted-and-recoverable inode (RECOV-01/02).

    Produced by :func:`iter_deleted_inodes`: the recovery orchestrator iterates
    these to know WHICH inodes to recover plus the directory-derived
    name/path/parent metadata (so it never touches pytsk3 to walk the tree). The
    actual byte recovery + block-run classification still goes through
    :func:`recover_meta`.

    Attributes:
        meta_addr: The deleted inode/MFT address to recover.
        name: The entry's directory name (lossy on FAT; data only — Pitfall 3).
        path: The entry's path within the filesystem (best-effort; a synthetic
            ``$OrphanFiles/<addr>`` style path for inodes with no surviving dir
            link).
        parent_addr: The parent directory inode address, when a dir link
            survives; ``None`` for an inode reached only by range scan.
        is_orphan: ``True`` when the entry has no surviving allocated parent
            directory — either TSK set the ORPHAN meta flag, the parent inode is
            itself unallocated/gone, or no dir link survives at all (RECOV-02,
            Pattern 3).
    """

    meta_addr: int
    name: str
    path: str
    parent_addr: int | None
    is_orphan: bool


def fs_type_int(fs: pytsk3.FS_Info) -> int:
    """Return ``fs.info.ftype`` as a plain int (test against the FS-type sets).

    Keeps the orchestrator pytsk3-free: it labels a recovered filesystem via the
    seam's :data:`FAT_FS_TYPES`/:data:`EXT_FS_TYPES`/:data:`NTFS_FS_TYPES`
    membership sets without touching ``fs.info`` (a native attribute) itself.
    """
    return int(fs.info.ftype)


def allocated_inodes(fs: pytsk3.FS_Info) -> frozenset[int]:
    """Return the set of ALLOCATED inode addresses (for orphan parent checks).

    Walks the inode range once and collects every inode whose ``meta.flags``
    carry ``ALLOC``. The recovery orchestrator uses this to decide orphan-ness:
    a deleted entry whose ``parent_addr`` is NOT in this set has no surviving
    allocated parent directory (Pattern 3). Returned as a ``frozenset[int]`` of
    plain ints (the seam's frozenset export convention).
    """
    allocated: set[int] = set()
    first = int(fs.info.first_inum)
    last = int(fs.info.last_inum)
    for inum in range(first, last + 1):
        try:
            f = fs.open_meta(inode=inum)
        except OSError:
            continue
        m = f.info.meta
        if m is None:
            continue
        if int(m.flags) & _FS_META_FLAG_ALLOC:
            allocated.add(int(m.addr))
    return frozenset(allocated)


def iter_deleted_inodes(
    fs: pytsk3.FS_Info, volume_id: int, volume_offset: int
) -> Iterator[DeletedInode]:
    """Yield every deleted, recoverable regular inode in ``fs`` (RECOV-01/02).

    Two discovery passes, unioned by ``meta_addr`` so each inode is yielded once:

    1. **Directory walk** (:func:`walk_fs`): collects deleted (``allocated is
       False``) regular entries that still carry a ``meta_addr`` — these have a
       surviving (if deleted) directory link, so we know their name/path/parent.
    2. **Inode-range scan**: catches deleted regular inodes whose directory link
       is broken (e.g. an NTFS resident-deleted entry whose name entry lost its
       meta reference, so the walk reports ``meta_addr is None``). These are
       given a synthetic ``$OrphanFiles/<addr>`` path and treated as orphans.

    Orphan-ness (Pattern 3): an entry is an orphan when TSK set the ORPHAN meta
    flag, OR its surviving ``parent_addr`` is not an allocated inode, OR it has no
    surviving dir link at all. The allocated-inode set is derived once for the
    parent check.

    Yields:
        A :class:`DeletedInode` per deleted recoverable regular inode, in
        ascending ``meta_addr`` order (deterministic — Pitfall 6).
    """
    ORPHAN = _FS_META_FLAG_ORPHAN  # noqa: N806 (local alias of the seam const)
    alloc_inodes = allocated_inodes(fs)

    # Pass 1: directory-walk-derived metadata for deleted regular entries.
    walked: dict[int, DeletedInode] = {}
    for fe in walk_fs(fs, volume_id, volume_offset):
        if fe.allocated is not False or fe.meta_addr is None:
            continue
        if fe.meta_type != "reg":
            continue
        addr = fe.meta_addr
        if addr in walked:
            continue
        parent_known_orphan = (
            fe.parent_addr is None or fe.parent_addr not in alloc_inodes
        )
        # Confirm the inode itself and read its ORPHAN flag.
        meta_orphan = False
        try:
            mf = fs.open_meta(inode=addr)
            if mf.info.meta is not None:
                meta_orphan = bool(int(mf.info.meta.flags) & ORPHAN)
        except OSError:
            pass
        walked[addr] = DeletedInode(
            meta_addr=addr,
            name=fe.name,
            path=fe.path,
            parent_addr=fe.parent_addr,
            is_orphan=meta_orphan or parent_known_orphan,
        )

    # Pass 2: inode-range scan for deleted regular inodes with no surviving dir
    # link (broken name->meta reference, e.g. NTFS resident-deleted).
    first = int(fs.info.first_inum)
    last = int(fs.info.last_inum)
    for inum in range(first, last + 1):
        if inum in walked:
            continue
        try:
            f = fs.open_meta(inode=inum)
        except OSError:
            continue
        m = f.info.meta
        if m is None:
            continue
        flags = int(m.flags)
        if flags & _FS_META_FLAG_ALLOC:
            continue
        if not (flags & _FS_META_FLAG_UNALLOC):
            continue
        if _meta_type_label(int(m.type)) != "reg":
            continue
        if int(m.size) <= 0:
            # No recoverable content (ext4 zeroed pointers): the directory pass
            # already covers named deleted entries; skip silent empties here so
            # the range scan only adds genuinely recoverable broken-link inodes.
            continue
        addr = int(m.addr)
        walked[addr] = DeletedInode(
            meta_addr=addr,
            name=f"inode-{addr}",
            path=f"/$OrphanFiles/{addr}",
            parent_addr=None,
            is_orphan=True,
        )

    for addr in sorted(walked):
        yield walked[addr]


def allocated_data_blocks(fs: pytsk3.FS_Info) -> frozenset[int]:
    """Derive the set of data blocks owned by ALLOCATED files (RECOV-03, Pattern 2).

    pytsk3 exposes no usable block-allocation-bitmap API (``TSK_FS_BLOCK`` is
    immediately invalid and there is no ``block_walk`` binding — RESEARCH
    Pitfall 1), so the allocated-block set is built by walking every allocated
    inode's non-resident runs exactly once. The orchestrator intersects a deleted
    file's runs against this set: any overlap ⇒ ``partial/overwritten`` (D-31).

    Args:
        fs: The open filesystem (from :func:`open_fs`).

    Returns:
        A :class:`frozenset` of plain-int block addresses owned by allocated
        files (matches the seam's frozenset export convention).
    """
    blocks: set[int] = set()
    first = int(fs.info.first_inum)
    last = int(fs.info.last_inum)
    for inum in range(first, last + 1):
        try:
            f = fs.open_meta(inode=inum)
        except OSError:
            continue
        m = f.info.meta
        if m is None or not (int(m.flags) & _FS_META_FLAG_ALLOC):
            continue
        blocks.update(_iter_block_runs(f))
    return frozenset(blocks)


def enumerate_volumes(img: pytsk3.Img_Info) -> Iterator[VolumeEntry]:
    """Yield one :class:`VolumeEntry` per *allocated* volume (D-15).

    Uses :class:`pytsk3.Volume_Info` (the ``mmls`` equivalent). A bare-filesystem
    image (no partition table) makes ``Volume_Info`` raise ``OSError`` — the
    documented signal to fall back to a single volume at offset 0 (D-15). For a
    partitioned image, only **allocated** partitions are yielded: the volume
    system's metadata partition (the partition table itself) and unallocated gaps
    are skipped so they never become empty/garbage walk targets.

    Partition byte-offset is ``part.start * block_size`` because ``part.start``
    is in *sectors*, not bytes (PITFALLS Pitfall 7).

    Args:
        img: The opened read-only image (``handle.image`` from the byte seam).

    Yields:
        A :class:`VolumeEntry` per walkable volume.
    """
    try:
        vol = pytsk3.Volume_Info(img)
    except OSError:
        # No partition table → bare filesystem; open the FS at offset 0 (D-15).
        yield VolumeEntry(
            volume_id=0,
            offset=0,
            length=img.get_size(),
            description="bare filesystem (no partition table)",
        )
        return

    block_size = vol.info.block_size
    for part in vol:
        if not (int(part.flags) & _VS_PART_FLAG_ALLOC):
            # Skip the partition table (META) and unallocated gaps — they are not
            # walkable filesystems and must not produce empty/garbage rows.
            continue
        yield VolumeEntry(
            volume_id=int(part.addr),
            offset=int(part.start) * block_size,
            length=int(part.len) * block_size,
            description=part.desc.decode("utf-8", "replace"),
        )


def open_fs(img: pytsk3.Img_Info, offset: int) -> pytsk3.FS_Info:
    """Open a filesystem at ``offset``; ``OSError`` is the D-20 signal.

    :class:`pytsk3.FS_Info` raises ``OSError`` when it cannot determine the
    filesystem type — i.e. the volume is encrypted or unsupported. This function
    deliberately lets that ``OSError`` propagate so the orchestrator can record an
    explicit known-limitation finding and continue the walk (D-20, PITFALLS
    Pitfall 6) rather than aborting the run.

    Args:
        img: The opened read-only image.
        offset: Byte offset of the volume to open.

    Returns:
        An open :class:`pytsk3.FS_Info`.

    Raises:
        OSError: If the filesystem type cannot be determined (encrypted/
            unsupported — caller records a D-20 limitation).
    """
    return pytsk3.FS_Info(img, offset=offset)


def _make_reader(entry: object) -> Callable[[int, int], bytes] | None:
    """Build a read-only byte-reader closure over a TSK directory entry.

    The closure calls ``entry.read_random(offset, size)`` so the orchestrator can
    hash/type content without seeing the native ``File``. Returns ``None`` when
    the entry has no readable content.
    """

    def read_random(offset: int, size: int) -> bytes:
        # read_random is read-only; it never writes or mounts the source (D-05).
        return entry.read_random(offset, size)  # type: ignore[attr-defined]

    return read_random


def _meta_type_label(meta_type: int | None, name_type: int | None = None) -> str:
    """Return a stable type label for an entry, with a name-entry-type fallback.

    The inode's ``meta.type`` is authoritative when set, but ext4 entries written
    by ``debugfs`` (and some recovered/deleted entries) carry ``meta.type ==
    UNDEF`` while the directory entry still records the correct
    ``TSK_FS_NAME_TYPE_*``. When the meta-type is absent or unmapped we therefore
    fall back to the name-entry type (a DIFFERENT enum space) so a genuine regular
    file is labelled ``reg`` rather than ``unknown`` — mirroring TSK's ``fls``.
    Returns ``unknown`` only when neither source yields a known type.
    """
    if meta_type is not None:
        label = _META_TYPE_LABELS.get(int(meta_type))
        if label is not None:
            return label
    if name_type is not None:
        label = _NAME_TYPE_LABELS.get(int(name_type))
        if label is not None:
            return label
    return "unknown"


def walk_fs(
    fs: pytsk3.FS_Info,
    volume_id: int,
    volume_offset: int,
    parent_path: str = "/",
    parent_addr: int | None = None,
    _seen: set[int] | None = None,
    _depth: int = 0,
) -> Iterator[FileEntry]:
    """Recursively yield a :class:`FileEntry` for every entry in ``fs``.

    Manual recursion via ``open_dir``/``as_directory`` (pytsk3 exposes no C
    ``dir_walk`` callback). ``.`` and ``..`` are skipped, and an inode seen-set
    guards against directory cycles / orphan-inode revisits before recursing into
    any directory (PITFALLS Pitfall 4, threat T-2-01-CYCLE). EVERY entry is
    yielded, including deleted/unallocated ones (``allocated is False``,
    META-01/D-18); their ``meta_addr`` is preserved.

    ``$OrphanFiles`` is a virtual directory: it is recursed into like a directory
    so its (deleted) children are inventoried, but no orphan *tree* is
    reconstructed — that is Phase 4 (D-18/A4).

    Args:
        fs: The open filesystem (from :func:`open_fs`).
        volume_id: The volume id to tag yielded entries with (D-15).
        volume_offset: The volume byte offset to tag yielded entries with (D-15).
        parent_path: The directory path currently being walked (recursion state).
        parent_addr: Inode/MFT address of ``parent_path``'s directory, tagged onto
            every entry yielded at this level so parent/child reconstruction is
            possible downstream (WR-03). At the root call (``_depth == 0`` and the
            incoming ``parent_addr is None``) this is substituted with the
            filesystem root inode (``fs.info.root_inum``) so root-level deletions
            classify as *recovered* (their parent — the allocated root — survives),
            NOT as orphans. ``None`` is therefore reserved exclusively for the
            range-scan orphan (a deleted inode with no surviving directory link).
        _seen: Inode seen-set guarding recursion (recursion state).
        _depth: Current recursion depth, bounded by :data:`_MAX_WALK_DEPTH`
            against adversarial deep nesting (WR-04, recursion state).

    Yields:
        A :class:`FileEntry` per filesystem entry.
    """
    if _seen is None:
        _seen = set()
    ftype = int(fs.info.ftype)

    # Resolve the effective parent address for THIS level ONCE. The genuine
    # top-level invocation arrives with ``_depth == 0`` and ``parent_addr is
    # None``; tag its entries with the real root inode (``fs.info.root_inum``)
    # so a deleted file in the root carries an *allocated* parent and is
    # classified as recovered, not an orphan (RECOV-02). The recursive call
    # below always passes the child directory's own (non-None) ``meta_addr`` as
    # the next level's ``parent_addr``, so this guard only ever fires for the
    # root call — keeping ``None`` reserved exclusively for the deliberate
    # pass-2 range-scan orphan (no surviving directory link).
    resolved_parent_addr = parent_addr
    if _depth == 0 and parent_addr is None:
        resolved_parent_addr = int(fs.info.root_inum)

    directory = fs.open_dir(path=parent_path)
    for entry in directory:
        name_obj = entry.info.name
        if name_obj is None:
            continue
        # Names are DATA ONLY — decode leniently, never use as a write path (V5).
        name = name_obj.name.decode("utf-8", "replace")
        if name in (".", ".."):
            continue

        meta = entry.info.meta
        name_alloc = bool(int(name_obj.flags) & _FS_NAME_FLAG_ALLOC)
        meta_alloc = bool(meta is not None and int(meta.flags) & _FS_META_FLAG_ALLOC)
        allocated = name_alloc and meta_alloc

        meta_addr = int(meta.addr) if meta is not None else None
        meta_type_int = int(meta.type) if meta is not None else None
        # The directory entry's own type byte (a DIFFERENT enum from meta.type);
        # the authoritative fallback when the inode meta-type is UNDEF.
        name_type_int = int(name_obj.type) if name_obj.type is not None else None
        size = int(meta.size) if meta is not None else 0

        child_path = parent_path.rstrip("/") + "/" + name
        yield FileEntry(
            name=name,
            path=child_path,
            parent_addr=resolved_parent_addr,
            meta_addr=meta_addr,
            allocated=allocated,
            meta_type=_meta_type_label(meta_type_int, name_type_int),
            size=size,
            uid=int(meta.uid) if meta is not None else None,
            gid=int(meta.gid) if meta is not None else None,
            mode=int(meta.mode) if meta is not None else None,
            mtime=int(meta.mtime) if meta is not None else 0,
            atime=int(meta.atime) if meta is not None else 0,
            ctime=int(meta.ctime) if meta is not None else 0,
            crtime=int(meta.crtime) if meta is not None else 0,
            mtime_nano=int(getattr(meta, "mtime_nano", 0)) if meta is not None else 0,
            atime_nano=int(getattr(meta, "atime_nano", 0)) if meta is not None else 0,
            ctime_nano=int(getattr(meta, "ctime_nano", 0)) if meta is not None else 0,
            crtime_nano=int(getattr(meta, "crtime_nano", 0))
            if meta is not None
            else 0,
            fs_ftype=ftype,
            volume_id=volume_id,
            volume_offset=volume_offset,
            read_random=_make_reader(entry) if meta is not None else None,
        )

        # Recurse into real directories (and $OrphanFiles VIRT_DIR), guarding
        # against inode revisits so a cycle/orphan loop cannot run forever, and
        # bounding total depth so adversarial deep nesting cannot exhaust the
        # stack (WR-04). The child's parent_addr is THIS entry's inode (WR-03).
        if meta is not None and meta_type_int in (
            _FS_META_TYPE_DIR,
            _FS_META_TYPE_VIRT_DIR,
        ):
            if meta.addr in _seen:
                continue
            if _depth >= _MAX_WALK_DEPTH:
                # Depth cap reached: stop descending rather than risk a
                # RecursionError that would abort the whole walk. Entries below
                # this point are not inventoried (a bounded, documented loss far
                # beyond any real filesystem's nesting).
                continue
            _seen.add(meta.addr)
            yield from walk_fs(
                fs,
                volume_id,
                volume_offset,
                child_path,
                meta_addr,
                _seen,
                _depth + 1,
            )
