#!/usr/bin/env python3
"""Pin the compacted target register dump (A9).

This is an evidence fix, not a behaviour fix.  60 registers at one line each
filled the entire 64-line delayed Wi-Fi trace window, so both Mobile Data
captures so far contain the register dump and nothing else -- no ``AR6002 AP:``
profile lines and no WMI command-history ring, i.e. none of the evidence that
names the command the target asserted on.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/miscdrv/common_drv.c")
INITRAMFS = Path(f"{A3DS_ROOT}/sdcard/linux/initramfs.cpio.gz")

WORDS_PER_LINE = 8

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_ar6014_regdump_compact",
        HERE / "patch_ar6014_regdump_compact.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from common_drv.c")
    check(patcher.patch_common_drv(text) == text, "patcher is not idempotent")

    # The one-line-per-register loop is the whole problem.
    check("index=%u value=0x%08x" not in text,
          "the one-line-per-register dump is back; a single assert emits 60 "
          "lines and evicts the AP evidence around it")
    check("for (i = 0; i < regDumpCount; i += 8) {" in text,
          "the dump no longer batches registers per line")
    check("AR6002 REGDUMP base=0x%08x +%02u: %s" in text,
          "the compact dump line format changed")

    # A partial final batch must not read past the end of regDumpValues[].
    check("u32 chunk = regDumpCount - i;" in text,
          "the final partial batch is not computed from the remaining count")
    check("if (chunk > 8) {" in text,
          "the batch size is not clamped; a full batch would read past the "
          "register array on the last iteration")

    # The line buffer must hold a full batch of "%08x " plus the terminator.
    check(f"char line[{WORDS_PER_LINE} * 9 + 1];" in text,
          "the dump line buffer is not sized for a full batch")
    check("snprintf(line + (9 * w), 10, \"%08x \", regDumpValues[i + w]);"
          in text,
          "the per-word format changed; the buffer sizing assumes 9 chars per "
          "word")
    check("line[9 * chunk] = 0;" in text,
          "the line is not terminated after a partial batch, so a short final "
          "batch would print stale bytes from the previous one")

    # 60 registers must now fit in far fewer lines than the trace window.
    reg_dump_count = 60
    lines = -(-reg_dump_count // WORDS_PER_LINE)
    check(lines <= 8,
          f"a {reg_dump_count}-register dump still costs {lines} lines")

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
            check(b"AR6002 REGDUMP base=0x%08x +%02u" in blob,
                  "baked initramfs module predates the compact register dump")
            check(b"index=%u value=0x%08x" not in blob,
                  "the shipped module still carries the 60-line dump")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_regdump_compact: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
