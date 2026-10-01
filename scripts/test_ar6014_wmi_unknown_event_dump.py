#!/usr/bin/env python3
"""Pin the unhandled-WMI-event dump and its rate limit (W16/W14b).

The user's visible complaint is "unknown ID errors": 77 identical
``Unknown id 0x1025`` lines per boot, in four bursts, one burst per association,
on a ~306 ms cadence (3 x a 100 ms beacon, i.e. DTIM 3).  Stock ath6kl prints
that line unbounded and never looks at the payload, so the flood said nothing
while costing a large share of a 256 KB log buffer.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/wmi/wmi.c")
INITRAMFS = Path(f"{A3DS_ROOT}/sdcard/linux/initramfs.cpio.gz")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_ar6014_wmi_unknown_event_dump",
        HERE / "patch_ar6014_wmi_unknown_event_dump.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from wmi.c")
    check(patcher.patch_wmi(text) == text, "patcher is not idempotent")

    # The unbounded stock print must be gone from both dispatch paths.
    check('(DBGFMT "Unknown id 0x%x\\n", DBGARG, id)' not in text,
          "the unbounded stock Unknown-id print is back; 0x1025 alone emitted "
          "77 of them per boot")
    check(text.count("n3ds_wmi_unknown_event(") == 3,
          "expected the helper plus exactly two call sites (xtnd and ctrl)")
    check('n3ds_wmi_unknown_event("xtnd", id, datap, len);' in text,
          "the extended-event dispatch no longer reports unknown ids")
    check('n3ds_wmi_unknown_event("ctrl", id, datap, len);' in text,
          "the control-event dispatch no longer reports unknown ids")

    # Bounded: per-id dump cap, per-id table cap, per-dump byte cap.
    check("#define N3DS_WMI_UNKNOWN_DUMPS    3" in text,
          "the per-id dump cap is missing")
    check("#define N3DS_WMI_UNKNOWN_BYTES    32" in text,
          "the per-dump byte cap is missing")
    check("#define N3DS_WMI_UNKNOWN_IDS      8" in text,
          "the distinct-id table cap is missing; an id storm would otherwise "
          "walk off the end of the arrays")
    check("if (n3ds_wmi_unknown_used == N3DS_WMI_UNKNOWN_IDS)" in text,
          "the distinct-id table is not bounds-checked before insertion")
    check("if (n3ds_wmi_unknown_seen[slot] > N3DS_WMI_UNKNOWN_DUMPS) {" in text,
          "the dump cap is not enforced")

    # Past the cap it must go quiet, not print once per event.
    check("if ((seen & (seen - 1)) == 0)" in text,
          "the suppressed path still prints on every event; that is the flood "
          "this patch exists to stop")

    # The dump must not read past the payload.
    check("dump_len = (len > N3DS_WMI_UNKNOWN_BYTES) ? "
          "N3DS_WMI_UNKNOWN_BYTES : len;" in text,
          "the payload dump is not clamped to the event length")
    check("char line[3 * N3DS_WMI_UNKNOWN_BYTES + 1];" in text,
          "the dump line buffer is not sized from the byte cap")

    check("AR6002 WMI unknown %s id=0x%04x #%u len=%u: %s" in text,
          "the dump line format changed; the capture instructions name it")

    # W14b: the connect event's own length, bounded.
    check("AR6002 WMI connect evt len=%d hdr=%u" in text,
          "the connect-event length log is missing")
    check("if (n3ds_connect_evt_dumps < 4) {" in text,
          "the connect-event length log is unbounded")

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
            check(b"AR6002 WMI unknown " in blob,
                  "baked initramfs module predates the unknown-event dump")
            check(b"Unknown id 0x%x" not in blob,
                  "the shipped module still carries the unbounded stock print")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_wmi_unknown_event_dump: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
