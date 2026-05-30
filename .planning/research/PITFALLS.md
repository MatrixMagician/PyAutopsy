# Pitfalls Research

**Domain:** Automated digital forensic analysis tooling (TSK/pytsk3-based disk + log analysis, Python/Linux)
**Researched:** 2026-05-30
**Confidence:** HIGH (forensic soundness, integrity, timeline, TSK/pytsk3, safe parsing verified against primary sources; some legal/admissibility points are jurisdiction-dependent — MEDIUM)

> Scope note: PyAutopsy explicitly does NOT certify court admissibility (that is the investigator's job), but its output supports evidence presentation. Therefore the bar is "defensible and reproducible," not just "works." Every pitfall below is framed against that bar.

## Critical Pitfalls

These cause rewrites, invalidate evidence, or get findings thrown out / disbelieved.

### Pitfall 1: Modifying the evidence source (the cardinal sin)

**What goes wrong:**
The tool alters the source it is supposed to analyze — mounting the image read/write, updating access times (atimes) while walking the filesystem, writing recovered files or temp data back into the image, or letting the OS auto-mount/journal-replay the device. Any single write event means the evidence "as analyzed" no longer matches the evidence "as seized."

**Why it happens:**
The path of least resistance on Linux is `mount -o loop image.dd /mnt` and then use normal file APIs. This is *fatal* — `mount` may replay the journal (ext4/NTFS), update mount counts in the superblock, and atimes on read. Developers reach for `mount` because it's familiar; pytsk3's `Img_Info`/`FS_Info` API is less obvious.

**How to avoid:**
- Read evidence ONLY through TSK's image layer (`pytsk3.Img_Info` → `FS_Info`), which opens the image read-only at the byte level and never mounts it. TSK reads inodes/blocks directly; it does not touch atimes or replay journals.
- If a real device must be touched (acquisition), use a hardware or software write-blocker, or open the block device `O_RDONLY` and set `blockdev --setro`. v1 scope is image analysis, so the rule is simpler: **never call `mount` on the source, ever.** Add a hard guard that refuses to operate on a path that is a mounted filesystem.
- Treat the input image file itself as read-only: open `O_RDONLY`, optionally set the file immutable / verify it's on read-only media, and never write anything inside the source. All output (recovered files, temp, reports) goes to a separate, clearly-named output directory.
- Hash the image before and after the run; assert they match (see Pitfall 2).

**Warning signs:**
- `mount`, `losetup` (without `-r`), or any write syscall against the source path anywhere in the codebase.
- atimes/mtimes on the source image file changing across a run.
- Pre/post hash mismatch.

**Phase to address:** Foundation / "Evidence ingestion" phase — this must be designed in before any analysis code exists. Retrofitting read-only guarantees later means re-auditing every code path.

---

### Pitfall 2: Missing, wrong, or unverified hashing → no integrity story

**What goes wrong:**
The tool produces findings but cannot prove the evidence wasn't altered: no hash of the source image, hashing the wrong bytes (the recovered file vs. the source extent), using a single weak/broken algorithm, or computing the "after" hash but never comparing it. Without a verifiable hash chain, every downstream finding is impeachable.

**Why it happens:**
Hashing feels like boilerplate and gets deferred. MD5 is copy-pasted from old tutorials. People hash convenience artifacts (a temp copy) rather than the authoritative source.

**How to avoid:**
- Compute and record the hash of the **source image as ingested** before any processing, store it in the run manifest, and recompute + compare at the end. Fail loudly on mismatch.
- Use SHA-256 as primary. MD5/SHA-1 are acceptable *additional* hashes for cross-tool compatibility (NSRL, legacy case files) but never as the sole integrity proof — both are cryptographically broken for collision resistance.
- Hash **every extracted/recovered artifact** and record it next to the finding, with the source offset/inode it came from.
- Stream hashes (read once, hash + analyze in the same pass) for multi-TB images — don't read the whole image twice.

**Warning signs:**
- Only MD5 in the codebase; no SHA-256.
- Hashes computed but never asserted/compared.
- A finding in the report with no associated hash.

**Phase to address:** Evidence ingestion phase (image hashing) + Reporting phase (per-finding hashes). Integrity must exist before recovery/timeline work, because those consume the hashed source.

---

### Pitfall 3: Non-deterministic / non-reproducible output undermines admissibility

**What goes wrong:**
Running the tool twice on the same image yields different reports — different ordering, embedded wall-clock timestamps, dict/set iteration order, parallel-processing race ordering, random temp paths in output. Reproducibility is a core Daubert-style reliability criterion; if a third party can't reproduce your output, the methodology looks unreliable.

**Why it happens:**
Python dict/set ordering, `os.walk`/`scandir` ordering, multithreading, and "report generated at {now}" embedded in the artifact body all introduce nondeterminism that nobody notices until someone diffs two runs.

**How to avoid:**
- Deterministic ordering everywhere that ends up in output: sort by inode/offset/path before emitting. Don't rely on filesystem walk order.
- Separate **report content** (must be byte-reproducible given same input + tool version) from **run metadata** (timestamp, host, operator — recorded but segregated, e.g. a header block or sidecar, so the analytical body still diffs clean).
- Make parallelism order-independent: collect results then sort, never append in completion order.
- Pin the analysis: record tool version, TSK/libtsk version, and config in the manifest so a given output maps to an exact toolchain.
- Add a CI test: run twice on a fixture image, assert the analytical body is identical.

**Warning signs:**
- `datetime.now()` interpolated into report bodies.
- Two runs produce non-identical reports on the same fixture.
- Iteration over un-sorted dicts/sets feeding output.

**Phase to address:** Reporting phase (design report format for determinism) — but the discipline (sorting, no implicit ordering) must be enforced in every analysis phase.

---

### Pitfall 4: Timezone / MAC-time / clock-skew misinterpretation (the classic forensic error)

**What goes wrong:**
Timestamps are mislabeled or mis-converted: treating a local-time artifact as UTC (or vice versa), ignoring DST transitions, applying the *analysis host's* timezone instead of the *evidence's*, or misreading what M/A/C/B times actually mean. Result: a timeline that puts events at the wrong time — "login after the user left the building," "file created before the OS existed." These anomalies almost always mean misinterpretation, not tampering, and a wrong timeline can swing a case.

**Why it happens:**
TSK returns Unix epoch times that are UTC-based, but different artifacts store time differently: some filesystems store UTC (NTFS), some store local time (FAT has no timezone), logs store local time often without offset, applications use varied epochs/precision. Developers naively `datetime.fromtimestamp()` (which applies the *local* tz of the analysis machine) instead of `fromtimestamp(ts, tz=UTC)`. Suspect-system clock skew (drift, manual changes, VM snapshot reverts) is ignored entirely.

**How to avoid:**
- **Store and reason about everything in UTC internally.** Convert to display timezone only at the presentation edge, and always render with an explicit offset (`2026-05-30T14:00:00+00:00`), never a bare local time.
- Use timezone-aware `datetime` objects exclusively. Ban naive `datetime.fromtimestamp(ts)` (local-tz) — require explicit `tz`.
- Record the **source timezone assumption** per artifact class and surface it in the report. FAT timestamps and many logs are local-time-without-offset — flag that the offset is *assumed*, not known.
- Capture and let the operator supply a **clock-skew offset** for the suspect system (and the evidence timezone), apply it consistently, and document it in the report. Never silently assume the suspect clock was correct.
- Correctly label MAC(B) semantics per filesystem and never overclaim ("modified" ≠ "user edited content"; many actions touch mtime/atime non-obviously). Document what each time means for the specific filesystem.

**Warning signs:**
- Any `datetime.fromtimestamp()` without a `tz=` argument.
- Naive datetimes anywhere in the timeline pipeline.
- Report shows times with no timezone offset.
- No place for operator to specify evidence timezone or clock skew.

**Phase to address:** Timeline phase — but enforce UTC-everywhere from the first metadata-extraction phase, because retrofitting timezone-awareness across a timeline is a rewrite.

---

### Pitfall 5: False confidence in deleted-file recovery

**What goes wrong:**
The tool presents carved/recovered files as if they are intact, authentic, and complete — when the data may be partially overwritten, recovered from stale metadata, or carved with no filesystem context. On ext4 specifically, deletion **zeroes the inode's block pointers / extent tree**, so the inode→data mapping that recovery depends on is gone; "recovery" then relies on the journal or signature carving, both of which can yield wrong, truncated, or wrongly-attributed data. Presenting these as solid findings invites a devastating cross-examination.

**Why it happens:**
TSK makes it easy to dump "deleted" entries; tutorials show it working on a freshly-deleted file. Developers generalize that to "we recover deleted files," not understanding that ext4's behavior differs sharply from NTFS (which keeps the $MFT record and run-list longer) or FAT. Carving (signature-based, e.g. PhotoRec-style) recovers *bytes that look like a file* with no proof they form one coherent original file.

**How to avoid:**
- Be **filesystem-explicit**: document recovery confidence per filesystem. ext4 deleted-inode recovery is unreliable because block pointers are wiped — prefer journal-based recovery and label it as such. NTFS/FAT have different, better-but-still-caveated behavior.
- Distinguish three recovery classes in the report with different confidence tiers: (a) **metadata-intact recovery** (inode/MFT entry still maps to blocks), (b) **journal/transaction recovery**, (c) **signature carving** (no filesystem context — lowest confidence, may be fragmented/false-positive).
- Detect and flag overwriting: if recovered blocks are now allocated to another file, say so. Never present a partial/overwritten file as complete.
- Verify carved files (header+footer present, parseable as the claimed type) and report verification status — don't claim a recovered JPEG is valid if it won't decode.
- Never assert "this is the file the user deleted" — assert "data consistent with X was recovered from [location] via [method] with [confidence]."

**Warning signs:**
- Recovery code path identical across all filesystems.
- Report lists recovered files with no method/confidence/filesystem annotation.
- Carved files presented as equivalent to metadata-recovered files.

**Phase to address:** Deleted-file recovery phase — confidence tiering and per-filesystem caveats must be part of the recovery design, not bolted on at reporting.

---

### Pitfall 6: Unsafe parsing of untrusted evidence (the tool attacks itself)

**What goes wrong:**
Evidence is adversarial input. Extracting archives found in the image without protection enables **Zip Slip / path traversal** (an entry named `../../etc/cron.d/x` writes outside the output jail and can compromise the analysis host), **zip bombs / decompression bombs** (exhaust disk/RAM/CPU and crash the run), **symlink traversal** during extraction, malicious filenames (control chars, `..`, absolute paths, extreme lengths), and resource exhaustion from crafted filesystem structures (cyclic directory entries, billion-laughs-style nesting). A forensic tool that can be subverted by the evidence it examines is both a security hole and a soundness failure.

**Why it happens:**
Naive use of `zipfile.extractall()`, `tarfile.extractall()`, or writing extracted names directly to disk. The mental model is "I'm reading data," but extraction *writes* attacker-controlled paths. Resource limits are an afterthought.

**How to avoid:**
- **Never** use `extractall()` on untrusted archives. Normalize each member path, reject `..`, absolute paths, and anything resolving outside a dedicated jail directory; verify the resolved real path is within the jail before writing. (Python 3.12+ `tarfile` has `filter='data'`; still validate.)
- Enforce limits: max uncompressed size, max compression ratio (bomb detection), max member count, max nesting depth, max single-file size, total output cap. Abort with a logged reason on violation rather than crashing.
- Sanitize filenames on extraction; preserve the *original* name as metadata (it's evidence) but write to a safe sanitized name.
- Don't follow symlinks during extraction; never let extraction escape the jail via symlink.
- Run analysis under resource limits (memory/CPU/disk cgroup or `resource` rlimits), and consider least-privilege / sandboxing for parsers. Process untrusted parsers defensively — assume any parser can be fed a malicious file.
- Wrap every parser in error isolation so one malformed artifact doesn't abort the whole run (but log it as a finding).

**Warning signs:**
- `extractall()` anywhere in the codebase.
- Extraction writes member names without path normalization/jailing.
- No size/ratio/depth limits on decompression.
- A single malformed file aborts the entire analysis.

**Phase to address:** Foundation/ingestion phase for the extraction jail and resource limits; reinforced in every parser phase (log parsing, archive handling). This is a security gate that should block phase completion.

---

## Moderate Pitfalls

### Pitfall 7: Log-parsing naïveté (tampering, rotation, locale, gaps)

**What goes wrong:**
Logs are treated as ground truth and parsed assuming a single, complete, well-formed stream. Reality: logs can be tampered/truncated, are rotated and compressed (`.1`, `.gz`, `.xz`), span DST changes, use locale-dependent month names, have inconsistent/missing year fields (classic syslog `Mon DD HH:MM:SS` has no year), and may simply be incomplete. Conclusions drawn from "the logs show nothing" are unsound when the logs were rotated away or wiped.

**How to avoid:**
- Handle rotated + compressed logs explicitly (`.gz`, `.xz`, `.bz2`); reassemble rotation sets in correct order.
- Don't assume a year — infer from file mtime/surrounding context and flag the assumption; handle year rollover across rotated files.
- Parse with explicit locale/timezone handling; syslog timestamps are local-time without offset.
- Detect tampering signals: gaps in sequence/time, truncation, out-of-order entries, last-entry-before-incident — and report log completeness as a *finding*, not a silent assumption.
- Never conclude absence of an event from a log that may be incomplete; state "not present in available logs."

**Warning signs:** Parser only reads the live log, not rotated/compressed siblings; year hard-coded or assumed; no gap/tamper detection.

**Phase to address:** Log parsing phase.

---

### Pitfall 8: pytsk3 / libtsk build, version, and filesystem-support gaps

**What goes wrong:**
Build/install pain and silent capability gaps. Multiple SleuthKit versions on one host cause pytsk3 to reference struct members that don't exist (pytsk3.c was generated for a different libtsk). TSK doesn't support every filesystem fully (APFS support is partial — encryption notably incomplete; LUKS/dm-crypt and BitLocker volumes aren't decrypted by TSK; some FS only partially). Encoding issues on filenames (UTF-16/NTFS, non-UTF-8 names) cause crashes or mojibake. Large images stress memory and runtime.

**How to avoid:**
- Pin pytsk3 (modern wheels bundle libtsk, so usually no separate libtsk build needed) and pin/record the TSK version in the manifest. Document the supported-filesystem matrix and **fail clearly** on unsupported/encrypted volumes ("encrypted volume detected — cannot analyze") rather than producing empty/garbage results.
- Ensure a single TSK version in the build/runtime env; if building from source, delete stale `pytsk3.c` so it regenerates for the installed libtsk.
- Treat filenames as bytes that may not be valid UTF-8; decode defensively (`errors='surrogateescape'` / explicit codepage handling), never assume UTF-8, and preserve raw bytes for evidence fidelity.
- Detect encrypted/unsupported filesystems early and report them as a known-limitation finding.

**Warning signs:** Struct-member AttributeErrors from pytsk3; empty results on an image that clearly has data (often = unsupported/encrypted FS); UnicodeDecodeError on filenames; TSK version not recorded.

**Phase to address:** Ingestion phase (FS detection + version pinning + capability matrix); revisited in metadata phase (encoding).

---

### Pitfall 9: Ignoring slack and unallocated space — or mishandling it

**What goes wrong:**
Either the tool ignores file slack and unallocated space entirely (missing evidence that lives precisely there), or it dumps them without context and presents fragments as meaningful files. Slack/unallocated content has no filesystem provenance — it's residual bytes.

**How to avoid:** Provide access to slack/unallocated as a distinct, clearly-labeled data class; carve from it with the low-confidence labeling from Pitfall 5; never attribute unallocated fragments to a specific file/user without evidence.

**Phase to address:** Recovery/carving phase.

---

### Pitfall 10: Overclaiming in the report (defensibility failure)

**What goes wrong:**
The report states conclusions the data can't support: "the user deleted this file," "the suspect accessed X at 14:00," "this proves intent." Forensic reports must distinguish observed artifacts from interpretation. Overclaiming is the fastest way to get a report (and analyst credibility) discredited.

**How to avoid:**
- Report **artifacts and methodology**, with interpretation clearly separated and hedged. "File metadata indicates mtime of X (UTC, assuming clock accuracy); this is consistent with but does not prove a user edit."
- Every finding carries: source location (offset/inode/log+line), method/tool+version, hash, confidence level, and stated assumptions (timezone, clock skew, recovery method).
- Include an explicit **methodology + limitations section** and the tool/TSK versions — reproducibility and disclosed limitations are what make a report defensible (Daubert-style reliability).
- Never imply court-admissibility; state that admissibility is the investigator's determination (matches PROJECT.md out-of-scope).

**Warning signs:** Findings phrased as conclusions about human intent/action; no per-finding provenance/confidence; no limitations section.

**Phase to address:** Reporting phase (design the finding schema to *force* provenance + confidence + assumptions on every entry).

---

## Minor Pitfalls

### Pitfall 11: Legal/ethical scope creep
The tool should never operate outside authorized scope or claim more than "analysis aid." Don't auto-exfiltrate, don't phone home, don't bypass/crack encryption (out of scope + legally fraught), and surface privacy-sensitive content (PII) carefully. Record operator/authorization metadata in the manifest. *Phase:* cross-cutting; capture authorization fields at ingestion.

### Pitfall 12: No audit log of the tool's own actions
A forensic tool that can't say what *it* did is hard to defend. Log every operation (files read, methods run, errors, decisions) to an immutable run log included with output. *Phase:* foundation (logging framework).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `mount -o loop` instead of TSK byte-read | Fast to code, familiar APIs | Modifies evidence; invalidates soundness; full rewrite | **Never** |
| MD5-only hashing | One line, matches old tutorials | Broken collision resistance; weak integrity story | Only as *additional* hash alongside SHA-256 |
| `zipfile/tarfile.extractall()` | One-liner extraction | Zip Slip + zip bomb RCE/DoS on analysis host | **Never** on untrusted evidence |
| Naive `datetime.fromtimestamp()` | Simpler timeline code | Applies analysis-host tz; wrong timeline | **Never** — always tz-aware UTC |
| Filesystem-agnostic recovery path | Less code | False confidence on ext4; wrong/incomplete files | Only with explicit per-FS confidence labeling |
| Load whole image/structures into RAM | Simple | OOM on multi-TB images | Small fixtures only; never on real evidence |
| Skip rotated/compressed logs | Faster log phase | Missed events; "absence" claims unsound | Never for evidentiary conclusions |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| pytsk3 / libtsk | Multiple TSK versions → struct mismatch; assuming all FS supported | Single pinned TSK; bundled-libtsk wheel; FS capability matrix; record version |
| The image/source | `mount`, writable loop device, atime updates | TSK `Img_Info`→`FS_Info` read-only byte access; never mount source |
| Encrypted volumes (LUKS/BitLocker/APFS-encrypted) | Empty/garbage output silently | Detect + report "encrypted — not analyzable"; don't pretend |
| Archives inside evidence | `extractall()` | Path-jailed, size/ratio/depth-limited, symlink-safe extraction |
| Filenames (NTFS UTF-16, non-UTF-8) | Assume UTF-8 → crash/mojibake | Bytes-first decode with surrogateescape; preserve raw bytes |
| Syslog/journald logs | Assume year, UTC, single file | Infer year, local-tz w/ offset flag, reassemble rotated+compressed sets |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Reading the image multiple times (hash, then analyze, then carve) | Runtime scales N× image size | Single streaming pass: hash + walk together | Noticeable at hundreds of GB; painful at multi-TB |
| Holding file list / timeline fully in RAM | Memory grows with file count; OOM | Stream to disk-backed store (SQLite/embedded DB); generators not lists | Millions of inodes / multi-TB |
| Naïve carving over all unallocated space single-threaded | Hours-to-days runtime | Bounded, parallel, order-independent carving with progress + checkpointing | Large unallocated regions on big disks |
| No resume/checkpoint | A crash 12h in restarts from zero | Checkpoint per phase; resumable runs | Any multi-TB job |
| Per-file Python overhead in the FS walk | Slow on filesystems with millions of entries | Batch, minimize per-entry Python work, profile hot loop | Filesystems with very high file counts |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| `extractall()` on evidence archives | Zip Slip → write outside jail → host compromise | Path normalization + jail + reject `..`/absolute |
| No decompression limits | Zip bomb → disk/RAM/CPU exhaustion, crash | Max size/ratio/depth/count caps; abort+log |
| Following symlinks during extraction | Escape jail, overwrite host files | Don't follow symlinks; resolve+verify within jail |
| Trusting filenames from evidence | Control chars, traversal, overlong names break tooling | Sanitize to safe write-name; keep original as metadata |
| Running parsers with full privileges | Malicious file → code exec with operator rights | Least privilege, rlimits/cgroups, parser isolation |
| One bad artifact aborts the run | DoS via single crafted file; lost analysis | Per-artifact error isolation; log as finding, continue |
| Tool phones home / writes outside output dir | Data leakage; scope/authorization violation | No network egress; all writes confined to output dir |

## "Looks Done But Isn't" Checklist

- [ ] **Evidence ingestion:** Often missing read-only enforcement — verify no `mount`/write touches source and pre/post hashes match.
- [ ] **Hashing:** Often missing SHA-256 + comparison — verify image hashed before *and* after, compared, and every finding carries a hash.
- [ ] **Timeline:** Often missing tz-awareness — verify all internal times are UTC tz-aware, display has explicit offset, and operator can set evidence tz + clock skew.
- [ ] **Recovery:** Often missing per-filesystem confidence — verify ext4 vs NTFS vs carving are labeled with method + confidence, overwriting detected.
- [ ] **Archive/log extraction:** Often missing jail + limits — verify no `extractall()`, traversal rejected, zip-bomb limits enforced.
- [ ] **Reporting:** Often missing methodology/limitations + tool versions — verify report states TSK/tool version, methodology, limitations, and no overclaiming.
- [ ] **Reproducibility:** Often missing — verify two runs on a fixture produce identical analytical output.
- [ ] **Audit log:** Often missing — verify the tool records its own actions in the output.

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Evidence modified during analysis | HIGH | Discard run; re-acquire/re-hash original; audit and fix every write path; never reuse the touched copy |
| Mounting used instead of TSK read | HIGH | Replace mount-based ingestion with TSK byte-layer; re-run on pristine copy |
| Wrong/missing hashing | MEDIUM | Add SHA-256 + before/after compare; re-run on original; re-hash all findings |
| Timezone bug in timeline | MEDIUM | Make all datetimes tz-aware UTC; reprocess; reissue corrected timeline noting prior error |
| Overclaimed findings | MEDIUM | Re-template report to artifact+method+confidence; add limitations section; reissue |
| Zip Slip / bomb hit during dev | LOW (if caught early) | Replace `extractall()` with jailed limited extractor; add regression tests with malicious fixtures |
| Non-reproducible output | LOW–MEDIUM | Sort all output; segregate run metadata; add reproducibility CI test |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Modifying evidence (P1) | Foundation / Ingestion | No `mount`/writes to source in code audit; pre/post image hash match |
| Missing/wrong hashing (P2) | Ingestion + Reporting | SHA-256 before+after compared; every finding has a hash |
| Non-reproducible output (P3) | Reporting (enforced all phases) | Two-run fixture diff is identical (CI test) |
| Timezone/MAC/skew (P4) | Metadata + Timeline | All times tz-aware UTC; explicit offset in output; operator tz/skew inputs |
| False recovery confidence (P5) | Recovery | Per-FS method+confidence labels; overwrite/validation flags present |
| Unsafe untrusted parsing (P6) | Foundation + every parser phase | No `extractall()`; traversal+bomb regression tests pass |
| Log-parsing naïveté (P7) | Log parsing | Rotated/compressed handled; year/tz/gap handling; completeness reported |
| pytsk3/TSK build+FS gaps (P8) | Ingestion | TSK version pinned+recorded; FS matrix; encrypted/unsupported reported, not silent |
| Slack/unallocated mishandling (P9) | Recovery/Carving | Distinct labeled data class; low-confidence carving labels |
| Overclaiming in report (P10) | Reporting | Finding schema forces provenance+confidence+assumptions; limitations section exists |
| Legal/ethical scope (P11) | Cross-cutting (Ingestion intake) | Authorization metadata captured; no network egress; no decryption attempts |
| No self-audit log (P12) | Foundation | Run log present in output covering all operations |

## Sources

- pytsk Building & Troubleshooting wiki (multi-version libtsk struct mismatch, bundled libtsk): https://github.com/py4n6/pytsk/wiki/Building , https://github.com/py4n6/pytsk/wiki/Troubleshooting
- pytsk3 on PyPI: https://pypi.org/project/pytsk3/
- The Sleuth Kit supported filesystems & description: https://www.sleuthkit.org/sleuthkit/desc.php
- APFS support is partial / encryption incomplete in TSK: https://dfrws.org/wp-content/uploads/2019/06/pres_adding_apfs_support_to_the_sleuthkit_framework.pdf , https://cellebrite.com/en/a-present-from-santa-apfs-providing-apfs-support-to-the-sleuth-kit-framework/
- ext4 deletion wipes inode block pointers (recovery difficulty): https://www.slashroot.in/how-does-file-deletion-work-linux , https://ext4magic.sourceforge.net/inode_en.html
- Timestamp/timezone/MAC-time/clock-skew interpretation (anomalies usually = misinterpretation): https://www.sciencedirect.com/science/article/pii/S2666281724000787 , https://aliascybersecurity.com/blog/why-time-is-one-of-the-hardest-problems-in-digital-forensics/ , https://idsinc.com/time-zones/
- Zip Slip / path traversal: https://medium.com/@ibm_ptc_security/zip-slip-attack-e3e63a13413f , https://developer.android.com/privacy-and-security/risks/zip-path-traversal
- Zip bombs / decompression bombs: https://en.wikipedia.org/wiki/Zip_bomb
- Forensic archive analysis best practices (jail, normalize, limits): https://ziptoolkit.com/blog/13
- Daubert / admissibility / reproducibility / tool validation for open-source forensic tools: https://pmc.ncbi.nlm.nih.gov/articles/PMC12431127/ , https://jmids.avestia.com/2021/005.html

---
*Pitfalls research for: automated TSK/pytsk3-based digital forensic analysis tooling (PyAutopsy)*
*Researched: 2026-05-30*
