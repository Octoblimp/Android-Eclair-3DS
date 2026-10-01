#!/usr/bin/env python3
"""Regression for Nintendo NWM persistent channel-table programming."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_channel_table.py")
CORPUS = ROOT / "scratch/nwm-full-corpus/functions"


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location("nwm_channel_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_nwm_evidence() -> None:
    workflow = (CORPUS / "0012ad70_FUN_0012ad70.c").read_text(encoding="utf-8")
    assert "nwm_connect_setup_11aa2c" in workflow
    assert workflow.index("nwm_connect_setup_11aa2c") < workflow.index(
        "nwm_connect_setup_11a390"
    )
    assert workflow.index("nwm_connect_setup_11aa2c") < workflow.index(
        "nwm_set_scan_params"
    )

    wrapper = (CORPUS / "0011aa2c_nwm_connect_setup_11aa2c.c").read_text(
        encoding="utf-8"
    )
    assert "FUN_00136830" in wrapper
    assert ",0,param_3,(int)(char)param_4,param_5" in wrapper

    serializer = (CORPUS / "00136830_FUN_00136830.c").read_text(
        encoding="utf-8"
    )
    assert "*(undefined1 *)(iVar2 + 1) = param_2" in serializer
    assert "*(undefined1 *)(iVar2 + 2) = param_3" in serializer
    assert "*(char *)(iVar2 + 3) = (char)param_4" in serializer
    assert "FUN_00121804(iVar2 + 4,param_5,param_4 * 2)" in serializer
    assert "FUN_00118140(param_1,iVar1,0x11,0)" in serializer


def main() -> None:
    # The evidence half reads a Ghidra corpus of Nintendo's NWM module, which
    # is not in the repository; a fresh clone checks only the patch model.
    if CORPUS.is_dir():
        assert_nwm_evidence()
    else:
        print("ar6014_nwm_channel_table: NWM evidence skipped (no local corpus)")
    patcher = load_patcher()

    payload = patcher.nwm_channel_payload([2412, 2437, 2462, 2484])
    assert payload[:4] == bytes((0, 0, 2, 4))
    assert payload[4:] == bytes.fromhex("6c09 8509 9e09 b409")
    for bad in (0, 2413, 5000):
        try:
            patcher.nwm_channel_payload([bad])
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted invalid channel {bad}")

    model = patcher.HELPER_OLD + patcher.CONNECT_OLD + patcher.SCAN_ANCHOR
    patched = patcher.patch_cfg(model)
    assert patched.count(patcher.MARKER) == 2
    assert "wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE" in patched
    assert "num_channels, channel_list" in patched
    assert "ARRAY_SIZE(channel_list), channel_list" in patched
    assert "up(&ar->arSem);" in patched
    assert "NWM channel table mode=11G" in patched
    assert "N3DS_AR6014_CHANNEL_TABLE" not in patched
    assert patcher.patch_cfg(patched) == patched
    print("ar6014_nwm_channel_table: PASS")


if __name__ == "__main__":
    main()
