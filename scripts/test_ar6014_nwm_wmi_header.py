#!/usr/bin/env python3
"""Regression for Nintendo NWM's two-byte WMI command/event header."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_wmi_header.py")
CORPUS = ROOT / "scratch/nwm-full-corpus/functions"


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location("nwm_wmi_header_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_decompilation_evidence() -> None:
    send = (CORPUS / "00118140_FUN_00118140.c").read_text(encoding="utf-8")
    assert "FUN_0011ffea(param_2,2)" in send
    assert "puVar2 = (undefined2 *)FUN_00120688(param_2)" in send
    assert "*puVar2 = (short)param_3" in send

    receive = (CORPUS / "001353ec_FUN_001353ec.c").read_text(encoding="utf-8")
    assert "if (uVar4 < 2)" in receive
    assert "uVar4 = (uint)*puVar5" in receive
    assert "FUN_0011f6c0(param_2,2)" in receive


def main() -> None:
    assert_decompilation_evidence()
    patcher = load_patcher()
    source = (
        patcher.WMI_RX_OLD
        + "\n"
        + patcher.WMI_TX_OLD
        + "\n"
        + patcher.WMI_SHORT_OLD
    )
    patched = patcher.patch_wmi(source)

    assert patched.count("N3DS_AR6014_NWM_WMI_U16_HEADER") == 2
    assert "A_NETBUF_LEN(osbuf) < sizeof(u16)" in patched
    assert "id = *(u16 *)A_NETBUF_DATA(osbuf);" in patched
    assert "A_NETBUF_PULL(osbuf, sizeof(u16))" in patched
    assert "A_NETBUF_PUSH(osbuf, sizeof(u16))" in patched
    assert "*(u16 *)A_NETBUF_DATA(osbuf) = (u16)cmdId;" in patched
    assert "AR6002 WMI: NWM u16 command/event header active" in patched
    assert "cHdr->info1 = 0" not in patched
    assert patched.count("N3DS_AR6014_NWM_SHORT_DISCONNECT_LAYOUT") == 1
    assert patched.count("N3DS_AR6014_SHORT_DISCONNECT") == 1
    assert "memcpy(shortBssid, datap, ATH_MAC_LEN);" in patched
    assert "reason = datap[ATH_MAC_LEN];" in patched
    assert "reason at offset four" not in patched
    assert patcher.patch_wmi(patched) == patched
    print("ar6014_nwm_wmi_header: PASS")


if __name__ == "__main__":
    main()
