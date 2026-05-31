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
    "VolumeEntry",
    "enumerate_volumes",
    "open_fs",
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
            possible downstream (WR-03); ``None`` at the root.
        _seen: Inode seen-set guarding recursion (recursion state).
        _depth: Current recursion depth, bounded by :data:`_MAX_WALK_DEPTH`
            against adversarial deep nesting (WR-04, recursion state).

    Yields:
        A :class:`FileEntry` per filesystem entry.
    """
    if _seen is None:
        _seen = set()
    ftype = int(fs.info.ftype)

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
            parent_addr=parent_addr,
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
