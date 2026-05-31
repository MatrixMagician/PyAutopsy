# Phase 4: Deleted Recovery & Known-File Filtering - Context

**Gathered:** 2026-05-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Recover **deleted and orphaned files** from supported filesystems with honest,
filesystem-aware **confidence labeling**, and **filter the file inventory**
against NSRL RDS + user-supplied custom hash sets to cut noise — layered onto
the proven Phase 1–3 SQLite spine.

**Requirements covered:** RECOV-01, RECOV-02, RECOV-03, FILTER-01.

**In scope:**
- Metadata-intact recovery: read content of deleted entries whose metadata + data
  blocks survive (TSK `icat`-equivalent via the `filesystem.py` seam), write as
  recovered `files` rows with source offset/inode and per-file hashes (RECOV-01).
- Orphan files (deleted entries whose parent directory is gone) reported
  **separately** (RECOV-02).
- Confidence tiers **intact** vs **partial/overwritten**, with overwrite
  detection and per-filesystem caveats; labels describe *data survival only*,
  never intent (RECOV-03).
- Known-file filtering against a user-supplied **NSRL RDS SQLite** DB **and**
  custom allow/block hash lists; matches surfaced as a neutral **"known"**
  annotation (source + list name), never a good/bad verdict (FILTER-01).
- New `pyautopsy recover` subcommand + filtering flags; folded into `analyze`
  **only when the relevant inputs are supplied**.

**Out of scope (deferred — NOT this phase):**
- Signature/file **carving** of unallocated space (photorec/scalpel/foremost) —
  that is **CARVE-01**, a separate later requirement.
- **ext4 journal (jbd2)** recovery and a dedicated `journal` confidence tier —
  deferred (fragile, ext-only). The tier taxonomy is designed to *accommodate* a
  future journal tier without schema churn, but no journal producer ships now.
- exFAT/HFS+/APFS deleted-file recovery (**RECOV-04**, gated on TSK build).
- Config-recipe runs (**CONF-01**) and IOC/known-bad content search
  (**SEARCH-02**) — Phase 5.

</domain>

<decisions>
## Implementation Decisions

### Recovery scope & confidence tiers
- **D-29:** Phase 4 ships **metadata-intact recovery only** — recover deleted
  entries whose meta slot + data block runs survive, via the existing
  `evidence/filesystem.py` native seam (TSK `File`/`read_random`, the `icat`
  equivalent). No new native dependency. ext4-journal recovery and signature
  carving are explicitly **deferred** (carving = CARVE-01).
- **D-30:** Confidence taxonomy is **two tiers this phase**: `intact`
  (all data blocks still unallocated / not reused) and `partial/overwritten`
  (one or more data blocks have been reallocated to another file or are no longer
  allocated to this inode). The tier string field is designed so a future
  `journal` / `carved` tier can be added as a new value with **no schema churn**.
- **D-31:** **Overwrite detection** compares the recovered inode's data block
  runs against the filesystem allocation state (and/or blocks now owned by other
  allocated files). Any reallocated/no-longer-owned block ⇒ `partial/overwritten`.
  Per-filesystem caveats (e.g. FAT cluster reuse, NTFS resident vs non-resident)
  are recorded as part of the tier rationale, not hardcoded as certainty.
- **D-32 (honesty, RECOV-03):** Confidence labels describe **data survival**,
  never user intent. The tool must **never** assert "the user deleted this." Tier
  copy and report wording are reviewed for overclaiming (mirrors Phase 3 WR-02).

### Recovered-file output
- **D-33:** Recovered file **contents are written to disk** under a case-dir
  `recovered/` tree, routed through the existing `util/safe_extract` confinement
  jail (realpath confinement + bomb caps), AND cataloged as `files` rows. Hashes
  (MD5/SHA-1/SHA-256) are computed from the **written bytes** (reuse the Phase 2
  single-pass hashing path).
- **D-34:** Recovered-file on-disk naming is **deterministic** and collision-safe,
  keyed by volume + inode (e.g. `recovered/vol<volume_id>-off<volume_offset>/
  <meta_addr>-<sanitized_name>`). Deterministic naming preserves CLI-02
  reproducibility and avoids name collisions between distinct deleted entries that
  reclaimed the same path. (Exact scheme finalized in planning.)
- **D-35:** Recovered `files` rows reuse the **existing `files` schema**
  (`allocated`, `meta_addr`, `volume_id/offset`, hash + MACB columns already
  present from Phase 2). Recovery-specific metadata (confidence tier, recovered
  path, overwrite evidence) lives in the row's `attributes` JSON and/or a
  narrow new column set — **CaseStore remains the sole writer** (no raw SQL
  outside `store.py`). Final column-vs-attributes split decided in planning.

