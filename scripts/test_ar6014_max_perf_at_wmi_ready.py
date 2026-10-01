#!/usr/bin/env python3
"""Regression for MAX_PERF_POWER actually being sent at WMI-ready.

W17 added two call sites and only one of them has ever fired.  Build #256
logged `AR6002 power: MAX_PERF at connect status=0` twenty-five times and
`at init` zero times -- not because the firmware refused it, but because
n3ds_set_max_perf() returns early unless ar->arWmiReady is set, and the init
call sits inside ar6000_init(), which runs before the WMI_READY handler sets
that flag.  The init call has been a no-op on every boot since it was written.

The earliest point the command can leave the driver is immediately after
`ar->arWmiReady = true;`.  Sending it there also gets the radio out of power
save before the connect-time scan rather than several seconds after the
station has already joined asleep, which is the failure mode the power-save
work exists for.

This test pins the call to that window, because an ordering regression here
is silent: the helper would simply return and the log would say nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_max_perf_at_wmi_ready.py")
DRV = (ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux"
       / "ar6000_drv.c")
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"

failures: list[str] = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_max_perf_at_wmi_ready_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_transform(patcher):
    fixture = "".join(old for _, old, _ in patcher.HUNKS)
    patched = patcher.patch_driver(fixture)
    check(patched != fixture, "the patcher did not change its own fixture")
    check(patcher.MARKER in patched, "the patcher left no marker behind")
    check(patcher.patch_driver(patched) == patched,
          "patcher is not idempotent")


def assert_source(text: str):
    check(text.count('n3ds_set_max_perf(ar, "wmiready");') == 1,
          "the WMI-ready MAX_PERF call is missing or duplicated")

    ready = text.find("ar->arWmiReady = true;")
    call = text.find('n3ds_set_max_perf(ar, "wmiready");')
    # ar6000_drv.c has ten wake_up(&arEvent) sites and the first one is
    # thousands of lines above this handler, so anchor to the ready
    # assignment and take the wakeup that actually follows it.
    wake = text.find("wake_up(&arEvent);", ready) if ready != -1 else -1
    check(-1 not in (ready, call, wake),
          "could not locate the WMI-ready landmarks")
    if -1 not in (ready, call, wake):
        check(ready < call,
              "the call runs before arWmiReady is set, so n3ds_set_max_perf() "
              "takes its early return and sends nothing -- exactly the bug "
              "this patch exists to fix")
        check(call < wake,
              "the call moved past the wakeup, where the thread waiting on "
              "arEvent can race ahead of it")

    # The helper has to be defined above the call or this will not compile;
    # a compile break is loud, but catching it here is free.
    helper = text.find("static void n3ds_set_max_perf(")
    check(helper != -1 and helper < call,
          "n3ds_set_max_perf() is not defined before the WMI-ready call site")

    # The existing association-time call must survive: WMI-ready is early
    # enough for the scan, but a target that resets power state on join would
    # otherwise go unhandled.
    check('n3ds_set_max_perf(ar, "connect")' in text,
          "the association-time MAX_PERF call was removed; it is the one that "
          "demonstrably reaches the target today")


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
    check(b"wmiready" in blob,
          "the shipped ath6kl.ko predates the WMI-ready MAX_PERF call, so a "
          "capture would still show only 'MAX_PERF at connect'")


def main() -> int:
    patcher = load_patcher()
    assert_transform(patcher)

    text = DRV.read_text(encoding="utf-8")
    check(patcher.MARKER in text, "marker missing from ar6000_drv.c")
    check(patcher.patch_driver(text) == text, "patcher is not idempotent")
    assert_source(text)
    assert_shipped_module()

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_max_perf_at_wmi_ready: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
