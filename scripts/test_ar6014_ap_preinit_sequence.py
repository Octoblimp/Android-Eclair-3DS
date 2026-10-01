#!/usr/bin/env python3
"""Pin the AP pre-init sequence and bring-up traces (A5 + A6).

Mobile Data now fails with a firmware assert during AP bring-up.  Two things
have to hold for the next hardware run to be worth flashing: the target has to
be given the AP parameters stock ath6kl programs before it commits a profile,
and every command in that sequence has to announce its ID before it is sent, so
an assert lands between two known log lines instead of somewhere inside "AP
bring-up".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_ap_preinit_sequence.py")
BASE = ROOT / "third_party/linux/drivers/staging/ath6k_legacy"
DRV_C = BASE / "os/linux/ar6000_drv.c"
WMI_H = BASE / "include/common/wmi.h"
INITRAMFS = ROOT / "sdcard/linux/initramfs.cpio.gz"
BAKED_MODULE = "n3ds/modules/ath6kl.ko"

# Command name -> the WMI helper that sends it.
EXPECTED_STEPS = (
    ("hidden_ssid", "WMI_AP_HIDDEN_SSID_CMDID", "wmi_ap_set_hidden_ssid"),
    ("num_sta", "WMI_AP_SET_NUM_STA_CMDID", "wmi_ap_set_num_sta"),
    ("acl_policy", "WMI_AP_ACL_POLICY_CMDID", "wmi_ap_set_acl_policy"),
    ("conn_inact", "WMI_AP_CONN_INACT_CMDID", "wmi_ap_conn_inact_time"),
    ("prot_scan_time", "WMI_AP_PROT_SCAN_TIME_CMDID", "wmi_ap_bgscan_time"),
)


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location(
        "ar6014_ap_preinit_sequence_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_transform(patcher) -> None:
    fixture = "".join(old for _, old, _ in patcher.HUNKS)
    patched = patcher.patch_drv(fixture)
    assert patched != fixture, "patcher did nothing to the pre-patch fixture"
    assert patcher.MARKER in patched
    assert patcher.patch_drv(patched) == patched, "patcher is not idempotent"


def assert_steps(text: str) -> None:
    body = re.search(
        r"static void n3ds_ar6000_ap_preinit\(struct ar6_softc \*ar\)\n\{"
        r"(.*?)\n\}", text, re.S)
    assert body, "n3ds_ar6000_ap_preinit() missing"
    seq = body.group(1)

    for name, cmd_id, helper in EXPECTED_STEPS:
        assert f'"{name}"' in seq, f"pre-init step {name} missing"
        assert cmd_id in seq, f"{name} does not name {cmd_id}"
        assert helper in seq, f"{name} does not call {helper}"

    # Order matters: the commit has to be last, and the sequence has to run in
    # the order stock ath6kl uses.
    positions = [seq.index(f'"{name}"') for name, _, _ in EXPECTED_STEPS]
    assert positions == sorted(positions), "pre-init steps are out of order"

    # Every step announces its command ID *before* sending, or an assert
    # cannot be attributed to a command.
    step = re.search(r"#define N3DS_AP_PREINIT_STEP\((.*?)\n\n", text, re.S)
    assert step, "N3DS_AP_PREINIT_STEP macro missing"
    macro = step.group(1)
    assert macro.index("submit") < macro.index("status=%d"), (
        "the step macro logs the result before it logs the submission")


def assert_commit_bracket(text: str) -> None:
    commit = text.index("status = wmi_ap_profile_commit(ar->arWmi, &p);")
    preinit = text.index("n3ds_ar6000_ap_preinit(ar);")
    assert preinit < commit, "pre-init must run before the commit"

    submit_log = text.index("AR6002 AP: commit cmd=0x%04x submit")
    assert preinit < submit_log < commit, (
        "the commit submission is not logged between pre-init and the send")
    assert "AR6002 AP: commit cmd=0x%04x status=%d" in text

    # The AP profile must not inherit whatever ctrl_flags the station sweep
    # left in ar->arConnectCtrlFlags.
    reset = text.index("ar->arConnectCtrlFlags = 0;\n    p.ctrl_flags =")
    assert reset < commit, "AP ctrl_flags are not reset before the commit"

    # A/B switch, so a run can separate "pre-init caused the assert" from
    # "pre-init did not help" without building a second driver.
    assert "module_param(n3ds_ap_preinit, int, 0644)" in text
    assert "if (!n3ds_ap_preinit)" in text
    assert "AR6002 AP: preinit disabled by n3ds_ap_preinit=0" in text


def assert_boundary_traces(text: str) -> None:
    # The two facts no capture has ever contained.
    assert "AR6002 AP: BMI fwmode=%u hi_option_flag=0x%08x" in text
    assert "AR6002 AP: WMI ready nettype=%u nextmode=%u wlanstate=%u" in text
    # The WMI-ready trace has to read the state before arWmiReady is set,
    # otherwise it says nothing the commit guard could not already see.
    ready_log = text.index("AR6002 AP: WMI ready nettype=")
    ready_set = text.index("ar->arWmiReady = true;")
    assert ready_log < ready_set


def assert_command_ids() -> None:
    """Every command the sequence names must exist with a real value."""
    header = WMI_H.read_text(encoding="utf-8")
    for _, cmd_id, _ in EXPECTED_STEPS:
        assert cmd_id in header, f"{cmd_id} is not defined in wmi.h"
    # The whole AP block is a renumbering guess; if it ever moves back out of
    # the 0x004A range this test should fail loudly rather than silently test
    # a different command.
    assert re.search(r"WMI_AP_HIDDEN_SSID_CMDID\s*=\s*0x004A", header), (
        "the AP command block is no longer based at 0x004A")


def main() -> None:
    patcher = load_patcher()
    assert_transform(patcher)
    assert_command_ids()

    text = DRV_C.read_text(encoding="utf-8")
    assert_steps(text)
    assert_commit_bracket(text)
    assert_boundary_traces(text)
    assert patcher.patch_drv(text) == text, "tree is not patched"

    if not INITRAMFS.is_file():
        print("  (no built initramfs; skipping shipped-module check)")
    else:
        blob = subprocess.run(
            f'zcat "{INITRAMFS}" | cpio -i --to-stdout {BAKED_MODULE} '
            f'2>/dev/null', shell=True, capture_output=True).stdout
        assert blob, "initramfs carries no ath6kl.ko"
        assert b"AR6002 AP: preinit" in blob, (
            "the initramfs ath6kl.ko predates the AP pre-init sequence")

    print("ar6014_ap_preinit_sequence: PASS "
          f"({len(EXPECTED_STEPS)} steps, each announced before it is sent)")


if __name__ == "__main__":
    main()
