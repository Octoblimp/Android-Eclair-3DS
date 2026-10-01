#!/usr/bin/env python3
"""Regression contract for failed-connect handoff and RSSI export."""

import importlib.util
from pathlib import Path


PATCH_PATH = Path(__file__).with_name("patch_ar6014_direct_reconnect.py")


def load_patcher():
    spec = importlib.util.spec_from_file_location("direct_reconnect_patch", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    patcher = load_patcher()
    patch = PATCH_PATH.read_text()
    for marker in (
        "N3DS_AR6014_RECONNECT_REMOVED",
        "N3DS_AR6014_CFG80211_DBM_SIGNAL",
        "reason=%u raw=%*ph",
        "signal = (s32)ni->ni_rssi * 100",
        "N3DS_AR6014_NO_NETWORK_HANDOFF",
        "N3DS_AR6014_NWM_DISCONNECT_BOUNDS",
    ):
        assert marker in patch, marker

    for old_block in (patcher.OLD_RECONNECT, patcher.NEW_RECONNECT):
        driver = "unsigned int wlanNodeCaching = 1;\n" + old_block
        updated = patcher.patch_driver(driver)
        assert "wmi_reconnect_cmd" not in updated
        assert "wmi_disconnect_cmd" not in updated
        assert "n3ds_ar6014_reconnect_used" not in updated
        assert updated.count("N3DS_AR6014_RECONNECT_REMOVED") == 1

    cfg = (
        "extern bool n3ds_ar6014_reconnect_used;\n"
        "    n3ds_ar6014_reconnect_used = false;\n"
        "    signal  = ni->ni_snr * 100;\n"
        + patcher.CFG_NO_NETWORK_OLD + "\n"
    )
    updated_cfg = patcher.patch_cfg(cfg)
    assert "n3ds_ar6014_reconnect_used" not in updated_cfg
    assert "signal = (s32)ni->ni_rssi * 100" in updated_cfg
    assert "cfg80211_connect_result" in updated_cfg
    assert "ar->arConnectPending = false" in updated_cfg
    assert "N3DS_AR6014_NO_NETWORK_HANDOFF" in updated_cfg
    assert "ni->ni_snr * 100" not in patch.split("def patch_cfg", 1)[1].split(
        "def patch_wmi", 1
    )[0].split("new = '''", 1)[1]
    wmi = '''        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: short disconnect len=%d reason=%u\\n", len, reason));
    ev = (WMI_DISCONNECT_EVENT *)datap;

    A_MEMZERO(wmip->wmi_bssid, sizeof(wmip->wmi_bssid));
'''
    updated_wmi = patcher.patch_wmi(wmi)
    assert "ev->assocRespLen > len - 10" in updated_wmi
    assert "NWM disconnect len=%d reason=%u status=%u" in updated_wmi
    assert patcher.patch_cfg(updated_cfg) == updated_cfg
    assert patcher.patch_wmi(updated_wmi) == updated_wmi
    print("ar6014_failed_connect_handoff: PASS")


if __name__ == "__main__":
    main()