### Known-file filtering input & surfacing
- **D-36:** Filtering accepts **two input kinds**: (1) a user-supplied **NSRL RDS
  "minimal" SQLite** database, queried directly with stdlib `sqlite3` (no new
  dep, read-only); (2) **custom allow/block hash lists** (newline-delimited
  hashes, MD5/SHA-1/SHA-256 auto-detected by hex length). NSRL is **not bundled**
  — it is a large external dataset the examiner provides.
- **D-37:** Match key order is **MD5 / SHA-1 first** (NSRL RDS is keyed on those),
  falling back to **SHA-256**. We already compute all three per file (Phase 2), so
  no re-hashing is needed for allocated files.
- **D-38 (FILTER-01 neutrality):** A match is surfaced as a neutral **"known"**
  annotation carrying `source` (nsrl | custom) and the **list/set name**, plus
  allow/block classification for custom lists — **never** a good/bad verdict. The
  report uses "known" framing as **noise reduction**, not adjudication.
- **D-39:** Filtering is a **post-walk pass over `files` rows** (allocated and
  recovered), writing match annotations via CaseStore. Storage shape (annotation
  column(s) on `files` vs a dedicated `known_file_matches` table) decided in
  planning; whichever preserves determinism and the sole-writer rule.

### CLI & pipeline integration
- **D-40:** New standalone **`pyautopsy recover`** subcommand; filtering exposed
  as flags (e.g. `--nsrl <db>`, `--hash-set <list>` with allow/block sense). The
  **D-21 `analyze` pipeline runs recovery/filtering only when the relevant inputs
  are supplied** — default `analyze` keeps the Phase 3 deterministic report
  baseline byte-stable. Recovery is an explicit examiner choice, not an implicit
  default.
- **D-41 (determinism, CLI-02):** Recovered-file lists and "known" annotations
  in the report body are ordered by the **existing total order**
  (`store.get_*` ORDER BY — `ts→volume→offset→path→...→id`), and the report body
  stays free of wall-clock/run metadata. New report sections (recovered files,
  orphans, known-file summary) must be byte-deterministic across identical runs.
- **D-42 (read-only):** All recovery reads go through the `filesystem.py` seam;
  the evidence source is **never** written. Only the case directory
  (`recovered/`, `case.db`, reports) is written. Read-only re-verify (Phase 1)
  still runs end-of-run.

### Claude's Discretion
- Exact `recovered/` naming/sanitization scheme and the column-vs-`attributes`
  split for recovery metadata and known-match annotations (D-34/D-35/D-39) — to
  be finalized by the planner against the existing schema, preserving the
  CaseStore-sole-writer rule and CLI-02 determinism.
- Whether orphan reporting is a boolean flag + report section or a small derived
  view — planner's call, provided orphans are reported **separately** (RECOV-02).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 4: Deleted Recovery & Known-File Filtering" —
  goal, 4 success criteria, RECOV-01..03 + FILTER-01.
- `.planning/REQUIREMENTS.md` § "Deleted File Recovery" / "Known-File Filtering" —
  RECOV-01..03, FILTER-01; also notes CARVE-01, RECOV-04, CONF-01, SEARCH-02 as
  **deferred** (do not pull forward).
- `.planning/PROJECT.md` — tech-stack constraints; NSRL guidance (modern RDS =
  large SQLite "minimal" DBs queried via stdlib `sqlite3`; keyed on MD5/SHA-1;
  treat ingestion as optional/later, not a pip install), fuzzy-hash (ssdeep/TLSH)
  is *similarity not integrity* and out of scope here, "What NOT to Use" (don't
  reimplement TSK carving/parsing — wrap pytsk3).

### Prior-phase decisions that constrain this phase
- `.planning/phases/02-filesystem-walk-metadata/02-CONTEXT.md` — D-14 native-seam
  allowlist (`evidence/filesystem.py` owns `FS_Info`/`Volume_Info`/`Directory`/
  `File`), D-15 volume tagging, **D-18 deleted entries already recorded with
  allocated/unallocated status + preserved `meta_addr` (recovery deferred to
  HERE)**, D-17 single-pass MD5/SHA-1/SHA-256.
- `.planning/phases/03-timeline-mvp-report/03-CONTEXT.md` — D-21 `analyze` full
  pipeline, D-23 shared forensic-event model, D-25 segregate run metadata from
  the byte-comparable report body, D-26 stable total order (CLI-02).

