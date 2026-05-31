"""In-memory pytsk3-shaped fakes for unit-testing ``walk_fs`` recursion.

``evidence/filesystem.walk_fs`` walks a ``pytsk3.FS_Info`` by duck-typing:

* ``fs.info.ftype`` — the filesystem-type integer.
* ``fs.open_dir(path=...)`` — returns an iterable of directory entries.
* ``entry.info.name`` — ``.name`` (bytes), ``.flags`` (int), ``.type`` (int).
* ``entry.info.meta`` — ``.flags``/``.addr``/``.type``/``.uid``/``.gid``/
  ``.mode``/``.mtime``/``.atime``/``.ctime``/``.crtime`` (+ ``*_nano`` via
  ``getattr``), or ``None``.
* ``entry.read_random(offset, size)`` — content bytes.

These fakes implement exactly that surface so the WR-03 (parent_addr threading)
and WR-04 (depth-cap) behaviours can be exercised deterministically without a
crafted on-disk image. The native flag/type integers are read from the installed
pytsk3 so the fake stays in lock-step with the seam's own constants.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytsk3

_NAME_ALLOC = int(pytsk3.TSK_FS_NAME_FLAG_ALLOC)
_META_ALLOC = int(pytsk3.TSK_FS_META_FLAG_ALLOC)
_META_TYPE_DIR = int(pytsk3.TSK_FS_META_TYPE_DIR)
_META_TYPE_REG = int(pytsk3.TSK_FS_META_TYPE_REG)
_NAME_TYPE_DIR = int(pytsk3.TSK_FS_NAME_TYPE_DIR)
_NAME_TYPE_REG = int(pytsk3.TSK_FS_NAME_TYPE_REG)
_FTYPE_EXT4 = int(pytsk3.TSK_FS_TYPE_EXT4)


class _FakeName:
    def __init__(self, name: str, *, is_dir: bool) -> None:
        self.name = name.encode("utf-8")
        self.flags = _NAME_ALLOC
        self.type = _NAME_TYPE_DIR if is_dir else _NAME_TYPE_REG


class _FakeMeta:
    def __init__(self, addr: int, *, is_dir: bool) -> None:
        self.flags = _META_ALLOC
        self.addr = addr
        self.type = _META_TYPE_DIR if is_dir else _META_TYPE_REG
        self.uid = 0
        self.gid = 0
        self.mode = 0o755 if is_dir else 0o644
        self.mtime = 0
        self.atime = 0
        self.ctime = 0
        self.crtime = 0
        self.size = 0
        self.mtime_nano = 0
        self.atime_nano = 0
        self.ctime_nano = 0
        self.crtime_nano = 0


class _FakeInfo:
    def __init__(self, name: _FakeName, meta: _FakeMeta) -> None:
        self.name = name
        self.meta = meta


class FakeDirEntry:
    """One fake directory entry (name + meta), shaped like a pytsk3 entry."""

    def __init__(self, name: str, *, addr: int, is_dir: bool) -> None:
        self.info = _FakeInfo(
            _FakeName(name, is_dir=is_dir), _FakeMeta(addr, is_dir=is_dir)
        )

    def read_random(self, offset: int, size: int) -> bytes:
        return b""


class _FakeFSInfo:
    def __init__(self, ftype: int) -> None:
        self.ftype = ftype


class FakeFS:
    """A fake ``FS_Info`` driven by a ``{path: [FakeDirEntry, ...]}`` map."""

    def __init__(self, tree: dict[str, list[FakeDirEntry]]) -> None:
        self._tree = tree
        self.info = _FakeFSInfo(_FTYPE_EXT4)

    def open_dir(self, path: str) -> list[FakeDirEntry]:
        return self._tree.get(path, [])


class DeepFakeFS:
    """A fake ``FS_Info`` where every directory contains one deeper directory.

    Each level uses a NEW inode address (so the inode seen-set never fires) and a
    fixed child name; the only thing that can stop the descent is ``walk_fs``'s
    depth cap (WR-04). ``open_dir`` synthesises the child on demand from the path
    depth, so the tree is effectively infinite.
    """

    def __init__(self) -> None:
        self.info = _FakeFSInfo(_FTYPE_EXT4)

    def open_dir(self, path: str) -> Iterator[FakeDirEntry]:
        # Depth = number of "d" path segments already descended; the child at
        # this level gets a unique inode so the seen-set guard cannot fire.
        depth = path.count("/d") if path != "/" else 0
        yield FakeDirEntry("d", addr=depth + 2, is_dir=True)
