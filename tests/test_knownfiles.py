"""RED Wave-0 scaffold for known-file filtering (FILTER-01).

These stubs pin the exact pytest node IDs from 04-VALIDATION.md for the NSRL +
custom-hash-set matching slice. They reference the (not-yet-existing) ``filter``
package — ``filter.nsrl`` (read-only NSRL membership) and ``filter.hashsets``
(custom allow/block parsing + match) — so each test FAILS until Wave 2 builds
them. The not-yet-existing modules are imported INSIDE each test body so the file
COLLECTS cleanly (an in-body ``ImportError`` is a test failure = RED, not a
collection error).

The committed NSRL fixtures (``nsrl_minimal.db`` FILE table, ``nsrl_metadata.db``
METADATA table) store hashes UPPERCASE while the project's own ``files`` rows are
lowercase — the #1 silent-zero-match trap (Pitfall 4) these tests lock in.

No ``import pytsk3`` here: filtering is stdlib ``sqlite3`` + text parsing, NOT a
native seam (D-14 unaffected).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from pyautopsy.case import KnownMatch
from tests.fixtures import make_fixtures


def test_nsrl_membership(nsrl_minimal_db: Path) -> None:
    """FILTER-01: a known md5 (UPPERCASE in DB, lowercase in row) -> neutral known.

    The fixture stores ``NSRL_KNOWN_MD5`` UPPERCASE; the probe value is the
    project's lowercase hex. The matcher must normalize before comparing (D-37
    md5->sha1->sha256 order, Pitfall 4) and report WHICH hash column matched.
    Membership is all it reports: turning a hit into a NEUTRAL record carrying
    ``source: nsrl`` and never a good/bad verdict (D-38) belongs to the caller.
    A non-member yields no match.
    """
    from pyautopsy.filter import nsrl  # noqa: PLC0415 (RED stub)

    conn, table = nsrl.open_nsrl(str(nsrl_minimal_db))
    try:
        hit = nsrl.nsrl_match(
            conn,
            table,
            md5=make_fixtures.NSRL_KNOWN_MD5,  # lowercase, as our rows store it
            sha1=make_fixtures.NSRL_KNOWN_SHA1,
            sha256=make_fixtures.NSRL_KNOWN_SHA256,
        )
        assert hit is not None, "known NSRL member did not match (uppercase trap?)"
        # The probe answers only "which column matched" — md5 first (D-37).
        assert hit == "md5"

        # The record built from it is the NEUTRAL annotation: source + column,
        # never a good/bad/malicious verdict (D-38).
        record = KnownMatch(file_id=1, source="nsrl", matched_on=hit)
        assert record.source == "nsrl"
        assert not (
            {f.name for f in dataclasses.fields(record)}
            & {"good", "bad", "malicious", "verdict"}
        )

        miss = nsrl.nsrl_match(
            conn,
            table,
            md5=make_fixtures.NSRL_NONMEMBER_MD5,
            sha1=make_fixtures.NSRL_NONMEMBER_SHA1,
            sha256=make_fixtures.NSRL_NONMEMBER_SHA256,
        )
        assert miss is None, "a non-member hash must not match"
    finally:
        conn.close()


def test_custom_hash_sets() -> None:
    """FILTER-01: allow + block lists parse and match md5->sha1->sha256.

    The parser tolerates comment (``#``), blank, and mixed-case lines and infers
    the algorithm by hex length (32/40/64). A match carries ``source``, ``list``
    and ``sense`` (allow|block) — and never a good/bad key (D-38).
    """
    from pyautopsy.filter import hashsets  # noqa: PLC0415 (RED stub)

    # Mixed case + comments + blanks; the known md5 is given UPPERCASE on purpose.
    list_text = (
        "# a custom allow list\n"
        "\n"
        f"{make_fixtures.NSRL_KNOWN_MD5.upper()}   known_good.bin\n"
        f"   {make_fixtures.NSRL_KNOWN2_SHA256}\n"
        "# trailing comment\n"
    )
    parsed = hashsets.parse_hash_set(list_text.splitlines())

    # md5 match (case-normalized).
    matched_on = hashsets.probe_hash_set(
        parsed,
        md5=make_fixtures.NSRL_KNOWN_MD5,
        sha1=None,
        sha256=None,
    )
    assert matched_on == "md5"
    hit = hashsets.to_known_match(
        7, matched_on, list_name="my-allow-list", sense="allow"
    )
    assert hit.source == "custom"
    assert hit.list_name == "my-allow-list"
    assert hit.sense == "allow"
    # Neutrality (D-38): the record carries provenance, never a verdict.
    assert not (
        {f.name for f in dataclasses.fields(hit)}
        & {"good", "bad", "malicious", "verdict"}
    )

    # sha256 fall-through match (md5/sha1 absent in the list for this entry).
    matched_on2 = hashsets.probe_hash_set(
        parsed,
        md5=make_fixtures.NSRL_NONMEMBER_MD5,
        sha1=None,
        sha256=make_fixtures.NSRL_KNOWN2_SHA256,
    )
    assert matched_on2 == "sha256"
    hit2 = hashsets.to_known_match(
        7, matched_on2, list_name="my-block-list", sense="block"
    )
    assert hit2.sense == "block"
    assert hit2.matched_on == "sha256"

    # A hash in neither list does not match.
    assert (
        hashsets.probe_hash_set(
            parsed,
            md5=make_fixtures.NSRL_NONMEMBER_MD5,
            sha1=make_fixtures.NSRL_NONMEMBER_SHA1,
            sha256=make_fixtures.NSRL_NONMEMBER_SHA256,
        )
        is None
    )


def test_one_parser_serves_both_filtering_and_search() -> None:
    """The same parser handles a list file's lines and bare command-line hashes.

    Search used to wrap the parser in a function that joined the caller's
    already-split hashes with newlines so the parser could split them again.
    Both callers now hand it lines directly, and must get the same set.
    """
    from pyautopsy.filter import hashsets  # noqa: PLC0415

    digest = make_fixtures.NSRL_KNOWN_MD5
    from_file_text = hashsets.parse_hash_set(f"# list\n{digest.upper()}\n".splitlines())
    from_cli_args = hashsets.parse_hash_set([digest.upper()])

    assert from_file_text == from_cli_args
    assert from_cli_args["md5"] == {digest.lower()}


def test_parse_tolerance_is_preserved() -> None:
    """One malformed line never discards an examiner's whole hash set."""
    from pyautopsy.filter import hashsets  # noqa: PLC0415

    parsed = hashsets.parse_hash_set(
        [
            "# comment",
            "",
            f"{make_fixtures.NSRL_KNOWN_MD5.upper()}  file.bin   # trailing",
            "zzzznot-hex-at-all-but-32-chars!",
            "abc",  # unrecognised length
            f"  {make_fixtures.NSRL_KNOWN2_SHA256}  ",
        ]
    )
    assert parsed["md5"] == {make_fixtures.NSRL_KNOWN_MD5.lower()}
    assert parsed["sha256"] == {make_fixtures.NSRL_KNOWN2_SHA256.lower()}
    assert parsed["sha1"] == set()


def test_variant_table_discovery(nsrl_minimal_db: Path, nsrl_metadata_db: Path) -> None:
    """FILTER-01: both ``FILE`` and ``METADATA`` variants are discovered + queried.

    ``open_nsrl`` discovers the hash table from ``sqlite_master`` (minimal=FILE,
    modern=METADATA) and chooses it from a fixed allowlist — never interpolating
    user input. Both fixture variants must resolve to their table and match the
    same known member.
    """
    from pyautopsy.filter import nsrl  # noqa: PLC0415 (RED stub)

    minimal_conn, minimal_table = nsrl.open_nsrl(str(nsrl_minimal_db))
    metadata_conn, metadata_table = nsrl.open_nsrl(str(nsrl_metadata_db))
    try:
        assert minimal_table == "FILE"
        assert metadata_table == "METADATA"
        for conn, table in (
            (minimal_conn, minimal_table),
            (metadata_conn, metadata_table),
        ):
            hit = nsrl.nsrl_match(
                conn,
                table,
                md5=make_fixtures.NSRL_KNOWN_MD5,
                sha1=make_fixtures.NSRL_KNOWN_SHA1,
                sha256=make_fixtures.NSRL_KNOWN_SHA256,
            )
            assert hit == "md5", f"known member not found in {table} variant"
    finally:
        minimal_conn.close()
        metadata_conn.close()
