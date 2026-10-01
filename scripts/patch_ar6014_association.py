#!/usr/bin/env python3
"""Install the Nintendo AR6014 association compatibility path."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"
DRV = ROOT / "os/linux/ar6000_drv.c"
WMI = ROOT / "wmi/wmi.c"
MARKER = "N3DS_AR6014_ASSOCIATION_COMPAT"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def repair_generated_c_strings(text: str) -> str:
    """Normalize newline escapes from an earlier generated-source revision."""
    for fragment in (
        "submit channel=%u flags=0x%x bssid=%pM",
        "bounded reconnect channel=%u bssid=%pM",
        "short disconnect len=%d reason=%u",
    ):
        text = text.replace(fragment + "\n\"", fragment + "\\n\"")
    return text


def patch_cfg(text: str) -> str:
    text = repair_generated_c_strings(text)
    if MARKER in text:
        return text
    anchor = "extern int reconnect_flag;\n\n\n"
    helper = r'''extern int reconnect_flag;
extern bool n3ds_ar6014_reconnect_used;

/* N3DS_AR6014_ASSOCIATION_COMPAT: this exact Nintendo type-4 image keeps
 * connect-time channel entry zero at 0x525548.  The public 3DS capture proved
 * WMI_CONNECT's channel field is ignored.  Validate entries 1..3 before
 * changing entry zero so a different firmware build fails closed. */
#define N3DS_AR6014_CHANNEL_TABLE 0x00525548
static int n3ds_ar6014_set_search_channel(struct ar6_softc *ar, u16 mhz)
{
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: search channel %u -> %u MHz\n", mhz, mhz));
    return 0;
}


'''
    text = replace_once(text, anchor, helper, "cfg helper insertion")
    auth_anchor = """    ar6k_set_wpa_version(ar, sme->crypto.wpa_versions);
    ar6k_set_auth_type(ar, sme->auth_type);
"""
    auth_add = auth_anchor + """
    n3ds_ar6014_reconnect_used = false;
    if (ar->arChannelHint)
        n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
"""
    text = replace_once(text, auth_anchor, auth_add, "connect channel steering")
    call_anchor = """    reconnect_flag = 0;
    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
"""
    call_add = """    reconnect_flag = 0;
    /* Register the directed SSID and tell the target that cfg80211 already
     * selected the BSS. */
    wmi_probedSsid_cmd(ar->arWmi, 0, SPECIFIC_SSID_FLAG,
                       ar->arSsidLen, ar->arSsid);
    ar->arConnectCtrlFlags |= DEFAULT_CONNECT_CTRL_FLAGS;
    if (ar->arReqBssid[0] || ar->arReqBssid[1] || ar->arReqBssid[2] ||
        ar->arReqBssid[3] || ar->arReqBssid[4] || ar->arReqBssid[5])
        ar->arConnectCtrlFlags |= CONNECT_PROFILE_MATCH_DONE;
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: submit channel=%u flags=0x%x bssid=%pM\\n",
         ar->arChannelHint, ar->arConnectCtrlFlags, ar->arReqBssid));
    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
"""
    return replace_once(text, call_anchor, call_add, "connect command setup")


def patch_driver(text: str) -> str:
    text = repair_generated_c_strings(text)
    if ("N3DS_AR6014_BOUNDED_RECONNECT" in text or
            "N3DS_AR6014_DIRECT_RECONNECT" in text or
            "N3DS_AR6014_RECONNECT_REMOVED" in text):
        return text
    global_anchor = "unsigned int wlanNodeCaching = 1;\n"
    text = replace_once(text, global_anchor,
                        global_anchor + "bool n3ds_ar6014_reconnect_used;\n",
                        "reconnect state")
    event_anchor = """        ar->arConnected = false;
        return;
    }

    ar6k_cfg80211_disconnect_event(ar, reason, bssid,
"""
    event_add = """        ar->arConnected = false;
        return;
    }

    /* N3DS_AR6014_BOUNDED_RECONNECT: abort Nintendo's parked first search
     * and try WMI_RECONNECT exactly once before reporting failure. */
    if (reason == NO_NETWORK_AVAIL && ar->arWmiReady &&
        ar->arConnectPending && !n3ds_ar6014_reconnect_used &&
        (ar->arReqBssid[0] || ar->arReqBssid[1] || ar->arReqBssid[2] ||
         ar->arReqBssid[3] || ar->arReqBssid[4] || ar->arReqBssid[5])) {
        n3ds_ar6014_reconnect_used = true;
        wmi_disconnect_cmd(ar->arWmi);
        if (wmi_reconnect_cmd(ar->arWmi, ar->arReqBssid,
                              ar->arChannelHint) == 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 connect: bounded reconnect channel=%u bssid=%pM\n",
                 ar->arChannelHint, ar->arReqBssid));
            return;
        }
    }

    ar6k_cfg80211_disconnect_event(ar, reason, bssid,
"""
    return replace_once(text, event_anchor, event_add, "disconnect fallback")


def patch_wmi(text: str) -> str:
    text = repair_generated_c_strings(text)
    if "N3DS_AR6014_SHORT_DISCONNECT" in text:
        return text
    old = """    if (len < sizeof(WMI_DISCONNECT_EVENT)) {
        return A_EINVAL;
    }
"""
    new = """    if (len < sizeof(WMI_DISCONNECT_EVENT)) {
        /* N3DS_AR6014_SHORT_DISCONNECT: Nintendo reports failed connects as
         * seven bytes, with the reason at offset four. */
        u8 shortBssid[ATH_MAC_LEN];
        u8 reason = len > 4 ? datap[4] : NO_NETWORK_AVAIL;
        A_MEMZERO(shortBssid, sizeof(shortBssid));
        A_MEMZERO(wmip->wmi_bssid, sizeof(wmip->wmi_bssid));
        wmip->wmi_is_wmm_enabled = false;
        wmip->wmi_pair_crypto_type = NONE_CRYPT;
        wmip->wmi_grp_crypto_type = NONE_CRYPT;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: short disconnect len=%d reason=%u\n", len, reason));
        A_WMI_DISCONNECT_EVENT(wmip->wmi_devt, reason, shortBssid,
                               0, NULL, 0);
        return 0;
    }
"""
    return replace_once(text, old, new, "short disconnect decoder")


def main() -> None:
    for path in (CFG, DRV, WMI):
        if not path.is_file():
            raise SystemExit(f"missing canonical source: {path}")
    CFG.write_text(patch_cfg(CFG.read_text()), encoding="utf-8")
    DRV.write_text(patch_driver(DRV.read_text()), encoding="utf-8")
    WMI.write_text(patch_wmi(WMI.read_text()), encoding="utf-8")
    print("patch_ar6014_association: Nintendo association compatibility installed")


if __name__ == "__main__":
    main()
