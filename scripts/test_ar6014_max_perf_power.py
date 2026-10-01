#!/usr/bin/env python3
"""Pin the power-save fix (W17).

The station has associated cleanly since #255 and still carries no traffic.
The one mechanism that explains zero EAPOL, zero frames of any kind, and an AP
that gives up with 802.11 reason 34 (DISASSOC_LOW_ACK) at the same time is a
station sitting in power save: the AP buffers the first handshake message for a
client it believes is asleep, the client never collects it, and the un-acked
frames eventually cost it the link.

The stock driver never sends a power-mode command at all -- every
``wmi_powermode_cmd()`` call site in this tree is behind a build flag that is
``#undef``'d or never defined.  What this test guards is that the fix cannot
regress back into that state without failing loudly.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/os/linux/ar6000_drv.c")
INITRAMFS = Path(f"{A3DS_ROOT}/sdcard/linux/initramfs.cpio.gz")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_ar6014_max_perf_power",
        HERE / "patch_ar6014_max_perf_power.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from ar6000_drv.c")
    check(patcher.patch_driver(text) == text, "patcher is not idempotent")

    # The bug: the only unconditional call site was inside a block guarded by
    # a macro nobody defines, so it compiled to nothing.
    check("#ifdef ATH6K_CONFIG_OTA_MODE" not in text,
          "the power-mode call is behind ATH6K_CONFIG_OTA_MODE again, which "
          "is not defined anywhere in this tree, so it compiles to nothing")
    check("#undef ADAPTIVE_POWER_THROUGHPUT_CONTROL" in text,
          "APTC is defined now; its two wmi_powermode_cmd() call sites would "
          "fight this fix for control of the power mode")

    # The fix must be reachable from real code, not from a dead branch.
    check("static void n3ds_set_max_perf(struct ar6_softc *ar, const char *when)"
          in text,
          "the power-mode helper is missing")
    check("wmi_powermode_cmd(ar->arWmi, MAX_PERF_POWER);" in text,
          "MAX_PERF_POWER is not requested")
    check(text.count('n3ds_set_max_perf(ar, "init");') == 1,
          "the init-time power-mode call is missing or duplicated")
    check(text.count('n3ds_set_max_perf(ar, "connect");') == 1,
          "the per-association power-mode call is missing or duplicated; the "
          "handshake happens in the first seconds of a link, so an init-only "
          "setting is not enough if the target resets its power state on join")

    # The helper runs on the connect event path, which is shared with
    # cfg80211 -- guard the ordering that makes that safe.
    check("if (ar == NULL || ar->arWmi == NULL || ar->arWmiReady == false)"
          in text,
          "the helper does not check that the WMI is up before sending")

    # An A/B against the old behaviour must not need a second driver build.
    check("module_param(n3ds_max_perf, int, 0644);" in text,
          "n3ds_max_perf is not a module parameter, so power save cannot be "
          "put back for a comparison run without rebuilding")
    check("static int n3ds_max_perf = 1;" in text,
          "n3ds_max_perf does not default on")

    # The result has to be visible in a capture, or the run proves nothing.
    check('A_PRINTF("AR6002 power: MAX_PERF at %s status=%d\\n", when, rc);'
          in text,
          "the power-mode result is not printed; a capture could not tell a "
          "sent command from a rejected one")

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
            check(b"AR6002 power: MAX_PERF at %s status=%d" in blob,
                  "baked initramfs module predates the power-save fix; the "
                  "sdcard system/lib/modules copies are never loaded, so this "
                  "is the only copy that matters")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_max_perf_power: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
