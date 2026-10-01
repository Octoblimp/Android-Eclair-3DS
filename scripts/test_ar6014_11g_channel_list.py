#!/usr/bin/env python3
"""Pin the 11G-legal channel-list restriction (W6).

Channel 14 (2484 MHz) in a WMI_11G_MODE channel list makes the target reject
WMI_SET_CHANNEL_PARAMS outright (WMI_CMDERROR cmd=0x0011 errorCode=1), which
leaves its persistent channel table -- the one WMI_CONNECT's own profile search
reads -- holding whatever the previous connect attempt left behind.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/os/linux/cfg80211.c")
INITRAMFS = Path(f"{A3DS_ROOT}/sdcard/linux/initramfs.cpio.gz")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_ar6014_11g_channel_list",
        HERE / "patch_ar6014_11g_channel_list.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from cfg80211.c")

    # Idempotency: re-running the patcher on a patched tree is a no-op.
    check(patcher.patch_cfg(text) == text, "patcher is not idempotent")

    # The predicate exists and excludes 2484 by construction.
    check("static bool n3ds_ar6014_channel_is_11g(u16 mhz)" in text,
          "n3ds_ar6014_channel_is_11g() helper missing")
    check("return mhz >= 2412 && mhz <= 2472 && !((mhz - 2412) % 5);" in text,
          "11g predicate body changed; 2484 may no longer be excluded")

    # All three call sites go through the predicate.
    check("if (!n3ds_ar6014_channel_is_11g(mhz))" in text,
          "set_search_channel() no longer validates through the predicate")
    check("if (n3ds_ar6014_channel_is_11g(freq))" in text,
          "discovery channel filter no longer uses the predicate")
    check("if (cv->one_channel && n3ds_ar6014_channel_is_11g("
          "ar->arChannelHint))" in text,
          "connect single-channel call site no longer guards on the predicate")

    check("AR6002 scan: START_SCAN submitted explicit_11g_channels=%d"
          in text,
          "scan submit log no longer reports the 11G-filtered channel count")

    # The fallback table must not reintroduce channel 14.
    fallback = re.search(
        r"static const u16 ar6014_2ghz_channels\[\] = \{(.*?)\};",
        text, re.S)
    check(fallback is not None, "fallback 2.4 GHz channel table not found")
    if fallback:
        freqs = [int(n) for n in re.findall(r"\d+", fallback.group(1))]
        check(2484 not in freqs,
              "fallback channel table still contains 2484 (channel 14)")
        check(freqs == [2412, 2417, 2422, 2427, 2432, 2437, 2442,
                        2447, 2452, 2457, 2462, 2467, 2472],
              f"fallback channel table is not the 13 11G channels: {freqs}")

    # No stray literal 2484 may survive in a channel list handed to WMI.  The
    # wiphy CHAN2G table and the CHAN_IS_11A range check are legitimate.
    for match in re.finditer(r"^.*\b2484\b.*$", text, re.M):
        line = match.group(0)
        allowed = ("CHAN2G(" in line or "CHAN_IS_11A" in line
                   or line.lstrip().startswith("*"))
        check(allowed, f"unexpected 2484 literal: {line.strip()}")

    # The shipped module is what runs (see the initramfs-only delivery path).
    if not INITRAMFS.is_file():
        failures.append(f"initramfs not found at {INITRAMFS}")
    else:
        blob = subprocess.run(
            ["bash", "-c",
             f"gzip -dc {INITRAMFS} | cpio -i --to-stdout "
             f"n3ds/modules/ath6kl.ko 2>/dev/null"],
            capture_output=True).stdout
        check(len(blob) > 0, "could not extract ath6kl.ko from the initramfs")
        if blob:
            # The predicate may be inlined away, so key freshness on a
            # string literal this patch introduces and nothing else does.
            check(b"explicit_11g_channels=" in blob,
                  "baked initramfs module predates the 11G channel patch")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_11g_channel_list: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
