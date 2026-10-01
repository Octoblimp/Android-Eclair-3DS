#!/usr/bin/env python3
"""Pin the bounded EAPOL frame trace (W9).

The 10 s post-association teardown is either wpa_supplicant's association
timeout or its first-EAPOL timeout; both are 10 s and nothing in any capture so
far distinguishes them.  Counting ethertype 0x888E in each direction does.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import re
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
        "patch_ar6014_eapol_trace", HERE / "patch_ar6014_eapol_trace.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from ar6000_drv.c")
    check(patcher.patch_drv(text) == text, "patcher is not idempotent")

    check("#define N3DS_EAPOL_ETHERTYPE    0x888E" in text,
          "EAPOL ethertype constant missing or changed")
    check("if (((eth[12] << 8) | eth[13]) != N3DS_EAPOL_ETHERTYPE)" in text,
          "the ethertype test is not reading the ethernet header")
    check("if (!skb || A_NETBUF_LEN(skb) < 14)" in text,
          "the trace no longer bounds-checks the frame before reading it")

    # Bounded output: this driver has produced a log firehose before.
    check("#define N3DS_EAPOL_TRACE_MAX    12" in text,
          "the per-direction trace cap is missing")
    check("if (n > N3DS_EAPOL_TRACE_MAX)" in text,
          "the trace cap is not enforced")
    check("atomic_inc_return(counter)" in text,
          "the trace counter is not atomic; both paths run concurrently")

    # Both directions traced, in the right places.
    check('n3ds_eapol_trace(skb, "tx", &n3ds_eapol_tx_count' in text,
          "TX trace call site missing")
    check('n3ds_eapol_trace(skb, "rx", &n3ds_eapol_rx_count, 1);' in text,
          "RX trace call site missing")

    # TX must be traced before the not-associated guard drops the frame.
    tx_at = text.index('n3ds_eapol_trace(skb, "tx"')
    guard_at = text.index("if( (!ar->arConnected && !bypasswmi)")
    check(tx_at < guard_at,
          "TX trace runs after the not-associated guard; dropped EAPOL frames "
          "would go unreported, which is the case worth seeing")

    # RX must be traced before eth_type_trans() pulls the ethernet header.
    rx_at = text.index('n3ds_eapol_trace(skb, "rx"')
    pull_at = text.index("skb->protocol = eth_type_trans(skb, skb->dev);")
    check(rx_at < pull_at,
          "RX trace runs after eth_type_trans(); the header is already pulled")

    # Counters reset per association, before arConnected goes true.
    check("n3ds_eapol_trace_reset();" in text,
          "counters are never reset, so later associations are not traced")
    reset_at = text.index("n3ds_eapol_trace_reset();")
    connected_at = text.index("ar->arConnected  = true;")
    check(reset_at < connected_at,
          "the counter reset must precede arConnected going true")

    check("AR6002 EAPOL %s #%d len=%d conn=%d" in text,
          "trace line format changed; the capture instructions name it")

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
            check(b"AR6002 EAPOL " in blob,
                  "baked initramfs module predates the EAPOL trace patch")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_eapol_trace: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
