#!/usr/bin/env python3
"""Pin the receive census (W15).

Zero EAPOL frames, confirmed on hardware in #254, is ambiguous: either nothing
at all is being received (the association is nominal) or plenty is being
received and the AP simply never sends message 1/4.  Those want opposite fixes.
One counter separates them, and it has to be bounded -- this driver has filled
a 256 KB log buffer in 20 s before.
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
        "patch_ar6014_rx_census", HERE / "patch_ar6014_rx_census.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from ar6000_drv.c")
    check(patcher.patch_drv(text) == text, "patcher is not idempotent")

    check("static atomic_t n3ds_rx_frames = ATOMIC_INIT(0);" in text,
          "the frame counter is missing")
    check("static atomic_t n3ds_rx_bcast = ATOMIC_INIT(0);" in text,
          "the broadcast counter is missing")
    check("atomic_inc(&n3ds_rx_frames);" in text,
          "frames are counted nowhere")

    # Counters must be atomic: rx runs from softirq, the report from the WMI
    # event path.
    check("static int n3ds_rx_frames" not in text,
          "the frame counter is a plain int; rx and the report run "
          "concurrently")

    # Bounds-check before touching the ethernet header.
    check("if (!skb || A_NETBUF_LEN(skb) < 14)\n        return;\n\n"
          "    atomic_inc(&n3ds_rx_frames);" in text,
          "the census reads the ethernet header without bounds-checking the "
          "frame first")
    check("if (eth[0] & 0x01)" in text,
          "the broadcast/multicast test is not reading the destination MAC's "
          "group bit")

    # Counted where the EAPOL trace already is, i.e. before eth_type_trans()
    # pulls the header.
    check("n3ds_rx_census(skb);" in text, "the census call site is missing")
    census_at = text.index("n3ds_rx_census(skb);")
    pull_at = text.index("skb->protocol = eth_type_trans(skb, skb->dev);")
    check(census_at < pull_at,
          "the census runs after eth_type_trans(); the header is already "
          "pulled and eth[0] would read the wrong bytes")

    # Reset per association, alongside the EAPOL counters.
    check("atomic_set(&n3ds_rx_frames, 0);" in text,
          "the frame counter is never reset, so later associations report "
          "cumulative totals")
    check("atomic_set(&n3ds_rx_bcast, 0);" in text,
          "the broadcast counter is never reset")
    reset_at = text.index("atomic_set(&n3ds_rx_frames, 0);")
    connected_at = text.index("ar->arConnected  = true;")
    check(reset_at < connected_at,
          "the counter reset must precede arConnected going true")

    # Reported once per link-down, not per frame.
    check('n3ds_rx_census_report("disconnect");' in text,
          "the census is never reported")
    check(text.count("n3ds_rx_census_report(") == 2,
          "expected exactly one definition and one call site; more than one "
          "call site means more than one line per link-down")
    report_at = text.index('n3ds_rx_census_report("disconnect");')
    notify_at = text.index("ar6k_cfg80211_disconnect_event(ar, reason, bssid,")
    check(report_at < notify_at,
          "the census is reported after cfg80211 is notified; the numbers "
          "belong next to the reason code, before the teardown")

    # W18 added raw=/rawerr= and W22 split raw into ctrl=/data=, both across
    # two printf literals, so pin the fields the capture instructions name
    # rather than one contiguous string.
    check("AR6002 census %s raw=%d ctrl=%d data=%d rawerr=%d frames=%d "
          in text,
          "the census line no longer reports the raw and delivered counts "
          "together; the capture instructions name both")
    # W23 appended the per-site drop counts, so this literal is no longer the
    # end of the line.  Pin the fields, not the terminator, or every future
    # extension of the census fails a test that is not about extensions.
    check('"bcast=%d eapol_rx=%d eapol_tx=%d' in text,
          "the census line no longer reports the EAPOL counters; they are "
          "the aggregate the capture is read from, and the per-frame "
          "AR6002 EAPOL line only prints for the first few frames")

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
            check(b"AR6002 census " in blob,
                  "baked initramfs module predates the rx census")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_rx_census: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
