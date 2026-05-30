# Feature Research

**Domain:** Automated digital forensic analysis (disk + log) — Python/Linux CLI on The Sleuth Kit
**Researched:** 2026-05-30
**Confidence:** MEDIUM-HIGH (forensic feature landscape is mature and well-documented; pytsk3-specific filesystem limits are MEDIUM and need a build-time spike to confirm)

## Feature Landscape

A forensic tool is judged against an established de-facto feature set defined by Autopsy/TSK, plaso, X-Ways and EnCase. "Table stakes" here means *missing it makes the output non-credible as forensic tooling*, not merely incomplete. Differentiators are where an *automated Python CLI* (vs the Autopsy GUI) wins: repeatability, structured output, scriptability.

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Ingest disk image read-only (raw/dd, E01/EWF) | Evidence must never be mutated; raw+E01 are the universal formats | MEDIUM | pytsk3 `Img_Info` handles raw; E01 needs `pyewf` wrapped as an Img_Info handle. Open O_RDONLY; never mount the source. HIGH confidence. |
| Source image hash verification (MD5 + SHA-256) | Proves the image analyzed == image acquired; cornerstone of integrity | LOW | Hash the whole image stream once; compare to acquisition hash if provided. MD5 retained for legacy interop, SHA-256 as primary. |
| Filesystem walk + full file metadata | The core forensic primitive — inventory every inode/file | MEDIUM | pytsk3 `FS_Info` + `walk`. Extract path, size, allocated/unallocated flag, inode/MFT addr. |
| MAC(B) timestamps per file | Timeline and "what happened when" depend on these | MEDIUM | Capture **all four**: Modified, Accessed, Changed (ext) / Created (NTFS $SI), Born/Created. Record timezone + source ($STANDARD_INFO vs $FILENAME on NTFS). Note resolution differs per FS. |
| Ownership & permissions (UID/GID, mode bits) | Attribution — links files to users/actions | LOW | From inode metadata. On ext also flags (immutable etc.). |
| File type identification (signature, not extension) | Detects renamed/disguised files (anti-forensics) | MEDIUM | libmagic / `python-magic` on file content. Compare detected type vs extension to flag mismatches. |
| Per-file hashing (MD5/SHA-1/SHA-256) | Dedup, known-file filtering, exhibit identification | LOW | Hash file content during walk. SHA-256 primary; MD5/SHA-1 for hash-set interop. |
| Known-file filtering via NSRL RDS | Standard data reduction — suppress OS/app files so analysts see user data | MEDIUM | Match file hashes against NSRL RDS (now "RDS Modern", SQLite/minimal sets). RDS says *known*, not good/bad — surface as "known system file" filter, not a verdict. Allow custom allowlist/blocklist hash sets. |
| Deleted file enumeration & recovery | The headline forensic capability; what investigators come for | MEDIUM | TSK exposes unallocated metadata entries (`fls -d`, inode still intact). Recover content where data units not yet overwritten. Distinguish "recovered intact" vs "partial/overwritten". |
| Orphan file handling | Deleted files whose parent dir is gone still hold evidence | MEDIUM | TSK `$OrphanFiles` virtual dir. Report separately — no path context. |
| File carving from unallocated space | Recovers files with no remaining metadata (fully unlinked) | HIGH | Signature/header-footer carving over unallocated blocks. Wrap `photorec`/`scalpel`/`foremost` rather than reimplement. Fragmented-file recovery is the hard part — set expectations. |
| Log parsing of forensically-relevant Linux logs | Linux is the target platform; logs are half the evidence story | MEDIUM | See log table below. Parse from the *image's* `/var/log`, not the host's. |
| Timeline construction (bodyfile/MACtime style) | Reconstructing event sequence is the central analytic deliverable | MEDIUM | Emit TSK-style bodyfile, render `mactime`-equivalent chronological timeline from FS metadata. |
| Super-timeline (FS metadata + log events merged) | Modern standard set by plaso — one chronological view across sources | HIGH | Normalize FS MACB events + parsed log events into one time-sorted stream with (timestamp, source, type, description, evidence-ref). Optionally shell out to plaso. |
| Keyword / string search | Finding specific evidence (names, IOCs, strings) is fundamental | MEDIUM | Search allocated + unallocated + file content. Regex + literal. Slow without an index — see differentiators. |
| Hash lookup / IOC matching | Match against known-bad hash lists and indicators | LOW-MEDIUM | Hash sets (custom/NSRL), plus IP/URL/email/hash IOC lists. Report hits with file + offset. |
| Chain-of-custody / case metadata record | Without it the output is not defensible evidence | LOW | Case ID, examiner, evidence ID, acquisition source, tool+versions, timestamps. Carried into the report. |
| Audit log of tool actions | Reproducibility & defensibility — what the tool did, when | LOW | Append-only run log: inputs, hashes, parameters, tool versions, start/end times, errors. |
| Read-only / non-modification guarantee | Forensic soundness is non-negotiable; a tool that writes to evidence is unusable | LOW-MEDIUM | Open evidence O_RDONLY; all output to a separate case directory; verify source hash unchanged at end. Document as a guarantee. |
| Human-readable report (case info, methodology, findings, hashes, timestamps, exhibits) | The actual product deliverable for evidence presentation | MEDIUM | HTML/PDF + Markdown. Sections: case/COC, methodology+tool versions, findings, evidence hashes, timeline, exhibits, appendices. Neutral language, no interpretation. |

