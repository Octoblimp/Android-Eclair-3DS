#!/usr/bin/env python3
"""Static regression checks for the AR6014 invalid-channel panic fix.

The canonical kernel checkout lives in WSL and is not present in this Windows
workspace, so these checks exercise the mirrored sources and the patch
script's required invariants without attempting a host kernel build.
"""

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DRV = (ROOT / "scratch/niazlv-linux/drivers/staging/ath6kl/"
       "os/linux/ar6000_drv.c").read_text()
CFG = (ROOT / "scratch/niazlv-linux/drivers/staging/ath6kl/"
       "os/linux/cfg80211.c").read_text()
WMI = (ROOT / "scratch/niazlv-linux/drivers/staging/ath6kl/wmi/wmi.c").read_text()
PATCH = (ROOT / "scripts/patch_wifi_bss_channel_guard.py").read_text()


def channel_mhz(channel):
    """Model the parser's accepted 2.4-GHz channel mapping."""
    if channel == 14:
        return 2484
    if 1 <= channel <= 13:
        return 2407 + 5 * channel
    return None


def fresh_wmi_patch_smoke():
    """Apply patch_wmi to a fresh fixture with duplicate bih declarations."""
    spec = importlib.util.spec_from_file_location(
        "wifi_bss_channel_patcher", ROOT / "scripts/patch_wifi_bss_channel_guard.py"
    )
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)

    fixture = ("static A_STATUS\n"
               "wmi_bssInfo_event_rx(struct wmi_t *wmip, A_UINT8 *datap, int len)\n"
               "{\n"
               "    WMI_BSS_INFO_HDR *bih;\n"
               "    if (len <= sizeof(WMI_BSS_INFO_HDR)) {\n"
               "        return A_EINVAL;\n"
               "    }\n"
               "    bih = (WMI_BSS_INFO_HDR *)datap;\n"
               "    bss = wlan_find_node(&wmip->wmi_scan_table, bih->bssid);\n"
               "    return A_OK;\n"
               "}\n"
               "static A_STATUS another_handler(A_UINT8 *datap)\n"
               "{\n"
               "    WMI_BSS_INFO_HDR *bih = (WMI_BSS_INFO_HDR *)datap;\n"
               "    return bih->channel;\n"
               "}\n")
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "wmi.c"
        path.write_text(fixture)
        old_path = patcher.WMI
        try:
            patcher.WMI = path
            patcher.patch_wmi()
            first_result = path.read_text()
            patcher.patch_wmi()
        finally:
            patcher.WMI = old_path
        result = path.read_text()
    handler_start = result.index("wmi_bssInfo_event_rx")
    next_handler = result.index("another_handler")
    marker = result.index("N3DS_WMI_BSS_CHANNEL_GUARD")
    lookup = result.index("wlan_find_node")
    assert handler_start < marker < lookup < next_handler
    assert result[next_handler:] == fixture[fixture.index("another_handler"):]
    assert first_result == result
    assert result.count("N3DS_WMI_BSS_CHANNEL_GUARD") == 1
    assert result.count("bih = (WMI_BSS_INFO_HDR *)datap;") == 2
    assert "bih->channel > 2472" in result


def fresh_cfg_patch_smoke():
    """Apply cfg guards to canonical-style four-space/kfree source."""
    spec = importlib.util.spec_from_file_location(
        "wifi_cfg_channel_patcher", ROOT / "scripts/patch_wifi_bss_channel_guard.py"
    )
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)

    fixture = ("static void scan_node(void)\n"
               "{\n"
               "    channel = ieee80211_get_channel(wiphy, freq);\n"
               "    cfg80211_inform_bss_frame(wiphy, channel, mgmt, size, signal, GFP_KERNEL);\n"
               "    kfree(ieeemgmtbuf);\n"
               "}\n"
               "static void connect_event(void)\n"
               "{\n"
               "    ibss_channel = ieee80211_get_channel(ar->wdev->wiphy, (int)channel);\n"
               "    cfg80211_inform_bss_frame(ar->wdev->wiphy, ibss_channel, mgmt, size, signal, GFP_KERNEL);\n"
               "    kfree(ieeemgmtbuf);\n"
               "}\n")
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "cfg80211.c"
        path.write_text(fixture)
        old_path = patcher.CFG
        try:
            patcher.CFG = path
            patcher.patch_cfg80211()
            first_result = path.read_text()
            patcher.patch_cfg80211()
        finally:
            patcher.CFG = old_path
        result = path.read_text()
    assert result.count("N3DS_CFG80211_BSS_CHANNEL_GUARD") == 2
    assert result.count("if (!channel)") == 1
    assert result.count("if (!ibss_channel)") == 1
    assert "    kfree(ieeemgmtbuf);" in result
    assert first_result == result


def main():
    fresh_wmi_patch_smoke()
    fresh_cfg_patch_smoke()
    assert channel_mhz(1) == 2412
    assert channel_mhz(13) == 2472
    assert channel_mhz(14) == 2484
    assert channel_mhz(0) is None
    assert channel_mhz(15) is None

    assert "p[2] >= 1 && p[2] <= 14" in DRV
    assert "p[0] == 61" in DRV
    assert "(p[2] == 14) ? 2484" in DRV
    assert "!chanMhz" in DRV

    assert "N3DS_CFG80211_BSS_CHANNEL_GUARD" in CFG
    assert CFG.count("if (!channel)") >= 1
    assert "N3DS_WMI_BSS_CHANNEL_GUARD" in WMI
    assert "bih->channel > 2472" in WMI
    assert "bih->channel != 2484" in WMI

    # The persistent patch must retain the exact invariants on future source
    # refreshes and choose the matching free primitive.
    assert "p[2] <= 14" in PATCH
    assert "bih->channel > 2472" in PATCH
    assert 'free_call = "kfree"' in PATCH
    print("wifi_bss_channel_guard: PASS")


if __name__ == "__main__":
    main()
