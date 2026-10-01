#!/usr/bin/env python3
"""Regression for the AR6014 connect-variant sweep machinery.

The sweep exists because the connect submission has several independent
unknowns and each blind single-variable guess costs a whole hardware cycle.
What this test pins is the property that makes the sweep worth flashing:

  * every attempt selects exactly one variant and says which one in the log,
  * a successful association latches that variant for the rest of the session,
  * the sweep advances on its own so one boot covers the whole table, and
  * n3ds_connvar can pin a single variant for a confirmation run.

It also checks the driver binary the device actually loads carries the sweep,
because a driver change that never reaches /n3ds/modules/ath6kl.ko has silently
burned a full test cycle here before.

The *contents* of the table have been replaced twice.  The original
auth/crypto/bssid/channel/scan table was exhausted on hardware (3 passes, ~36
attempts, zero associations); the ctrl_flags table that followed found the
association in #253 and pinned the geometry; and #257 spends the freed axes on
auth/crypto again now that association is reachable.  What each row means is
owned by test_ar6014_nwm_auth_sweep.py, and the latch condition moved there
too -- association alone is no longer the thing that latches.  This test stays
on the machinery that carries whatever table is in place.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_connect_variant_sweep.py")
CFG = (ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux"
       / "cfg80211.c")
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"

EXPECTED_VARIANTS = (
    "nwm-auth", "nwm-open", "nwm-aes", "match-done",
    "real-nwm", "nwm-user", "nwm-noflags", "nwm-nwmscan",
)


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_connect_variant_sweep_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_transform(patcher) -> None:
    """The patcher must produce the sweep from the pre-sweep source, once."""
    fixture = (
        patcher.TABLE_OLD
        + patcher.BSSID_OLD
        + patcher.CRYPTO_OLD
        + patcher.SCAN_OLD
        + patcher.LOG_OLD
        + patcher.AUTH_OLD
        + patcher.LATCH_OLD
    )
    patched = patcher.patch_cfg(fixture)
    assert patched != fixture
    assert patched.count(patcher.MARKER) == 2, (
        "one banner on the table, one on the latch")
    # Idempotent: re-running must not stack a second variant table.
    assert patcher.patch_cfg(patched) == patched


def parse_rows(body: str) -> list[list[str]]:
    """Split the variant table into rows of comma-separated fields.

    Rows can wrap across lines now that ctrl_flags may be an OR of two named
    bits, so match brace-delimited rows rather than whole source lines.
    """
    rows = re.findall(r'\{\s*("[^"]*"[^{}]*?)\}', body, re.S)
    return [[field.strip() for field in row.split(",") if field.strip()]
            for row in rows]


def assert_source(text: str) -> None:
    # One banner survives on the table; #257 replaced the latch banner with
    # its own marker when it moved the latch condition off bare association.
    assert patcher_marker_count(text) >= 1, "sweep markers drifted"

    # --- the table itself ---
    table = re.search(
        r"static const struct n3ds_connect_variant n3ds_connect_variants\[\]"
        r" = \{(.*?)\n\};", text, re.S)
    assert table, "variant table missing"
    body = table.group(1)
    names = re.findall(r'\{\s*"([^"]+)"', body)
    assert tuple(names) == EXPECTED_VARIANTS, names

    rows = parse_rows(body)
    assert len(rows) == len(EXPECTED_VARIANTS), rows
    axes = []
    for fields in rows:
        # name, the five original axes, then ctrl_flags.
        assert len(fields) == 7, fields
        axes.append(tuple(int(f) for f in fields[1:6]))
        assert fields[6], fields

    # Whichever axes the current table sweeps, at least one has to move or the
    # hardware cycle buys nothing.  Which ones, and why the rest are pinned,
    # belongs to the test that owns the table -- #253 settled bssid, channel
    # and ctrl_flags on hardware, so #257 deliberately holds them constant.
    assert any(len({row[column] for row in axes}) > 1 for column in range(5)), (
        f"no axis varies across the table: {axes}")
    # The crypto axis must still try all three wire readings.
    assert {row[1] for row in axes} == {0, 4, 8}

    # --- selection, advance, pin, latch ---
    assert "module_param(n3ds_connvar, int, 0644)" in text
    assert "n3ds_connect_attempt++" in text
    assert "n3ds_connect_attempt % ARRAY_SIZE(n3ds_connect_variants)" in text
    assert "else if (n3ds_connect_latched >= 0)" in text
    # The latch target moved from "whatever just associated" to "whatever
    # association went on to carry EAPOL"; either spelling is a real latch.
    assert ("n3ds_connect_latched = n3ds_connect_current;" in text
            or "n3ds_connect_latched = n3ds_connect_assoc_variant;" in text)
    assert "cv = &n3ds_connect_variants[n3ds_connect_current];" in text

    # A pinned variant must win over the latch, or a confirmation run silently
    # measures whatever associated first instead of the variant asked for.
    order = text.index("n3ds_connvar >= 0")
    assert order < text.index("else if (n3ds_connect_latched >= 0)")

    # --- each axis is actually consumed ---
    assert "cv->real_auth ? (AUTH_MODE)ar->arAuthMode" in text
    assert "cv->real_bssid && sme->bssid" in text
    assert "cv->crypto == 8" in text and "cv->crypto == 4" in text
    assert "if (cv->stock_scan)" in text
    assert "cv->one_channel && n3ds_ar6014_channel_is_11g(" in text
    assert "ar->arConnectCtrlFlags = cv->ctrl_flags;" in text
    assert "n3ds_ar6014_set_all_channels(ar)" in text

    # --- the logs the hardware run is read from ---
    assert "AR6002 connect: VARIANT %d %s auth=" in text
    assert "AR6002 connect: VARIANT %d %s ASSOCIATED" in text

    # The full-channel restore must exist, otherwise a single-channel table
    # left by an earlier variant silently poisons every later one.
    assert re.search(
        r"wmi_set_channelParams_cmd\(ar->arWmi, 0, WMI_11G_MODE,\s*0, NULL\)",
        text), "full channel table restore missing"


def patcher_marker_count(text: str) -> int:
    return text.count("N3DS_AR6014_CONNECT_VARIANT_SWEEP")


def assert_shipped_module() -> None:
    """The sweep has to be in the driver the device loads, not just in git."""
    if not INITRAMFS.is_file():
        print("  (no built initramfs; skipping shipped-module check)")
        return
    extracted = subprocess.run(
        f'zcat "{INITRAMFS}" | cpio -i --to-stdout {BAKED_MODULE} 2>/dev/null',
        shell=True, capture_output=True,
    )
    blob = extracted.stdout
    if not blob:
        print("  (initramfs carries no ath6kl.ko; skipping)")
        return
    assert b"n3ds_connvar" in blob, (
        "the initramfs ath6kl.ko predates the sweep -- rebuild the kernel")
    for name in EXPECTED_VARIANTS:
        assert name.encode() in blob, f"variant {name} missing from the module"
    assert b"AR6002 connect: VARIANT" in blob


def main() -> None:
    patcher = load_patcher()
    assert_transform(patcher)

    text = CFG.read_text(encoding="utf-8")
    assert_source(text)
    # The tree must already be patched; re-running must change nothing.
    assert patcher.patch_cfg(text) == text

    assert_shipped_module()
    print("ar6014_connect_variant_sweep: PASS "
          f"({len(EXPECTED_VARIANTS)} variants, latch + pin honoured)")


if __name__ == "__main__":
    main()
