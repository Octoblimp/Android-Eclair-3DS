#!/usr/bin/env python3
"""Pin the WMI_CONNECT ctrl_flags sweep (W5) and its connect log (W7).

ctrl_flags is the only field of the 52-byte WMI_CONNECT_CMD this driver has
never varied -- it was hardcoded to 0 on every attempt ever sent, on the
strength of an NWM disassembly reading.  The previous sweep exhausted every
other field against the hardware and never associated once, and the failure the
firmware reports (reason=1, NO_NETWORK_AVAIL) is its own internal connect-time
scan coming up empty for an AP the host scan sees at -34 dBm.
CONNECT_PROFILE_MATCH_DONE is the bit that tells it to skip that scan, so what
this test guards is that the bit is actually reaching the wire on most rows and
that one control row still sends flags=0 for comparison.
"""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path
import re
import subprocess


_file_path = Path(__file__).resolve()
ROOT = _file_path.parents[1]
if "/mnt/c/" in str(_file_path):
    ROOT = Path(A3DS_ROOT)
PATCH_PATH = Path(__file__).with_name(
    "patch_ar6014_connect_ctrl_flags_sweep.py")
CFG = (ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux"
       / "cfg80211.c")
WMI_H = (ROOT / "third_party/linux/drivers/staging/ath6k_legacy/include"
         / "common/wmi.h")
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"

MATCH_DONE = "CONNECT_PROFILE_MATCH_DONE"


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_connect_ctrl_flags_sweep_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_transform(patcher) -> None:
    """The patcher must rewrite the pre-sweep source once, and only once."""
    fixture = patcher.TABLE_OLD + patcher.LOG_OLD
    patched = patcher.patch_cfg(fixture)
    assert patched != fixture, "patcher did nothing to the pre-patch fixture"
    assert patcher.MARKER in patched
    assert patcher.patch_cfg(patched) == patched, "patcher is not idempotent"
    # The old hardcoded zero must be gone, not merely shadowed.
    assert "ar->arConnectCtrlFlags = 0;" not in patched


def parse_rows(body: str) -> list[list[str]]:
    rows = re.findall(r'\{\s*("[^"]*"[^{}]*?)\}', body, re.S)
    return [[field.strip() for field in row.split(",") if field.strip()]
            for row in rows]


def assert_flag_names_exist() -> None:
    """Every bit the table names must be a real enumerator, or it won't build."""
    header = WMI_H.read_text(encoding="utf-8")
    for name in (MATCH_DONE, "CONNECT_ASSOC_POLICY_USER",
                 "CONNECT_IGNORE_WPAx_GROUP_CIPHER", "CONNECT_CSA_FOLLOW_BSS",
                 "DEFAULT_CONNECT_CTRL_FLAGS"):
        assert name in header, f"{name} is not defined in wmi.h"
    # The bit this whole sweep is aimed at must still be 0x0008.
    assert re.search(rf"{MATCH_DONE}\s*=\s*0x0*8\b", header), (
        "CONNECT_PROFILE_MATCH_DONE is no longer 0x0008")


def assert_source(text: str) -> None:
    assert "N3DS_AR6014_CONNECT_CTRL_FLAGS_SWEEP" in text, "marker missing"

    # --- the struct carries the new axis ---
    assert re.search(r"u16 ctrl_flags;", text), (
        "struct n3ds_connect_variant has no ctrl_flags member")

    table = re.search(
        r"static const struct n3ds_connect_variant n3ds_connect_variants\[\]"
        r" = \{(.*?)\n\};", text, re.S)
    assert table, "variant table missing"
    rows = parse_rows(table.group(1))
    assert len(rows) == 8, f"expected 8 variants, got {len(rows)}"

    flags = [row[6] for row in rows]
    assert len(flags) == len(rows)

    # The point of the sweep: most rows carry the match-done bit.
    match_done_rows = [f for f in flags if MATCH_DONE in f]
    assert len(match_done_rows) >= 4, (
        f"only {len(match_done_rows)} rows set {MATCH_DONE}; the sweep is "
        "not actually testing the bit it exists for")

    # ...and exactly one control row sends flags=0, so a single boot still
    # reproduces the old behaviour next to the new one.
    zero_rows = [f for f in flags if f.strip() == "0"]
    assert len(zero_rows) == 1, (
        f"expected exactly one flags=0 control row, got {len(zero_rows)}")

    # A row that tells the target to skip its own scan must supply the BSSID
    # and channel that scan would otherwise have found, or there is nothing
    # for it to associate to.
    for row in rows:
        if MATCH_DONE in row[6]:
            name, real_bssid, one_channel = row[0], row[3], row[4]
            assert real_bssid == "1", (
                f"{name} sets {MATCH_DONE} but sends a wildcard BSSID")
            assert one_channel == "1", (
                f"{name} sets {MATCH_DONE} but does not pin the channel")

    # --- the flags actually reach the command ---
    assert "ar->arConnectCtrlFlags = cv->ctrl_flags;" in text
    assert "ar->arConnectCtrlFlags = 0;" not in text, (
        "something still hardcodes ctrl_flags to zero")
    assert re.search(
        r"wmi_connect_cmd\(.*?ar->arConnectCtrlFlags\);", text, re.S), (
        "wmi_connect_cmd no longer passes arConnectCtrlFlags")

    # --- W7: the log has to show the whole submission ---
    for field in ("flags=0x%04x", "nettype=%u", "dot11auth=%u", "ssidlen=%u"):
        assert field in text, f"connect log lost {field}"
    assert "AR6002 connect: VARIANT %d %s auth=" in text


def assert_shipped_module() -> None:
    if not INITRAMFS.is_file():
        print("  (no built initramfs; skipping shipped-module check)")
        return
    blob = subprocess.run(
        f'zcat "{INITRAMFS}" | cpio -i --to-stdout {BAKED_MODULE} 2>/dev/null',
        shell=True, capture_output=True).stdout
    if not blob:
        print("  (initramfs carries no ath6kl.ko; skipping)")
        return
    assert b"flags=0x%04x" in blob, (
        "the initramfs ath6kl.ko predates the ctrl_flags sweep -- rebuild")
    assert b"match-done" in blob


def main() -> None:
    patcher = load_patcher()
    assert_transform(patcher)
    assert_flag_names_exist()

    text = CFG.read_text(encoding="utf-8")
    assert_source(text)
    assert patcher.patch_cfg(text) == text, "tree is not patched"

    assert_shipped_module()
    print("ar6014_connect_ctrl_flags_sweep: PASS "
          "(8 variants, match-done rows pin bssid + channel)")


if __name__ == "__main__":
    main()
