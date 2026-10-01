#!/usr/bin/env python3
"""Regression for NWM's selected-profile connection-scan contract."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_connection_scan.py")
CORPUS = ROOT / "scratch/nwm-full-corpus"
NWM_BIN = ROOT / "content/code_decompressed.bin"


def load_patcher():
    spec = importlib.util.spec_from_file_location("nwm_connection_scan", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_nwm_evidence() -> None:
    prepare = (CORPUS / "disassembly/0012ad70_FUN_0012ad70.txt").read_text()
    expected_calls = (
        "bl 0x0011a330",  # selected SSID slot 0
        "bl 0x0011a2b8",  # command 8 scan policy
        "bl 0x0011aa2c",  # command 17 channel table
        "bl 0x0011a390",  # command 9 BSS filter
        "bl 0x00133030",  # command 7 START_SCAN wrapper
    )
    positions = [prepare.index(call) for call in expected_calls]
    assert positions == sorted(positions)
    assert "0021  movs r1, #0x0" in prepare
    assert "0222  movs r2, #0x2" in prepare
    assert "0521  movs r1, #0x5" in prepare
    assert "1420  movs r0, #0x14" in prepare

    probed = (CORPUS / "functions/00136528_FUN_00136528.c").read_text()
    assert "param_2 < 6" in probed
    assert "FUN_00118140(param_1,iVar1,10,0)" in probed

    scan_policy = (CORPUS / "functions/0013664c_FUN_0013664c.c").read_text()
    assert "FUN_0011fff6(0x14)" in scan_policy
    assert "FUN_00118140(param_1,iVar1,8,0)" in scan_policy

    start_scan = (CORPUS / "disassembly/00136b9a_FUN_00136b9a.txt").read_text()
    assert "strb r6, [r0,#0x10]" in start_scan
    assert "strb r4, [r0,#0x11]" in start_scan
    assert "0722  movs r2, #0x7" in start_scan

    # 0x0012aec4 is the literal loaded three times for command 8's periods.
    image = NWM_BIN.read_bytes()
    assert len(image) == 348160
    assert image[0x2AEC4:0x2AEC8] == bytes.fromhex("ffff0000")


def main() -> None:
    # The evidence half reads Nintendo's NWM module and a Ghidra corpus made
    # from it. Neither is in the repository (the dump is the builder's own,
    # see README "Firmware"), so a fresh clone checks only the patch model.
    if CORPUS.is_dir() and NWM_BIN.is_file():
        assert_nwm_evidence()
    else:
        print("ar6014_nwm_connection_scan: NWM evidence skipped (no local NWM dump/corpus)")
    patcher = load_patcher()
    model = (
        patcher.HELPER_ANCHOR
        + patcher.SCAN_RET_OLD
        + patcher.FILTER_OLD
        + patcher.PREP_OLD
        + patcher.START_OLD
        + patcher.COMPLETE_OLD
    )
    patched = patcher.patch_cfg(model)
    assert patcher.MARKER in patched
    for token in (
        "n3ds_ar6014_program_scan_ssids(ar, request)",
        "wmi_scanparams_cmd(ar->arWmi, 0xffff, 0xffff, 0xffff",
        "N3DS_NWM_CONNECTION_SCAN_FLAGS",
        "wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE",
        "wmi_bssfilter_cmd(ar->arWmi",
        "N3DS_NWM_CONNECTION_SCAN_DWELL_MS, 0,\n                         0, NULL",
        "n3ds_ar6014_clear_scan_ssids(ar, request, true)",
        "n3ds_ar6014_clear_scan_ssids(ar, request, scan_info.aborted)",
    ):
        assert token in patched, token
    order = [
        patched.index("n3ds_ar6014_program_scan_ssids(ar, request)"),
        patched.index("wmi_scanparams_cmd(ar->arWmi"),
        patched.index("wmi_set_channelParams_cmd(ar->arWmi"),
        patched.index("wmi_bssfilter_cmd(ar->arWmi"),
        patched.index("wmi_startscan_cmd(ar->arWmi"),
    ]
    assert order == sorted(order)
    assert "programmed + 1" not in patched
    assert "num_channels, channel_list) != 0" not in patched.split(
        "wmi_startscan_cmd", 1
    )[1]
    assert patcher.patch_cfg(patched) == patched
    print("ar6014_nwm_connection_scan: PASS")


if __name__ == "__main__":
    main()
