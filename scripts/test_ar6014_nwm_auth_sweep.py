#!/usr/bin/env python3
"""Regression for the #257 AR6014 auth/crypto sweep and its EAPOL latch.

Two properties are worth a hardware cycle here, and they are easy to lose.

First, the sweep has to actually sweep.  In #256 every one of the boot's 19
connect attempts logged `VARIANT 0 match-done`, because the latch fired the
moment the target associated -- and association is exactly what the failing
tuple already achieves.  Seven of the eight rows were therefore unreachable on
hardware.  The latch now has to key off the link carrying an EAPOL frame, so
this test refuses a latch that keys off association again.

Second, the table has to spend its rows on the open question.  #253 settled
the geometry on hardware (pinned BSSID, single channel,
CONNECT_PROFILE_MATCH_DONE) and those are deliberately held constant here;
what varies is authMode and the cipher wire values, the axis the NWM
disassembly says this driver still has wrong.  One row must reproduce #256
unchanged, or the run has no control to compare against.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_auth_sweep.py")
DRIVER = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux"
CFG = DRIVER / "cfg80211.c"
DRV = DRIVER / "ar6000_drv.c"
HDR = DRIVER / "include/ar6000_drv.h"
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"

EXPECTED_VARIANTS = (
    "nwm-auth", "nwm-open", "nwm-aes", "match-done",
    "real-nwm", "nwm-user", "nwm-noflags", "nwm-nwmscan",
)

failures: list[str] = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_nwm_auth_sweep_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_transform(patcher):
    """Each patch function must transform its own file, once, and stop."""
    for fn, hunks in ((patcher.patch_cfg, patcher.CFG_HUNKS),
                      (patcher.patch_drv, patcher.DRV_HUNKS),
                      (patcher.patch_hdr, patcher.HDR_HUNKS)):
        fixture = "".join(old for _, old, _ in hunks)
        patched = fn(fixture)
        check(patched != fixture, f"{fn.__name__} did not change its fixture")
        check(patcher.MARKER in patched,
              f"{fn.__name__} left no marker behind")
        check(fn(patched) == patched, f"{fn.__name__} is not idempotent")


def parse_rows(body: str) -> list[list[str]]:
    rows = re.findall(r'\{\s*("[^"]*"[^{}]*?)\}', body, re.S)
    return [[field.strip() for field in row.split(",") if field.strip()]
            for row in rows]


def assert_table(text: str):
    table = re.search(
        r"static const struct n3ds_connect_variant n3ds_connect_variants\[\]"
        r" = \{(.*?)\n\};", text, re.S)
    check(table is not None, "variant table missing")
    if not table:
        return
    body = table.group(1)
    names = tuple(re.findall(r'\{\s*"([^"]+)"', body))
    check(names == EXPECTED_VARIANTS, f"variant names drifted: {names}")

    rows = parse_rows(body)
    check(len(rows) == len(EXPECTED_VARIANTS), f"row count: {len(rows)}")
    axes = []
    for fields in rows:
        # name, real_auth, crypto, real_bssid, one_channel, stock_scan, flags
        check(len(fields) == 7, f"row shape: {fields}")
        if len(fields) == 7:
            axes.append(tuple(int(f) for f in fields[1:6]))
    if len(axes) != len(EXPECTED_VARIANTS):
        return

    # The axis under test must move, in both directions.
    check({row[0] for row in axes} == {0, 1},
          "authMode never varies, so the run cannot answer the one question "
          "it was flashed for")
    check({row[1] for row in axes} == {0, 4, 8},
          "the crypto axis must still try all three wire readings")

    # The geometry #253 proved on hardware must stay pinned, or a failure to
    # associate becomes indistinguishable from a failure to authenticate.
    check({row[2] for row in axes} == {1},
          "real_bssid is no longer pinned; #253 proved a locked BSSID is what "
          "makes NWM associate at all")
    check({row[3] for row in axes} == {1},
          "one_channel is no longer pinned; a full channel table reintroduces "
          "the variable #253 already eliminated")

    # A control row: exactly the tuple #256 sent, so the boot contains its own
    # before-and-after.
    check(("match-done", 1, 8, 1, 1, 1) in
          {(names[i],) + axes[i] for i in range(len(axes))},
          "no control row reproducing #256 (real auth, Linux 8/8 ciphers)")


def assert_latch(text: str):
    # The association site records, and must not latch.
    check("n3ds_connect_assoc_variant = n3ds_connect_current;" in text,
          "the association site no longer records which variant got there")
    check("n3ds_connect_latched = n3ds_connect_current;" not in text,
          "the latch still fires on bare association -- that is what froze "
          "the sweep on row 0 for all 19 attempts of #256")

    # The latch site is guarded by the EAPOL counter.
    match = re.search(
        r"if \(n3ds_connect_latched < 0 && n3ds_connect_assoc_variant >= 0 &&"
        r"\s*atomic_read\(&n3ds_eapol_rx_count\) > 0\) \{", text)
    check(match is not None,
          "the latch is not conditioned on the link having carried EAPOL")
    check("n3ds_connect_latched = n3ds_connect_assoc_variant;" in text,
          "the EAPOL latch does not actually latch the associating variant")

    # It has to run before the variant for this attempt is chosen, or the
    # latch takes effect one attempt late.
    if match:
        select = text.find("if (n3ds_connvar >= 0 &&")
        check(select != -1 and match.start() < select,
              "the latch decision runs after variant selection, so a latched "
              "variant is not used until the attempt after next")

    # The log the hardware run is read from.
    check("AR6002 connect: VARIANT %d %s CARRIED EAPOL rx=%d, latching" in text,
          "no log line names the variant that carried a handshake")
    check("AR6002 connect: VARIANT %d %s ASSOCIATED" in text,
          "the association line is gone; it is still how the sweep is traced")


def assert_linkage(drv: str, hdr: str):
    check("static atomic_t n3ds_eapol_rx_count" not in drv,
          "n3ds_eapol_rx_count is still static, so cfg80211.c cannot read it")
    check("\natomic_t n3ds_eapol_rx_count = ATOMIC_INIT(0);" in drv,
          "n3ds_eapol_rx_count has no definition with external linkage")
    check("extern atomic_t n3ds_eapol_rx_count;" in hdr,
          "the shared header does not declare the counter, so cfg80211.c "
          "would compile against an implicit declaration")


def assert_shipped_module():
    if not INITRAMFS.is_file():
        print("  (no built initramfs; skipping shipped-module check)")
        return
    blob = subprocess.run(
        f'zcat "{INITRAMFS}" | cpio -i --to-stdout {BAKED_MODULE} 2>/dev/null',
        shell=True, capture_output=True).stdout
    if not blob:
        print("  (initramfs carries no ath6kl.ko; skipping)")
        return
    for name in EXPECTED_VARIANTS:
        check(name.encode() in blob,
              f"variant {name} missing from the shipped module")
    check(b"CARRIED EAPOL" in blob,
          "the shipped ath6kl.ko predates the EAPOL latch -- the module in "
          "the initramfs is what the device loads, not the source tree")


def main() -> int:
    patcher = load_patcher()
    assert_transform(patcher)

    cfg = CFG.read_text(encoding="utf-8")
    drv = DRV.read_text(encoding="utf-8")
    hdr = HDR.read_text(encoding="utf-8")

    check(patcher.MARKER in cfg, "marker missing from cfg80211.c")
    check(patcher.MARKER in drv, "marker missing from ar6000_drv.c")
    check(patcher.MARKER in hdr, "marker missing from ar6000_drv.h")
    check(patcher.patch_cfg(cfg) == cfg, "cfg80211.c patch is not idempotent")
    check(patcher.patch_drv(drv) == drv, "ar6000_drv.c patch is not idempotent")
    check(patcher.patch_hdr(hdr) == hdr, "ar6000_drv.h patch is not idempotent")

    assert_table(cfg)
    assert_latch(cfg)
    assert_linkage(drv, hdr)
    assert_shipped_module()

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print(f"test_ar6014_nwm_auth_sweep: PASS "
          f"({len(EXPECTED_VARIANTS)} variants, EAPOL latch honoured)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
