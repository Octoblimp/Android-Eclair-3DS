#!/usr/bin/env python3
"""Pin the widened delayed Wi-Fi trace window (A10).

The Mobile Data failure lands ~220 s into the boot, so only a "delayed" stage
of the Wi-Fi trace ever sees it, and that stage kept 64 filtered dmesg lines.
A single target assert used to cost 60 of them.  This asserts the widened
window in the canonical overlay copy *and* that the copy actually shipped to
the SD card carries it -- rootfs_overlay/etc is the source of truth and the SD
copy has silently drifted from it before.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/"
           "rootfs_overlay/etc/boot_progress.sh")
SHIPPED = [
    Path(f"{A3DS_ROOT}/sdcard/linux/android/etc/boot_progress.sh"),
    Path(f"{A3DS_WIN}/"
         "sdcard/linux/android/etc/boot_progress.sh"),
]

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_wifi_trace_delayed_window",
        HERE / "patch_wifi_trace_delayed_window.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from boot_progress.sh")
    check(patcher.patch_boot_progress(text) == text,
          "patcher is not idempotent")

    check("WIFI_DELAYED_LINES=96" in text,
          "the delayed trace window is not 96 lines")
    check("WIFI_DELAYED_LINES=64" not in text,
          "the old 64-line delayed window is still present")

    # The window is only useful if it is actually applied to the delayed stage.
    check('tail -n "$WIFI_DELAYED_LINES"' in text,
          "the delayed stage no longer uses WIFI_DELAYED_LINES")

    # The early stage must stay larger than the delayed one; it captures the
    # driver bring-up, which is longer.
    check("WIFI_INITIAL_LINES=256" in text,
          "the initial window changed; it should stay the larger of the two")

    shipped_found = False
    for path in SHIPPED:
        if not path.is_file():
            continue
        shipped_found = True
        shipped = path.read_text(encoding="utf-8", errors="replace")
        check("WIFI_DELAYED_LINES=96" in shipped,
              f"{path} still carries the old window; run "
              f"sync_android_to_sdcard.sh")
    check(shipped_found,
          "no shipped boot_progress.sh found under either sdcard/ mirror")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_wifi_trace_delayed_window: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
