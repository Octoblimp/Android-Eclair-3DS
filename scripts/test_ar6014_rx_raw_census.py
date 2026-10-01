#!/usr/bin/env python3
"""Pin the HTC-boundary receive census (W18).

``frames=0`` is not yet an answer.  It is measured at the handover to the
network stack, which is hundreds of lines of ``ar6000_rx()`` downstream of the
point where the target actually hands the driver a packet, and it cannot
separate "the target delivered nothing" from "the driver discarded everything".
Those two readings point at completely different fixes, so the counter has to
move up to the HTC callback before any conclusion drawn from it is worth
anything.
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
        "patch_ar6014_rx_raw_census",
        HERE / "patch_ar6014_rx_raw_census.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from ar6000_drv.c")
    check(patcher.patch_driver(text) == text, "patcher is not idempotent")

    check("static atomic_t n3ds_rx_raw = ATOMIC_INIT(0);" in text,
          "the raw receive counter is missing")
    check("static atomic_t n3ds_rx_raw_err = ATOMIC_INIT(0);" in text,
          "the raw error counter is missing; without it a stream of failed "
          "deliveries is indistinguishable from a healthy one")

    # The whole point is where it is counted.  W22 gave the call a second
    # argument (the control/data endpoint split); match the call by prefix so
    # this test pins the position, which is what it is for, and leaves the
    # signature to test_ar6014_rx_endpoint_census.py.
    check(text.count("n3ds_rx_raw_census(status") == 1,
          "the raw census call is missing or duplicated")
    rx_entry = text.find("HTC_ENDPOINT_ID   ept = pPacket->Endpoint;")
    census_call = text.find("n3ds_rx_raw_census(status")
    deliver = text.find("n3ds_rx_census(skb);")
    check(rx_entry != -1 and census_call != -1 and deliver != -1,
          "could not locate the receive path landmarks")
    if rx_entry != -1 and census_call != -1 and deliver != -1:
        check(census_call - rx_entry < 400,
              "the raw census is no longer at the top of ar6000_rx(); a "
              "counter placed after the early returns measures the same thing "
              "the old one did")
        check(census_call < deliver,
              "the raw census is counted after the netdev handover, which "
              "defeats its purpose")

    # It must ride the existing report and the existing per-association reset,
    # or the numbers will be cumulative across associations and unreadable.
    check("AR6002 census %s raw=%d ctrl=%d data=%d rawerr=%d frames=%d "
          in text,
          "the census line does not report the raw counters")
    check("atomic_set(&n3ds_rx_raw, 0);" in text,
          "the raw counter is never reset, so it would accumulate across "
          "every association attempt in a boot")
    check("atomic_set(&n3ds_rx_raw_err, 0);" in text,
          "the raw error counter is never reset")

    # Resets belong together; a counter reset somewhere else would drift.
    reset = text.find("atomic_set(&n3ds_rx_frames, 0);")
    raw_reset = text.find("atomic_set(&n3ds_rx_raw, 0);")
    check(reset != -1 and raw_reset != -1 and 0 <= raw_reset - reset < 200,
          "the raw counters are not reset alongside the existing ones")

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
            check(b"AR6002 census %s raw=%d ctrl=%d data=%d rawerr=%d" in blob,
                  "baked initramfs module predates the raw census, so a "
                  "capture would still only show the netdev-handover count")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_rx_raw_census: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
