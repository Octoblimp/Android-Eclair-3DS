#!/usr/bin/env python3
"""Return failed connects to cfg80211 promptly and export RSSI as dBm."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import re


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")
DRV = ROOT / "os/linux/ar6000_drv.c"
CFG = ROOT / "os/linux/cfg80211.c"
WMI = ROOT / "wmi/wmi.c"
MARKER = "N3DS_AR6014_DIRECT_RECONNECT"
REMOVED_MARKER = "N3DS_AR6014_RECONNECT_REMOVED"
RSSI_MARKER = "N3DS_AR6014_CFG80211_DBM_SIGNAL"
HANDOFF_MARKER = "N3DS_AR6014_NO_NETWORK_HANDOFF"
EVENT_MARKER = "N3DS_AR6014_NWM_DISCONNECT_BOUNDS"


OLD_RECONNECT = '''    /* N3DS_AR6014_BOUNDED_RECONNECT: abort Nintendo's parked first search
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
                ("AR6002 connect: bounded reconnect channel=%u bssid=%pM\\n",
                 ar->arChannelHint, ar->arReqBssid));
            return;
        }
    }
'''


NEW_RECONNECT = '''    /* N3DS_AR6014_DIRECT_RECONNECT: the physical association capture proves
     * DISCONNECT followed by RECONNECT produces reasons 3,10,3: DISCONNECT
     * clears Nintendo's saved target profile, so RECONNECT fails with
     * INVALID_PROFILE.  Preserve the profile created by WMI_CONNECT and issue
     * one direct BSSID/channel reconnect.  Unlike this firmware's CONNECT
     * parser, WMI_RECONNECT retains those two fields explicitly. */
    if (reason == NO_NETWORK_AVAIL && ar->arWmiReady &&
        ar->arConnectPending && !n3ds_ar6014_reconnect_used &&
        (ar->arReqBssid[0] || ar->arReqBssid[1] || ar->arReqBssid[2] ||
         ar->arReqBssid[3] || ar->arReqBssid[4] || ar->arReqBssid[5])) {
        n3ds_ar6014_reconnect_used = true;
        if (wmi_reconnect_cmd(ar->arWmi, ar->arReqBssid,
                              ar->arChannelHint) == 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 connect: direct reconnect channel=%u bssid=%pM profile=preserved\\n",
                 ar->arChannelHint, ar->arReqBssid));
            return;
        }
    }
'''

REMOVED_RECONNECT = '''    /* N3DS_AR6014_RECONNECT_REMOVED: kernel #178 proves that retrying a
     * failed WMI_CONNECT inside the target extends stale association state,
     * delays cfg80211's failure result, and can leave the next scan busy.
     * Hand Nintendo's NO_NETWORK_AVAIL event directly to cfg80211 below. */
'''

CFG_NO_NETWORK_OLD = '''        if(NO_NETWORK_AVAIL == reason) {
            /* connect cmd failed */
            wmi_disconnect_cmd(ar->arWmi);
        }'''

CFG_NO_NETWORK_NEW = '''        if(NO_NETWORK_AVAIL == reason) {
            /* N3DS_AR6014_NO_NETWORK_HANDOFF: Nintendo reports an exhausted
             * target search after about 4.5 seconds. Stop its parked connect
             * state and complete the pending cfg80211 request immediately;
             * otherwise nl80211 stays silent and supplicant waits for its
             * unrelated ten-second local authentication timer. */
            wmi_disconnect_cmd(ar->arWmi);
            ar->arConnectPending = false;
            if (ar->smeState == SME_CONNECTING) {
                cfg80211_connect_result(ar->arNetDev, bssid,
                                        NULL, 0, NULL, 0,
                                        WLAN_STATUS_UNSPECIFIED_FAILURE,
                                        GFP_KERNEL);
            } else {
                cfg80211_disconnected(ar->arNetDev, reason, NULL, 0,
                                      false, GFP_KERNEL);
            }
            ar->smeState = SME_DISCONNECTED;
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 connect: NWM failure handed to cfg80211 reason=%u "
                 "status=%u bssid=%pM\\n",
                 reason, protocolReasonStatus, bssid));
        }'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_driver(text: str) -> str:
    if REMOVED_MARKER in text:
        return text
    if MARKER in text:
        text = replace_once(
            text, NEW_RECONNECT, REMOVED_RECONNECT, "direct reconnect removal"
        )
    elif "N3DS_AR6014_BOUNDED_RECONNECT" in text:
        if OLD_RECONNECT in text:
            text = replace_once(
                text, OLD_RECONNECT, REMOVED_RECONNECT, "bounded reconnect removal"
            )
        else:
            text, count = re.subn(
                r"    /\* N3DS_AR6014_BOUNDED_RECONNECT:.*?"
                r"(?=    ar6k_cfg80211_disconnect_event\()",
                REMOVED_RECONNECT,
                text,
                count=1,
                flags=re.S,
            )
            if count != 1:
                raise RuntimeError(
                    f"bounded reconnect removal: expected one marked block, found {count}"
                )
    else:
        raise RuntimeError("reconnect removal: no known source anchor")
    return text.replace("bool n3ds_ar6014_reconnect_used;\n", "", 1)


def patch_cfg(text: str) -> str:
    text = text.replace("extern bool n3ds_ar6014_reconnect_used;\n", "", 1)
    text = text.replace("    n3ds_ar6014_reconnect_used = false;\n", "", 1)
    if RSSI_MARKER not in text:
        old = "    signal  = ni->ni_snr * 100;\n"
        new = '''    /* N3DS_AR6014_CFG80211_DBM_SIGNAL: cfg80211 expects mBm here.
     * ni_snr is an unsigned margin (45 in the physical capture), not dBm;
     * exporting it produced the impossible +45 dBm / 134 dB SNR result.
     * The harvester stores its conservative estimate in signed ni_rssi. */
    signal = (s32)ni->ni_rssi * 100;
'''
        text = replace_once(text, old, new, "cfg80211 signal source")
    if HANDOFF_MARKER not in text:
        text = replace_once(
            text, CFG_NO_NETWORK_OLD, CFG_NO_NETWORK_NEW,
            "NO_NETWORK cfg80211 handoff"
        )
    return text


def patch_wmi(text: str) -> str:
    if "reason=%u raw=%*ph" not in text:
        old = '''        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: short disconnect len=%d reason=%u\\n", len, reason));
'''
        new = '''        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: short disconnect len=%d reason=%u raw=%*ph\\n",
             len, reason, len, datap));
'''
        text = replace_once(text, old, new, "short event evidence")
    if EVENT_MARKER in text:
        return text
    old = '''    ev = (WMI_DISCONNECT_EVENT *)datap;

    A_MEMZERO(wmip->wmi_bssid, sizeof(wmip->wmi_bssid));
'''
    new = '''    ev = (WMI_DISCONNECT_EVENT *)datap;

    /* N3DS_AR6014_NWM_DISCONNECT_BOUNDS: NWM 0x001353ec passes the packed
     * {status:u16,bssid[6],reason:u8,assoc_len:u8,assoc_info[]} payload.
     * Validate the variable tail before any callback can walk it, and retain
     * one credential-free diagnostic for the next physical acceptance run. */
    if (ev->assocRespLen > len - 10) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: invalid NWM disconnect len=%d assoc=%u\\n",
             len, ev->assocRespLen));
        return A_EINVAL;
    }
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM disconnect len=%d reason=%u status=%u "
         "bssid=%pM assoc=%u\\n", len, ev->disconnectReason,
         ev->protocolReasonStatus, ev->bssid, ev->assocRespLen));

    A_MEMZERO(wmip->wmi_bssid, sizeof(wmip->wmi_bssid));
'''
    return replace_once(text, old, new, "NWM disconnect validation")


def main() -> None:
    for path in (DRV, CFG, WMI):
        if not path.is_file():
            raise SystemExit(f"missing canonical source: {path}")
    DRV.write_text(patch_driver(DRV.read_text()))
    CFG.write_text(patch_cfg(CFG.read_text()))
    WMI.write_text(patch_wmi(WMI.read_text()))
    print("patch_ar6014_direct_reconnect: failed-connect handoff and dBm RSSI installed")


if __name__ == "__main__":
    main()
