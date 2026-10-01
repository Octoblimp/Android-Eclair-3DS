#!/usr/bin/env python3
"""Regression for Nintendo NWM's host-managed WPA WMI contract."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_host_wpa.py")
CORPUS = ROOT / "scratch/nwm-full-corpus/functions"


def load_patcher():
    assert PATCH_PATH.is_file(), f"missing implementation: {PATCH_PATH.name}"
    spec = importlib.util.spec_from_file_location("nwm_host_wpa_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_decompilation_evidence() -> None:
    appie = (CORPUS / "0013673e_FUN_0013673e.c").read_text(encoding="utf-8")
    assert "param_3 + 5U" in appie
    assert "*puVar2 = param_2" in appie
    assert "puVar2[1] = (short)param_3" in appie
    assert "FUN_00121804(puVar2 + 2,param_4,param_3)" in appie
    assert "FUN_00118140(param_1,iVar1,0x3f,0)" in appie

    defaults = (CORPUS / "00118f64_FUN_00118f64.c").read_text(encoding="utf-8")
    for offset in ("0x216", "0x217", "0x218", "0x21a"):
        assert f"(param_1 + {offset}) = 1" in defaults
    for offset in ("0x219", "0x21b"):
        assert f"(param_1 + {offset}) = 0" in defaults

    aes_install = (CORPUS / "001191e8_FUN_001191e8.c").read_text(encoding="utf-8")
    assert "FUN_00118fe0" in aes_install
    assert ",4,3," in aes_install
    assert ",3,0);" in aes_install

    live_profile = (CORPUS / "00119f54_FUN_00119f54.c").read_text(
        encoding="utf-8"
    )
    assert "param_4 != 0x10" in live_profile
    assert "uVar1 = 4;" in live_profile
    assert "(param_1 + 0x218) = uVar1" in live_profile
    assert "(param_1 + 0x21a) = uVar1" in live_profile
    assert "(param_1 + 0x217) = 1" in live_profile

    connect = (CORPUS / "00131d40_nwm_connect_profile.c").read_text(
        encoding="utf-8"
    )
    for offset in ("0x218", "0x219", "0x21a", "0x21b"):
        assert f"(param_1 + {offset})" in connect
    assert "nwm_wmi_connect_cmd" in connect


def main() -> None:
    assert_decompilation_evidence()
    patcher = load_patcher()

    assert patcher.nwm_appie_payload(3, b"\x30\x02\x01\x00") == (
        b"\x03\x00\x04\x00\x30\x02\x01\x00\x00"
    )
    assert patcher.nwm_appie_payload(3, b"") == b"\x03\x00\x00\x00\x00\x00"
    assert patcher.nwm_key_type(1) == 1
    assert patcher.nwm_key_type(2) == 2
    assert patcher.nwm_key_type(8) == 4
    payload = patcher.nwm_connect_payload(
        b"HomeWifi", bytes.fromhex("8cdd0b0053c8"), 2437, 0
    )
    assert len(payload) == 52
    assert payload[:16] == bytes.fromhex("0101010400040008486f6d6557696669")
    assert payload[40:42] == (2437).to_bytes(2, "little")
    assert payload[42:48] == bytes.fromhex("8cdd0b0053c8")
    assert payload[48:52] == b"\0\0\0\0"

    cfg = patcher.patch_cfg(patcher.CFG_OLD)
    wmi = patcher.patch_wmi(patcher.WMI_APPIE_OLD + patcher.WMI_KEY_OLD)
    api = patcher.patch_wmi_api(patcher.WMI_API_OLD)

    assert cfg.count("N3DS_AR6014_NWM_HOST_WPA") == 1
    assert cfg.index("wmi_set_appie_cmd") < cfg.index("wmi_connect_cmd")
    assert "ar->arDot11AuthMode, NONE_AUTH" in cfg
    assert "nwm_pairwise_crypto = (CRYPTO_TYPE)4" in cfg
    assert "nwm_group_crypto = (CRYPTO_TYPE)4" in cfg
    assert "ar->arPairwiseCrypto == AES_CRYPT" in cfg
    assert "ar->arGroupCrypto == AES_CRYPT" in cfg
    assert "N3DS_AR6014_NWM_LIVE_PROTECTED_TUPLE" in cfg
    assert "wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0)" in cfg
    assert "wmi_bssfilter_cmd(ar->arWmi, NONE_BSS_FILTER, 0)" not in cfg
    assert "WEP_CRYPT" in cfg
    assert "NWM APP-IE len=%u" in cfg
    assert "if (status != 0)" in cfg
    assert "A_OK" not in cfg
    assert wmi.count("N3DS_AR6014_NWM_APPIE_LAYOUT") == 1
    assert wmi.count("N3DS_AR6014_NWM_AES_KEY_TYPE") == 1
    assert "cmdLen = ieLen ? ieLen + 5 : 6;" in wmi
    assert "((u16 *)cmd)[0] = (u16)mgmtFrmType;" in wmi
    assert "((u16 *)cmd)[1] = ieLen;" in wmi
    assert "cmd->keyType  = nwm_key_type;" in wmi
    assert "u16 ieLen" in api

    assert patcher.patch_cfg(cfg) == cfg
    split_cfg = (
        "/* N3DS_AR6014_DISCOVERY_CONNECT_SPLIT */\n"
        + patcher.CFG_CRYPTO_NEW
        + "    status = wmi_set_appie_cmd(ar->arWmi, WMI_FRAME_ASSOC_REQ,\n"
        + "    wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0);\n"
    )
    assert patcher.patch_cfg(split_cfg) == split_cfg
    assert patcher.patch_wmi(wmi) == wmi
    assert patcher.patch_wmi_api(api) == api
    print("ar6014_nwm_host_wpa: PASS")


if __name__ == "__main__":
    main()
