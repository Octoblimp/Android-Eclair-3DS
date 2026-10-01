#!/usr/bin/env python3
"""Pin the one-shot Wi-Fi bring-up snapshot (W24).

In #257 the ath6kl module loaded between the trace snapshot at uptime 111.8 s
(wlan0 absent) and the one at 144.3 s (wlan0 present), and that later snapshot
came back exactly 98 lines long -- `tail -n 96` plus its two markers, i.e.
saturated.  The BMI download, the HTC setup and the WMI-ready banner were all
pushed out of the tail, so W19b could not be confirmed or refuted at all.

The failure mode this guards is subtle: the capture still *runs*, still looks
healthy, and simply does not contain the window under investigation.  So the
checks below are about the three things that would silently restore it -- a
budget that is not actually applied, a stamp that lives somewhere persistent
(which turns a one-shot into a never-shot after the first boot), and CRLF from
the Windows workspace making the whole script unrunnable on the device.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

import importlib.util
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/"
           "rootfs_overlay/etc/boot_progress.sh")
SHIPPED = [
    Path(f"{A3DS_ROOT}/sdcard/linux/android/etc/boot_progress.sh"),
    Path(f"{A3DS_WIN}/"
         "sdcard/linux/android/etc/boot_progress.sh"),
]
REL = "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh"

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_wifi_trace_bringup_snapshot",
        HERE / "patch_wifi_trace_bringup_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fixture(patcher):
    """Patch a file built from the patcher's own OLD strings, twice."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / REL
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(old for _, old, _ in patcher.HUNKS),
                          encoding="utf-8")

        patcher.patch_one(target)
        patched = target.read_bytes()
        check(patcher.MARKER.encode() in patched, "fixture gains the marker")
        for name, _, new in patcher.HUNKS:
            check(new.encode() in patched, f"fixture carries hunk {name!r}")
        check(b"\r\n" not in patched,
              "the patcher emitted CRLF; boot_progress.sh is a shell script "
              "the device runs, and it also lives in the Windows workspace "
              "where that is the default translation")

        patcher.patch_one(target)
        check(target.read_bytes() == patched,
              "second run changed the fixture; the patcher is not idempotent")


def main():
    patcher = load_patcher()
    test_fixture(patcher)

    if not SRC.is_file():
        print(f"FAIL: no overlay boot_progress.sh at {SRC}")
        return 1
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from boot_progress.sh")

    check("WIFI_BRINGUP_LINES=600" in text, "the bring-up budget is not 600")
    check("WIFI_BRINGUP_STAMP=/tmp/" in text,
          "the stamp is not under /tmp; anywhere persistent turns a one-shot "
          "into a never-shot on the second boot, and puts the write on the SD "
          "card that the bounded snapshots exist to keep quiet")

    # A budget that is declared and not applied is the exact shape of the bug
    # being fixed: the capture runs, looks healthy, and is still truncated.
    check('tail -n "$WIFI_BRINGUP_LINES"' in text,
          "the bring-up stage does not use WIFI_BRINGUP_LINES")
    check("stage=bringup" in text,
          "the snapshot is not labelled, so it cannot be told apart from the "
          "delayed stages it exists to supplement")

    # It has to be larger than the window that lost the evidence, or it buys
    # nothing.
    check("WIFI_DELAYED_LINES=96" in text,
          "the delayed window changed; the bring-up budget is sized against it")

    # Both halves of the guard: without the wlan0 test it fires before the
    # module loads and captures nothing; without the stamp test it fires every
    # interval and becomes 600 lines of SD traffic every 30 s.
    check('[ ! -f "$WIFI_BRINGUP_STAMP" ]' in text,
          "the snapshot is not gated on the stamp, so it is not one-shot")
    check("[ -d /sys/class/net/wlan0 ]" in text,
          "the snapshot is not gated on wlan0 existing, so it can fire before "
          "the driver has printed anything")

    # Stamp on success only, so a failed append retries next interval instead
    # of silently consuming the single shot.
    check(text.count('> "$WIFI_BRINGUP_STAMP"') == 1,
          "expected exactly one stamp write")
    stamp_at = text.index('> "$WIFI_BRINGUP_STAMP"')
    then_at = text.index('} >> "$WIFI_OUT" 2>/dev/null; then')
    check(then_at < stamp_at,
          "the stamp is written outside the success branch; a failed append "
          "would burn the one shot and the bring-up window would be lost "
          "again")

    # Reuses the snapshot the loop already took rather than shelling out to
    # dmesg a second time.
    bringup_at = text.index("stage=bringup")
    check('"$snap" | grep -iE "$WIFI_RE" | tail -n "$WIFI_BRINGUP_LINES"'
          in text[bringup_at:],
          "the bring-up stage does not reuse $snap through the "
          "existing filter and budget")

    shipped_found = False
    for path in SHIPPED:
        if not path.is_file():
            continue
        shipped_found = True
        blob = path.read_bytes()
        check(patcher.MARKER.encode() in blob,
              f"{path} predates the bring-up snapshot; run "
              f"sync_android_to_sdcard.sh")
        check(b"\r\n" not in blob,
              f"{path} contains CRLF and will not run on the device")
    check(shipped_found,
          "no shipped boot_progress.sh found under either sdcard/ mirror")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_wifi_trace_bringup_snapshot: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
