"""Streaming content / IOC / known-bad-hash search (SEARCH-01/02, D-49).

This package is the upper search tier. It imports NO native binding
(``pytsk3``/``pyewf``, D-14): every byte it scans arrives through the two
established seams — the byte seam (``evidence/image.py``) and the FS seam
(``evidence/filesystem.py``, specifically the new ``iter_unallocated_blocks``
generator and per-file ``read_random`` closures). It is purely stdlib
(``re``) + the reused Phase-4 ``filter/*`` infrastructure (D-43: no new
runtime dependency).

Modules:

* :mod:`pyautopsy.search.content` — SEARCH-01 streaming literal/regex scanner
  over allocated file content and unallocated space, with a carry-over overlap
  window so a chunk-boundary-spanning match is found exactly once (Pitfall 5)
  and absolute-offset reporting (PERF-01: never slurps a whole region).
* :mod:`pyautopsy.search.ioc` — SEARCH-02 IOC-term parsing + the known-bad-hash
  arm that reuses ``filter/hashsets`` (and ``filter/nsrl``) verbatim.
"""

from __future__ import annotations

__all__: list[str] = []