### Differentiators (Competitive Advantage)

These align directly with Core Value ("repeatable, scriptable pipeline producing consistent reports") and are where a CLI beats the Autopsy GUI.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Single-command automated pipeline | Replaces dozens of manual Autopsy GUI clicks; consistent every run | MEDIUM | `pyautopsy analyze image.E01 --case ...` → full report. The headline differentiator. |
| Deterministic / repeatable output | Same image → same report (modulo timestamps); reviewable in court | MEDIUM | Stable ordering, pinned tool versions in report, no nondeterministic iteration. Directly supports defensibility. |
| Structured machine-readable output (JSON) | Feeds SIEM/SOAR/downstream tooling; enables diffing & automation | LOW-MEDIUM | Emit JSON alongside the human report. **Strongly consider CASE/UCO** (the cyber-investigation ontology standard) for interoperability — even partial conformance is a differentiator. |
| Scriptability / config-driven runs | Investigators codify standard operating procedures as config | LOW | YAML/TOML case config: which parsers, hash sets, keyword lists, carving on/off. Reproducible recipes. |
| Declarative keyword/IOC/YARA rule packs | Reusable, shareable detection content across cases | MEDIUM | Load keyword lists, IOC files, and optionally YARA rules; report all hits with provenance. |
| Search indexing | Makes keyword search fast on large images (Autopsy uses Solr) | HIGH | Optional full-text index. Defer to v2 — large effort; literal/regex scan is acceptable for v1. |
| Timeline anomaly surfacing | Auto-flag timestomping, MACB inconsistencies, out-of-order events | MEDIUM | E.g. $SI vs $FN mismatch on NTFS, future timestamps, mass-modification windows. High analyst value, low extra cost on top of timeline. |
| Mismatch & suspicious-file flagging | Extension-vs-content mismatch, files in unusual locations, hidden files | LOW-MEDIUM | Cheap heuristics layered on metadata already collected. |
| Diffable reports across runs/images | Track changes between two images or two analyses | MEDIUM | Falls out of structured JSON output. Useful for incident timelines. |

### Anti-Features (Commonly Requested, Often Problematic)

Each maps to PROJECT.md "Out of Scope" — documented here to prevent scope creep.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Live / memory forensics (RAM capture, running-process analysis) | "Full" IR coverage | Entirely different acquisition model + tooling (Volatility, LiME); not disk/log; huge scope | Out of scope v1. Disk + log only. Point users to Volatility for memory. |
| Malware sandboxing / dynamic analysis / RE | "Tell me if it's malicious" | Requires isolated execution env, behavioral instrumentation; safety/scope explosion; verdicts aren't forensic facts | YARA/IOC static matching only (report *indicators*, not verdicts). Refer out for behavioral analysis. |
| Network / packet forensics (PCAP) | Complete incident picture | Separate domain (Wireshark/Zeek/Suricata); different data model | Out of scope. Parse network-related *host logs* only. |
| GUI / web interface | Easier for non-CLI users | Autopsy already provides a mature GUI; duplicating it abandons the CLI/automation differentiator | CLI + structured output; let other tools build UIs on the JSON. |
| Court-admissibility certification / legal verdicts | "Is this admissible / who's guilty?" | Legal determination is the investigator's & court's job; tool overreach undermines credibility | Produce defensible *factual* findings + COC; explicitly disclaim legal conclusions. |
| Windows/macOS host support (running the tool there) | Broader user base | Splits platform effort; v1 targets Linux host | Linux host only. (Note: *analyzing* Windows/macOS *images* is a separate, valid future axis — see below.) |
| Auto "this user is guilty / this is the smoking gun" conclusions | Analysts want answers | Forensic reports must be neutral and factual; interpretation invites bias challenges | Surface evidence + flags; leave conclusions to the human examiner. |
| Reimplementing TSK carving/parsing primitives | "Pure Python, no deps" | TSK is the trusted, court-tested implementation; reimplementation forfeits credibility and correctness | Wrap TSK/pytsk3, photorec/scalpel, plaso — orchestrate, don't reinvent. |

