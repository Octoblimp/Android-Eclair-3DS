#!/usr/bin/env python3
"""Regression for splitting the raw RX census by HTC endpoint (W22).

W18 moved the receive count up to the HTC callback so `frames=0` could be told
apart from "the driver dropped everything".  It landed above the
`ept == ar->arControlEp` split, though, so WMI control events and data frames
go into one bucket -- and that is what made #256 ambiguous in exactly the way
the counter was added to prevent.

`raw=47 frames=0` looks like 47 delivered packets thrown away.  It is not: an
unknown control event (WMI ID 0x1025, one-byte payload) arrives about every
300 ms, which over the ten seconds the link was up accounts for roughly 33 of
the 47 on its own.  The true reading is that zero *data* frames were
delivered, which points somewhere else entirely.

So the split is the whole point of this patch, and this test pins it: the
count still happens before any early return, and it is attributed by endpoint.
"""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_rx_endpoint_census.py")
DRV = (ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux"
       / "ar6000_drv.c")
if not DRV.is_file():
    DRV = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
               "ath6k_legacy/os/linux/ar6000_drv.c")
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"

failures: list[str] = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_rx_endpoint_census_patch", PATCH_PATH)
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
    check("static atomic_t n3ds_rx_raw_ctrl = ATOMIC_INIT(0);" in text,
          "the control-endpoint counter is missing")
    check("static atomic_t n3ds_rx_raw_data = ATOMIC_INIT(0);" in text,
          "the data-endpoint counter is missing")

    # The attribution has to come from the endpoint, not from a guess.
    check("n3ds_rx_raw_census(int status, int is_ctrl)" in text,
          "the census helper does not take the endpoint attribution")
    check("n3ds_rx_raw_census(status, (ept == ar->arControlEp) ? 1 : 0);"
          in text,
          "the call site does not attribute the packet by HTC endpoint")

    # Position is still the property W18 bought: before every early return.
    rx_entry = text.find("HTC_ENDPOINT_ID   ept = pPacket->Endpoint;")
    call = text.find("n3ds_rx_raw_census(status, (ept ==")
    deliver = text.find("n3ds_rx_census(skb);")
    check(-1 not in (rx_entry, call, deliver),
          "could not locate the receive path landmarks")
    if -1 not in (rx_entry, call, deliver):
        check(rx_entry < call,
              "the census reads ept before it is assigned")
        check(call - rx_entry < 700,
              "the census drifted down out of the top of ar6000_rx(); a count "
              "taken after the early returns measures the wrong thing")
        check(call < deliver,
              "the raw census is counted after the netdev handover")

    # Reported and reset alongside the counters it belongs with, or the
    # numbers accumulate across associations and cannot be read.
    check("AR6002 census %s raw=%d ctrl=%d data=%d rawerr=%d frames=%d "
          in text,
          "the census line does not report the endpoint split")
    check("atomic_set(&n3ds_rx_raw_ctrl, 0);" in text,
          "the control counter is never reset")
    check("atomic_set(&n3ds_rx_raw_data, 0);" in text,
          "the data counter is never reset")
    base = text.find("atomic_set(&n3ds_rx_raw, 0);")
    ctrl = text.find("atomic_set(&n3ds_rx_raw_ctrl, 0);")
    check(base != -1 and ctrl != -1 and 0 < ctrl - base < 200,
          "the endpoint counters are not reset alongside the existing ones")


def assert_shipped_module():
    if not INITRAMFS.is_file():
        check(False, "release initramfs is required")
        return
    blob = subprocess.run(
        f'zcat "{INITRAMFS}" | cpio -i --to-stdout {BAKED_MODULE} 2>/dev/null',
        shell=True, capture_output=True).stdout
    if not blob:
        check(False, "initramfs carries no ath6kl.ko")
        return
    check(b"AR6002 census %s raw=%d ctrl=%d data=%d" in blob,
          "the shipped ath6kl.ko predates the endpoint split, so a capture "
          "would still show the ambiguous single raw count")


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
    print("test_ar6014_rx_endpoint_census: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
