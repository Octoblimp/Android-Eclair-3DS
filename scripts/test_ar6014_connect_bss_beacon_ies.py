#!/usr/bin/env python3
"""Regression for the connect-time BSS being built from NWM's beacon IEs.

`WARNING at net/wireless/sme.c:757` fired six times in #256.  That line is
`if (WARN_ON(!cr->bss)) return;` in __cfg80211_connect_result(), and it means
cfg80211 could not find by SSID the BSS the driver said it had connected to --
so wdev->current_bss is never set and cfg80211_upload_connect_keys() is
skipped with it.

The driver publishes that BSS itself, a few lines earlier, by handing
cfg80211_inform_bss_frame() a synthesized beacon.  Stock ath6kl fills the
beacon's variable part with the *association request* IEs; after the assoc-IE
fixup those are the host's own RSN blob, which contains no SSID element at
all.  NWM does supply the AP's real beacon IEs (beaconIeLen=207 in every #256
connect event) in the first beaconIeLen bytes of assocInfo.

What this pins is that the beacon is built from the beacon IEs, that it is
built before cfg80211 is told about the BSS, and that the old behaviour
survives only as the fallback for a target that sent none.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_connect_bss_beacon_ies.py")
CFG = (ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux"
       / "cfg80211.c")
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"

failures: list[str] = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_connect_bss_beacon_ies_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_transform(patcher):
    fixture = "".join(old for _, old, _ in patcher.HUNKS)
    patched = patcher.patch_cfg(fixture)
    check(patched != fixture, "the patcher did not change its own fixture")
    check(patcher.MARKER in patched, "the patcher left no marker behind")
    check(patcher.patch_cfg(patched) == patched, "patcher is not idempotent")


def assert_source(text: str):
    check("ptr_ie_buf = assocInfo;" in text,
          "the synthesized beacon is not built from NWM's beacon IEs")
    check("ie_buf_len = beaconIeLen;" in text,
          "the beacon IE length is not taken from beaconIeLen")

    # A target that reports no beacon IEs must still get the old behaviour,
    # or this trades one empty BSS for another.
    check("assocInfo != NULL && beaconIeLen > 0" in text,
          "no guard on beaconIeLen, so a target reporting none would publish "
          "a zero-length beacon")
    check("ptr_ie_buf = assocReqIe;" in text,
          "the assoc-request fallback was removed rather than demoted")

    # Order: choose the IEs, copy them into the frame, then inform cfg80211.
    choose = text.find("ptr_ie_buf = assocInfo;")
    copy = text.find("memcpy(mgmt->u.beacon.variable, ptr_ie_buf, ie_buf_len)")
    inform = text.find("cfg80211_inform_bss_frame(ar->wdev->wiphy,")
    result = text.find("cfg80211_connect_result(ar->arNetDev, bssid,")
    check(-1 not in (choose, copy, inform, result),
          "could not locate the connect-event landmarks")
    if -1 not in (choose, copy, inform, result):
        check(choose < copy < inform,
              "the IE choice no longer precedes the frame it feeds")
        check(inform < result,
              "cfg80211_connect_result() runs before the BSS is published, "
              "which is the exact ordering sme.c:757 warns about")

    # The capture has to say which source was used, or a beaconIeLen of 0 on
    # hardware would look identical to the patch not being present.
    check("AR6002 connect: bss ie src=beacon len=%u" in text,
          "no log line reports that the beacon IEs were used")
    check("AR6002 connect: bss ie src=assocreq len=%u" in text,
          "no log line reports the fallback, so a silent fallback would read "
          "as a successful fix")


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
    check(b"bss ie src=beacon" in blob,
          "the shipped ath6kl.ko predates the beacon-IE fix -- the module in "
          "the initramfs is what the device loads, not the source tree")


def main() -> int:
    patcher = load_patcher()
    assert_transform(patcher)

    text = CFG.read_text(encoding="utf-8")
    check(patcher.MARKER in text, "marker missing from cfg80211.c")
    check(patcher.patch_cfg(text) == text, "patcher is not idempotent")
    assert_source(text)
    assert_shipped_module()

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_connect_bss_beacon_ies: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