## Feature Dependencies

```
Read-only image ingest (raw/dd, E01)
    └──requires──> Source image hash verification
    └──enables───> Filesystem walk + metadata
                       ├──requires──> MAC(B) timestamps
                       ├──requires──> Ownership/permissions
                       ├──enables───> Per-file hashing
                       │                  ├──enables──> NSRL known-file filtering
                       │                  └──enables──> Hash lookup / IOC matching
                       ├──enables───> File type ID (signature)
                       │                  └──enables──> Extension/content mismatch flagging
                       ├──enables───> Deleted file enumeration ──> Orphan file handling
                       └──enables───> Timeline (bodyfile/MACtime)
                                          └──requires──> merge with...
Log parsing (Linux logs)
    └──enables───> Log event normalization
                       └──requires──> ...for──> Super-timeline (FS + logs merged)
                                                     └──enhances──> Timeline anomaly surfacing

File carving (unallocated)  ──independent of metadata; needs raw block access from ingest

Case/COC metadata + Audit log  ──cross-cutting: consumed by──> Report (human + JSON)

Structured JSON output ──enables──> Diffable reports, downstream tooling
Keyword/IOC/YARA packs ──enhanced by──> Search indexing (optional, v2)
```

### Dependency Notes

- **Everything depends on read-only ingest + hash verification.** These are the foundation phase; nothing else is defensible without them.
- **Per-file hashing is a hub:** NSRL filtering, IOC matching, and exhibit identification all consume it. Compute hashes once during the walk, reuse everywhere.
- **Super-timeline requires both** the FS metadata timeline *and* normalized log events. The shared "forensic event" data model (timestamp, source, type, description, evidence-ref) must exist before either feeds the timeline — design it early.
- **Carving is independent** of the metadata pipeline (operates on raw unallocated blocks), so it can be developed/parallelized separately, but it shares the read-only ingest layer.
- **Report consumes Case/COC + Audit log + all findings** — it is necessarily the last phase, and the structured JSON model should be defined before the human renderer.
- **Anti-forensics flags** (timestomp detection, extension mismatch) are cheap *add-ons* to data already collected — low marginal cost, high analyst value.

## Forensically-Relevant Linux Logs (scope for the log parser)

| Log / artifact | Path | Events to surface | Confidence |
|----------------|------|-------------------|------------|
| Auth log (Debian) / secure (RHEL) | `/var/log/auth.log`, `/var/log/secure` | logins, SSH, sudo, PAM, failed auth, new sessions — **highest forensic value** | HIGH |
| Syslog / messages | `/var/log/syslog`, `/var/log/messages` | service start/stop, kernel, cron, errors, network | HIGH |
| systemd journal | `/var/log/journal/**` (binary) | unified events grouped by `_BOOT_ID`; reboots, services, auth | HIGH (binary format — needs a journald parser; non-trivial) |
| auditd | `/var/log/audit/audit.log` | syscall-level: file access/mod, execve, SELinux/AppArmor, config changes | MEDIUM (rich but verbose; parse if present) |
| Bash/shell history | `~/.bash_history`, `.zsh_history` | executed commands per user (tamperable — note that) | HIGH |
| wtmp/btmp/lastlog/faillog | `/var/log/{wtmp,btmp,lastlog,faillog}` | login sessions (wtmp), failed logins (btmp), last login, fail counts — binary | MEDIUM (binary, `utmp` struct parsing) |
| Web/server logs | `/var/log/{apache2,nginx,httpd}/*` | access/error logs, request sources, suspicious requests | MEDIUM (format varies; common+combined log formats) |
| Package/install logs | `/var/log/{dpkg.log,apt/history.log,yum.log,dnf.log}` | software install/remove timeline | MEDIUM |

**Surface per event:** timestamp (with TZ), source log, user/actor, action, outcome (success/fail), source IP where present. Feed all into the super-timeline.

## Filesystem & Format Support (deleted recovery / carving scope)