### Code the planner/researcher must read
- `src/pyautopsy/evidence/filesystem.py` — the ONLY recovery-read seam
  (`walk_fs`, `FileEntry` with `allocated`/`meta_addr`, `read_random`).
- `src/pyautopsy/core/walk.py` — `run_walk`, `_build_file_row`, single-pass
  hashing + content-typing path to reuse for recovered bytes.
- `src/pyautopsy/case/store.py` + `src/pyautopsy/case/schema.sql` — `files`
  table (already has `allocated`, `meta_addr`, hash, MACB, volume cols + an
  `attributes` JSON on every table), sole-writer rule, total-order ORDER BY.
- `src/pyautopsy/util/safe_extract.py` — confinement jail for writing the
  `recovered/` tree (`ExtractionLimits`, realpath confinement).
- `src/pyautopsy/core/analyze.py` (`run_analyze`) — where opt-in recovery/filter
  steps slot into the D-21 pipeline.
- `src/pyautopsy/report/assemble.py` / `report/jsonreport.py` — deterministic
  report body to extend with recovered-files / orphans / known-file sections.

No external ADRs beyond the `.planning/` docs above — requirements fully
captured in the decisions section.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`evidence/filesystem.py` seam** — already walks and yields deleted entries
  (`allocated is False`, `meta_addr` preserved). Recovery reads inode content
  through the same seam; no second native importer (D-14 allowlist holds).
- **`files` table + `FileRow`** — already carries `allocated`, `meta_addr`,
  `volume_id/offset`, MD5/SHA-1/SHA-256, MACB, and a per-row `attributes` JSON.
  Recovered files are just more `files` rows; recovery metadata fits in
  `attributes` (or a narrow new column set).
- **Single-pass hashing + content typing** (`walk.py` `_content_fields`) —
  reuse to hash/type recovered bytes in one streaming pass.
- **`safe_extract` jail** — reuse to write the `recovered/` tree under the case
  dir with realpath confinement + bomb caps.
- **`store.get_*` total order** — extend for deterministic recovered/known lists
  (CLI-02); never re-sort outside the store.

### Established Patterns
- **Single native seam allowlist (D-06/D-14):** recovery reads MUST go through
  `evidence/filesystem.py`; the grep gate enforces no other pytsk3/pyewf imports.
- **CaseStore is the sole DB writer (D-08):** all recovered rows + known-match
  annotations written via store methods; no raw SQL elsewhere.
- **Deterministic, run-metadata-free report body (D-25/D-26):** new report
  sections obey the same byte-determinism contract.
- **Honest status copy (Phase 3 WR-02 lesson):** no hardcoded/overclaimed
  certainty — applies directly to confidence tiers (D-32).

### Integration Points
- `core/analyze.py::run_analyze` — opt-in recovery + filtering steps inserted
  between walk and timeline/report when inputs supplied (D-40).
- `case/store.py` + `schema.sql` — recovery metadata + known-match storage.
- `report/assemble.py` — new "Recovered Files", "Orphan Files", and
  "Known-File Filtering (noise reduction)" sections; JSON gets the full lists.
- Typer CLI — new `recover` subcommand + `--nsrl` / `--hash-set` flags.

</code_context>

<specifics>
## Specific Ideas

- Recovery and filtering are **opt-in / explicit** — the examiner chooses to run
  them; the default one-command `analyze` report stays exactly as Phase 3 shipped
  unless recovery/filter inputs are passed.
- "Known" framing is strictly **noise reduction**, echoing standard DFIR NSRL
  usage (filter known-good to reduce review volume), never an automated verdict.
- The two-tier confidence model is intentionally minimal but **forward-shaped**:
  a `journal` or `carved` tier can be added later as a new enum value without
  touching the schema.

</specifics>

<deferred>
## Deferred Ideas

- **Signature/file carving** of unallocated space (photorec/scalpel/foremost) —
  **CARVE-01**, its own later effort; brings new external tool deps.
- **ext4 journal (jbd2) recovery** + a `journal` confidence tier — deferred;
  fragile and ext-only. Taxonomy leaves room for it.
- **exFAT/HFS+/APFS deleted-file recovery** — **RECOV-04**, gated on the linked
  TSK build / runtime capability probe.
- **Config-recipe runs (CONF-01)** and **IOC / known-bad content search +
  offsets (SEARCH-02)** — Phase 5 territory.
- Fuzzy-hash (ssdeep/TLSH) near-duplicate matching — similarity, not integrity;
  not part of FILTER-01's known-file filtering.

None of these block Phase 4; all are recorded so they are not lost.

</deferred>

---

*Phase: 4-Deleted Recovery & Known-File Filtering*
*Context gathered: 2026-05-31*
