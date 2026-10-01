#!/usr/bin/env python3
"""Regression for Nintendo NWM's exact 16-byte READY event layout."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_ready_layout.py")
CORPUS = ROOT / "scratch/nwm-full-corpus/functions"


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location("nwm_ready_layout_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_decompilation_evidence() -> None:
    receive = (CORPUS / "001353ec_FUN_001353ec.c").read_text(encoding="utf-8")
    assert "if (0xf < uVar8)" in receive
    assert "uVar3 = (undefined2)puVar7[3]" in receive
    assert "uVar10 = *(undefined2 *)((int)puVar7 + 0xe)" in receive
    assert "*(byte *)((int)puVar7 + 6),puVar7[2],uVar3,uVar10" in receive


def main() -> None:
    assert_decompilation_evidence()
    patcher = load_patcher()
    patched = patcher.patch_wmi(patcher.READY_OLD)

    assert patched.count("N3DS_AR6014_NWM_READY_LAYOUT") == 1
    assert "u8 macaddr[ATH_MAC_LEN];" in patched
    assert "u8 phyCapability;" in patched
    assert "u8 reserved;" in patched
    assert "u32 sw_version;" in patched
    assert "u16 version_12;" in patched
    assert "u16 version_14;" in patched
    assert "len == sizeof(NWM_READY_EVENT)" in patched
    assert "nwm->macaddr" in patched
    assert "nwm->phyCapability" in patched
    assert "nwm->sw_version" in patched
    assert "nwm->abi_version" not in patched
    assert "NWM READY len=%d" in patched
    assert patcher.patch_wmi(patched) == patched
    print("ar6014_nwm_ready_layout: PASS")


if __name__ == "__main__":
    main()
