---
status: diagnosed
phase: 04-deleted-recovery-known-file-filtering
source: [04-VERIFICATION.md]
started: 2026-05-31T15:09:30Z
updated: 2026-05-31T17:55:00Z
---

## Current Test

[testing complete — 1 issue found + diagnosed]

## Tests

### 1. Rendered report shows three distinct, legible sections (Recovered / Orphan / Known-File)
expected: Running `pyautopsy recover <image> --case <dir>` then `pyautopsy analyze <image> --case <dir> --recover --nsrl <nsrl.db> --hash-set-allow <list>` and opening `reports/report.html` shows three separate, clearly-labelled sections — Recovered Files, Orphan Files (orphans NOT mixed into the recovered list, RECOV-02), and Known-File Filtering (noise reduction). The known-file framing is neutral ("known", with source + list name) — no good/bad/safe/malicious verdict language anywhere.
result: issue
reported: "Three sections render and known-file framing is neutral (verified) — BUT recovered/orphan classification is WRONG: every deleted file in a volume's ROOT directory is mislabelled is_orphan and dumped into 'Orphan Files', leaving 'Recovered Files' empty. On a host-built partitioned disk (FAT + ext4), analyze --recover --nsrl --hash-set-allow produced: Recovered Files = 0; Orphan Files = 3 incl. FAT /_DEL1.TXT and /_DEL2.TXT whose parent IS the present root /. The Orphan section literally states 'deleted entries whose parent directory is itself gone, so they have no path back to the root' — a FALSE provenance claim for these files (overclaim, against D-32/RECOV-03). A deleted file inside a SURVIVING subdirectory classifies correctly (is_orphan=False), so the defect is root-level-specific."
severity: major

### 2. Confidence tiers use a glyph/text indicator (not color-only) and per-fs caveats read honestly
expected: Each recovered file's confidence tier (intact vs partial/overwritten) is conveyed with a text/glyph indicator — never color alone — and the per-filesystem caveats (ext4 pointer-zeroing, NTFS resident, FAT first-char-lost) read as honest data-survival statements. No copy anywhere asserts intent (e.g. never "the user deleted this"). A4 print-to-PDF layout has no clipped cards; long hashes/paths wrap.
result: pass
verified: "2026-05-31 — PASS (presentation/honesty), via the rendered report + headless-Chrome A4 PDF (4 pages).
  - Confidence tier is text+glyph, never color-only: rendered as '● intact' (bullet glyph + the tier word).
  - Per-fs caveat copy is honest data-survival language, e.g. 'Recovered content is best-effort data survival only: ext4 clears block pointers on unlink…'; per-row 'all surviving data blocks still unallocated'. (Test fixtures exercised intact-tier ext4/FAT; NTFS-resident/FAT-first-char-lost caveat strings live in the templates.)
  - NO intent language anywhere (scan for 'user deleted/removed', 'deliberately', 'malicious', etc. → none); the only 'safe' occurrence is the neutral disclaimer 'a known file is not asserted to be good or safe'.
  - A4 print-to-PDF = 4 pages at A4, no clipped cards; long SHA-256 wraps across two lines.
  NOTE: these presentation checks pass independent of the Test-1 classification bug (the tier/caveat/print machinery is correct; only the recovered-vs-orphan routing is wrong)."

## Summary

total: 2
passed: 1
issues: 1
pending: 0
skipped: 0
blocked: 0

## Gaps

- truth: "Deleted files whose parent directory still exists (e.g. a volume's root) are reported in the Recovered Files section as non-orphans; only entries whose parent is genuinely gone appear under Orphan Files (RECOV-02)."
  status: failed
  reason: "Root-level deleted files are mislabelled is_orphan=True, so Recovered Files is empty and they appear under Orphan Files with the false claim 'parent directory is itself gone'. Verified on a host-built FAT+ext4 partitioned disk."
  severity: major
  test: 1
  root_cause: "core/../evidence/filesystem.py walk_fs() yields root-level entries with parent_addr=None (it passes parent_addr=None at _depth==0 / the root call; docstring even says 'None at the root'). iter_deleted_inodes() then computes parent_known_orphan = (parent_addr is None OR parent_addr not in alloc_inodes), so ANY deleted entry whose walk-derived parent_addr is None is flagged is_orphan=True. None is OVERLOADED: it means both 'root-level entry' (walk_fs default) AND 'no surviving dir link' (the genuine pass-2 orphan at filesystem.py:524). The root directory is always allocated, so root-level deletions are NOT orphans. Confirmed: raw TSK exposes par_addr=2 (root) for the FAT files with meta ORPHAN flag UNSET and root inode 2 in the allocated set; a deleted file in a SURVIVING subdir correctly gets parent_addr=<dir inode> and is_orphan=False."
  artifacts:
    - path: "src/pyautopsy/evidence/filesystem.py"
      issue: "walk_fs() passes parent_addr=None for root-level entries (default param at the _depth==0 call); should tag them with the root inode address (fs.info.root_inum) so 'None' is reserved for genuine no-dir-link orphans."
    - path: "src/pyautopsy/evidence/filesystem.py"
      issue: "iter_deleted_inodes() treats parent_addr is None as parent_known_orphan=True, conflating walk_fs's root-level None with a true missing parent."
  missing:
    - "Tag root-level FileEntry rows in walk_fs with parent_addr = int(fs.info.root_inum) (only when _depth==0 / parent_addr is None at the initial call), so a deleted file in root has an allocated parent_addr and classifies as recovered (non-orphan)."
    - "Alternatively/additionally, disambiguate in iter_deleted_inodes so a root-level entry is not treated as an orphan purely because parent_addr is None."
    - "Add a regression test: a deleted file in a volume ROOT classifies is_orphan=False (Recovered), while a deleted file whose parent dir is removed classifies is_orphan=True (Orphan) — covering both FAT and ext4."
  debug_session: ""
