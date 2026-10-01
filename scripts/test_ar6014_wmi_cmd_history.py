#!/usr/bin/env python3
"""Pin the WMI command-history ring and the connect/commit payload dump (A4/W7).

The target asserts during AP bring-up and leaves a register dump that names no
command.  This ring is the only thing that will say what the host had just
sent, so what matters is that it is recorded on every send, printed from the
assert handler, safe to touch from atomic context, and bounded.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_wmi_cmd_history.py")
BASE = ROOT / "third_party/linux/drivers/staging/ath6k_legacy"
WMI_C = BASE / "wmi/wmi.c"
WMI_API_H = BASE / "include/wmi_api.h"
DRV_C = BASE / "os/linux/ar6000_drv.c"
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_wmi_cmd_history_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_transform(patcher) -> None:
    """Each file's hunks must apply once against its own pre-patch fixture."""
    for path in (WMI_API_H, WMI_C, DRV_C):
        fixture = "".join(old for target, _, old, _ in patcher.HUNKS
                          if target == path)
        assert fixture, f"no hunks registered for {path.name}"
        patched = patcher.patch_text(path, fixture)
        assert patched != fixture, f"{path.name}: patcher did nothing"
        assert patcher.MARKER in patched, f"{path.name}: marker not written"
        assert patcher.patch_text(path, patched) == patched, (
            f"{path.name}: patcher is not idempotent")


def assert_ring(text: str) -> None:
    assert "N3DS_WMI_HISTORY_DEPTH" in text, "history ring missing"
    depth = re.search(r"#define N3DS_WMI_HISTORY_DEPTH (\d+)", text)
    assert depth, "ring depth is not a compile-time constant"
    assert 8 <= int(depth.group(1)) <= 64, (
        f"ring depth {depth.group(1)} is not a sane bound")

    # A command can be sent from atomic context, so the ring must not sleep
    # and must not allocate.
    assert "DEFINE_SPINLOCK(n3ds_wmi_history_lock)" in text
    assert text.count("spin_lock_irqsave(&n3ds_wmi_history_lock") == 2
    assert text.count("spin_unlock_irqrestore(&n3ds_wmi_history_lock") == 2
    for banned in ("kmalloc", "kzalloc", "msleep", "A_MALLOC"):
        record = text[text.index("static void n3ds_wmi_history_record"):
                      text.index("/*\n * Called to send a wmi command")]
        assert banned not in record, f"{banned} in the ring write path"

    # Recorded on every send, from the one place every command goes through.
    assert "n3ds_wmi_history_record((u16)cmdId, (u16)A_NETBUF_LEN(osbuf));" \
        in text, "sends are not recorded"

    # Dumped oldest-first so the final line is the command in flight.
    assert "void n3ds_wmi_history_dump(const char *why)" in text
    assert "for (i = depth; i > 0; i--)" in text, (
        "history is not printed oldest-first")
    # The format string wraps across two source lines.
    assert "AR6002 WMI history: -%u cmd=0x%04x len=%u " in text
    assert "age=%ums" in text


def assert_payload_dump(text: str) -> None:
    assert "WMI_CONNECT_CMDID || cmdId == WMI_AP_CONFIG_COMMIT_CMDID" in text, (
        "the payload dump does not cover both connect and AP commit")
    assert "AR6002 WMI tx cmd=0x%04x +%02u: %s" in text

    # Bounded twice over: a capped number of dumps, and a capped dump length.
    budget = re.search(r"n3ds_wmi_payload_dumps < (\d+)", text)
    assert budget, "payload dump has no budget"
    assert int(budget.group(1)) <= 32, "payload dump budget is too generous"
    assert "n3ds_wmi_payload_dumps++;" in text
    assert re.search(r"if \(dump_len > 64\)\s*\n\s*dump_len = 64;", text), (
        "payload dump is not length-capped")
    # The hex line buffer must hold 16 groups of "xx " plus a terminator.
    assert "char line[3 * 16 + 1];" in text
    assert "line[3 * chunk] = '\\0';" in text


def main() -> None:
    patcher = load_patcher()
    assert_transform(patcher)

    wmi_c = WMI_C.read_text(encoding="utf-8")
    api_h = WMI_API_H.read_text(encoding="utf-8")
    drv_c = DRV_C.read_text(encoding="utf-8")

    assert "void n3ds_wmi_history_dump(const char *why);" in api_h, (
        "no prototype; ar6000_drv.c would call this implicitly")
    assert_ring(wmi_c)
    assert_payload_dump(wmi_c)

    # The whole point: the assert handler prints it, before the register dump
    # that names nothing.
    assert 'n3ds_wmi_history_dump("target assert");' in drv_c
    assert drv_c.index('n3ds_wmi_history_dump("target assert")') < \
        drv_c.index("ar6000_dump_target_assert_info(ar->arHifDevice"), (
            "history must be printed before the register dump")

    for path, text in ((WMI_C, wmi_c), (WMI_API_H, api_h), (DRV_C, drv_c)):
        assert patcher.patch_text(path, text) == text, (
            f"{path.name} is not patched")

    if not INITRAMFS.is_file():
        print("  (no built initramfs; skipping shipped-module check)")
    else:
        blob = subprocess.run(
            f'zcat "{INITRAMFS}" | cpio -i --to-stdout {BAKED_MODULE} '
            f'2>/dev/null', shell=True, capture_output=True).stdout
        assert blob, "initramfs carries no ath6kl.ko"
        assert b"AR6002 WMI history" in blob, (
            "the initramfs ath6kl.ko predates the command ring -- rebuild")

    print("ar6014_wmi_cmd_history: PASS "
          "(ring recorded, dumped at assert, payload dump bounded)")


if __name__ == "__main__":
    main()