| Filesystem | Recovery support | Confidence | Notes |
|------------|------------------|------------|-------|
| ext2/3/4 | Metadata walk + deleted inodes | HIGH | Primary target (Linux). pytsk3 supports ext2/3/4. |
| NTFS | Walk + deleted ($MFT), $SI/$FN timestamps | HIGH | Well supported by TSK; valuable for analyzing Windows images even on a Linux host. |
| FAT12/16/32 | Walk + deleted dir entries, carving | HIGH | Long supported by TSK. |
| exFAT | Walk + deleted | MEDIUM | Support depends on bundled TSK version — **verify in build spike**. |
| HFS+ | Walk + deleted | MEDIUM | TSK supports HFS+; confirm against pytsk3's bundled libtsk. |
| APFS | Walk + deleted | LOW-MEDIUM | Added in modern TSK 4.x (pool support); pytsk3 build may lag. **Verify; treat as best-effort / defer.** |

**Recommendation:** Scope v1 recovery firmly around **ext4 + NTFS + FAT** (HIGH confidence, covers the dominant cases for a Linux-platform tool). Treat exFAT/HFS+/APFS as "supported if the linked TSK build provides it" and gate behind a capability probe at runtime rather than promising them. Image formats: **raw/dd + E01 (via pyewf)** for v1.

## MVP Definition

### Launch With (v1)

Minimum viable, end-to-end "image → defensible report" pipeline. Be ruthless: a thin vertical slice that is *forensically sound* beats a wide one that isn't.

- [ ] Read-only ingest of raw/dd + E01 — foundation; nothing works without it
- [ ] Source image hash verification (MD5 + SHA-256) — integrity is non-negotiable
- [ ] Filesystem walk + full metadata (MACB, owner, perms, size, type) on **ext4/NTFS/FAT** — the core primitive
- [ ] Per-file hashing — hub feature feeding filtering/IOC/exhibits
- [ ] NSRL known-file filtering + custom hash sets — credible data reduction
- [ ] Deleted file enumeration & recovery (+ orphan files) — the headline capability
- [ ] Linux log parsing: auth.log/secure, syslog, bash history (start with HIGH-confidence text logs) — half the evidence
- [ ] Timeline + super-timeline (FS metadata + parsed logs in one chronological view) — central deliverable
- [ ] Keyword + IOC/hash matching — fundamental search
- [ ] Case/COC metadata + audit log — makes output defensible
- [ ] Report: human-readable (HTML/MD) **and** structured JSON — the actual product
- [ ] Single-command automated pipeline — the differentiator that justifies the tool

### Add After Validation (v1.x)

- [ ] File carving from unallocated (photorec/scalpel wrapper) — high value but high effort; add once core pipeline is trusted. *Trigger: core report validated by a real examiner.*
- [ ] journald (binary) + auditd + wtmp/btmp parsers — extends log coverage. *Trigger: text-log timeline proven useful.*
- [ ] Timeline anomaly / timestomp surfacing + extension-mismatch flagging — cheap analyst-value add-ons. *Trigger: timeline in active use.*
- [ ] YARA rule pack support — *Trigger: IOC matching demand grows.*
- [ ] CASE/UCO-conformant JSON export — *Trigger: downstream-integration demand.*

### Future Consideration (v2+)

- [ ] Full-text search indexing — large effort; defer until image sizes/keyword volume demand it
- [ ] exFAT/HFS+/APFS recovery — depends on TSK build; defer until needed
- [ ] Web/server + package log parsers — defer until use cases appear
- [ ] Report diffing across images/runs — depends on stable JSON schema
- [ ] plaso integration as an alternative timeline backend — defer; native timeline first

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Read-only ingest (raw/E01) + hash verify | HIGH | MEDIUM | P1 |
| FS walk + MACB/owner/perms metadata | HIGH | MEDIUM | P1 |
| Per-file hashing | HIGH | LOW | P1 |
| Deleted file recovery + orphans | HIGH | MEDIUM | P1 |
| Linux log parsing (auth/syslog/bash) | HIGH | MEDIUM | P1 |
| Timeline + super-timeline | HIGH | HIGH | P1 |
| Case/COC + audit log | HIGH | LOW | P1 |
| Human + JSON report | HIGH | MEDIUM | P1 |
| Single-command pipeline | HIGH | MEDIUM | P1 |
| NSRL known-file filtering | HIGH | MEDIUM | P1/P2 |
| Keyword + IOC/hash matching | HIGH | MEDIUM | P2 |
| File type ID (signature) + mismatch flag | MEDIUM | LOW-MEDIUM | P2 |
| File carving (unallocated) | HIGH | HIGH | P2 |
| Timeline anomaly / timestomp surfacing | MEDIUM | MEDIUM | P2 |
| journald/auditd/wtmp parsers | MEDIUM | MEDIUM-HIGH | P2 |
| YARA rule packs | MEDIUM | MEDIUM | P3 |
| CASE/UCO JSON conformance | MEDIUM | MEDIUM | P3 |
| Full-text search indexing | MEDIUM | HIGH | P3 |
| exFAT/HFS+/APFS recovery | LOW-MEDIUM | MEDIUM | P3 |

## Competitor Feature Analysis

| Feature | Autopsy / TSK | plaso (log2timeline) | X-Ways / EnCase | Our Approach (PyAutopsy) |
|---------|---------------|----------------------|-----------------|--------------------------|
| Filesystem walk / deleted recovery | Core (libtsk) | Via dfvfs | Core, broad FS | Wrap TSK via pytsk3 (ext4/NTFS/FAT v1) |
| Super-timeline | Basic timeline view | Best-in-class | Built-in | Native FS+log merge; optional plaso backend |
| Known-file filtering (NSRL) | Yes (hash DB) | N/A | Yes | NSRL RDS + custom hash sets |
| File carving | PhotoRec module | No (timeline focus) | Yes | Wrap photorec/scalpel (v1.x) |
| Keyword search | Solr index | No | Indexed | Literal/regex v1, index v2 |
| Structured/JSON output | Limited | Yes (storage + output mods) | Limited (reports) | **First-class JSON + CASE/UCO** (differentiator) |
| Automation / scriptability | GUI-first (some CLI) | CLI/scriptable | GUI-first | **CLI-first, single-command, config-driven** (differentiator) |
| Chain of custody / case mgmt | Case DB | N/A (engine) | Case mgmt | COC metadata + audit log baked into report |
| Reporting for presentation | HTML/Excel reports | Output formats only | Strong reports | Human (HTML/MD) + JSON, methodology+hashes+exhibits |
| Platform | Java GUI, cross-platform | Python, cross-platform | Windows | **Linux CLI** (focused) |

## Sources

- [The Sleuth Kit + Autopsy complete platform overview — TezGeek](https://www.tezgeek.com/2025/07/the-sleuth-kit-autopsy-complete-digital.html?m=1)
- [Sleuth Kit command-line forensic tools — TezGeek](https://www.tezgeek.com/2025/07/sleuth-kit-powerful-collection-of.html)
- [Autopsy digital forensics platform — cybersources](https://cybersources.hashnode.dev/autopsy)
- [plaso / log2timeline GitHub](https://github.com/log2timeline/plaso)
- [Plaso documentation (readthedocs)](https://plaso.readthedocs.io/)
- [A Deep Dive into Plaso/Log2Timeline — cyberengage](https://www.cyberengage.org/post/a-deep-dive-into-plaso-log2timeline-forensic-tools)
- [National Software Reference Library (NSRL) — NIST](https://www.nist.gov/itl/ssd/software-quality-group/national-software-reference-library-nsrl)
- [A more efficient NSRL for digital forensics — DFIRScience](https://dfir.science/2022/02/A-more-efficient-NSRL-for-digital-forensics)
- [National Software Reference Library — forensics.wiki](https://forensics.wiki/national_software_reference_library/)
- [Linux Log File Forensics (syslog/auth.log/journal) — kandibrian](https://kandibrian.com/articles/linux-log-forensics-syslog-authlog-journal.html)
- [7 essential Linux forensics artifacts — Magnet Forensics](https://www.magnetforensics.com/blog/linux-forensics-artifacts-every-investigator-should-know/)
- [Log Sources for Digital Forensics: Windows and Linux — LetsDefend](https://letsdefend.io/blog/log-sources-for-digital-forensics-windows-and-linux)
- [Top File Carving Tools — Cyber Forensics Academy](https://www.cyberforensicacademy.com/blog/top-file-carving-tools-for-data-recovery-in-investigations)
- [pytsk3 forensic evidence container recipes — Packt](https://hub.packtpub.com/working-forensic-evidence-container-recipes/)
- [Automating DFIR: programming libtsk with Python — HECF Blog](https://www.hecfblog.com/2015/05/automating-dfir-how-to-series-on.html)
- [pytsk GitHub (py4n6/pytsk)](https://github.com/py4n6/pytsk)
- [The Cornerstone of Digital Evidence: Integrity with Hash Values — Granite Discovery](https://www.granitediscovery.com/2025/09/08/the-cornerstone-of-digital-evidence-ensuring-integrity-with-hash-values/)
- [Chain of Custody in Digital Evidence Handling — Censinet](https://censinet.com/perspectives/chain-of-custody-digital-evidence-handling)
- [Forensic Report Writing Guide — legalexperts.ai](https://www.legalexperts.ai/knowledge-base/forensic-report-writing-guide)
- [iocextract — InQuest GitHub](https://github.com/InQuest/iocextract)

---
*Feature research for: automated digital forensic analysis (PyAutopsy)*
*Researched: 2026-05-30*
