#!/usr/bin/env python3
"""Harden the legacy ath6k AP path used by 3DS Telco.

This patch only uses the AP ABI already present in the legacy driver:
fwmode=2 at BMI boot, WEXT IW_MODE_MASTER/AP_NETWORK, the existing AP
profile commit, AP_GET_STA_LIST, and AP_GET_STAT.  Nintendo's AP-mode firmware
does not emit the station-mode self-connect event; the vendor driver's proven
contract therefore treats a successfully queued AP_CONFIG_COMMIT as readiness.
The proven AP stats payload has traffic counters, not RSSI;
callers must report RSSI as unknown until a target AP RSSI event is evidenced.
"""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")
DRIVER = ROOT / "os/linux/ar6000_drv.c"
IOCTL = ROOT / "os/linux/ioctl.c"
DRIVER_H = ROOT / "os/linux/include/athdrv_linux.h"
FILTER = ROOT / "os/linux/include/wmi_filter_linux.h"
WEXT = ROOT / "os/linux/wireless_ext.c"
MARKER = "N3DS_AR6014_MOBILE_DATA_AP_GUARD"
FW_MARKER = "N3DS_AR6014_FW_MODE_GUARD"
STA_MARKER = "N3DS_AR6014_AP_STA_BOUNDS"
STATS_MARKER = "N3DS_AR6014_AP_STATS_GUARD"
READY_MARKER = "N3DS_AR6014_AP_READY_EVENT"
COMMIT_READY_MARKER = "N3DS_AR6014_AP_COMMIT_ACCEPTED_READY"
IOCTL_MARKER = "N3DS_AR6014_MOBILE_DATA_IOCTL"
WEXT_MARKER = "N3DS_AR6014_PRIVATE_IOCTL_REACHABLE"
DIRECT_MARKER = "N3DS_AR6014_MOBILE_DATA_DIRECT_IOCTL"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_fwmode(text: str) -> str:
    if FW_MARKER in text:
        return text

    old = """    /* set the firmware mode to STA/IBSS/AP */\n    {\n        u32 param;\n\n        if (BMIReadMemory(ar->arHifDevice,\n            HOST_INTEREST_ITEM_ADDRESS(ar, hi_option_flag),"""
    new = """    /* set the firmware mode to STA/IBSS/AP */\n    {\n        u32 param;\n\n        /* N3DS_AR6014_FW_MODE_GUARD: fwmode is consumed only during BMI\n         * boot. Reject undefined modes before touching target RAM, and\n         * replace (rather than OR) the two mode bits so a stale ROM value\n         * cannot silently turn an STA boot into AP or IBSS. */\n        if (fwmode > HI_OPTION_FW_MODE_AP) {\n            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,\n                (\"AR6002: unsupported fwmode=%u (expected 0..2)\\n\", fwmode));\n            return A_ERROR;\n        }\n\n        if (BMIReadMemory(ar->arHifDevice,\n            HOST_INTEREST_ITEM_ADDRESS(ar, hi_option_flag),"""
    text = replace_once(text, old, new, "fwmode validation")
    text = replace_once(
        text,
        "        param |= (fwmode << HI_OPTION_FW_MODE_SHIFT);\n",
        "        param &= ~(HI_OPTION_FW_MODE_MASK << HI_OPTION_FW_MODE_SHIFT);\n"
        "        param |= (fwmode << HI_OPTION_FW_MODE_SHIFT);\n",
        "fwmode mode-bit replacement",
    )
    old_desc = "module_param(fwmode, uint, 0644);\n"
    new_desc = old_desc + (
        "MODULE_PARM_DESC(fwmode, \"boot-time firmware mode: 0=IBSS, "
        "1=STA, 2=AP; runtime writes do not rebind the target\");\n"
    )
    return replace_once(text, old_desc, new_desc, "fwmode description")


def patch_ap_commit(text: str) -> str:
    if MARKER in text:
        if COMMIT_READY_MARKER in text:
            return text
        old_ready = """    /* wmi_ap_profile_commit() is the existing AP_CONFIG_COMMIT command.\n     * Its return value proves only that the host queued the command. Do not\n     * turn that into Connected/carrier state: the existing AP connect event\n     * must prove that target firmware accepted the profile. */\n    status = wmi_ap_profile_commit(ar->arWmi, &p);\n"""
        new_ready = """    /* N3DS_AR6014_AP_COMMIT_ACCEPTED_READY: Nintendo's AP-mode\n     * firmware does not emit the station-mode self-connect event. Preserve\n     * the original vendor contract: successful AP_CONFIG_COMMIT enqueue is\n     * the host readiness boundary; client association remains independently\n     * evidenced through the bounded station list/status path. */\n    status = wmi_ap_profile_commit(ar->arWmi, &p);\n"""
        text = replace_once(text, old_ready, new_ready,
                            "AP commit readiness migration")
        old_success = """    spin_lock_irqsave(&ar->arLock, flags);\n    ar->arConnected  = false;\n    netif_carrier_off(ar->arNetDev);\n    spin_unlock_irqrestore(&ar->arLock, flags);\n    ar->ap_profile_flag = 0;\n    return 0;\n}\n"""
        new_success = """    spin_lock_irqsave(&ar->arLock, flags);\n    ar->arConnected = true;\n    netif_carrier_on(ar->arNetDev);\n    spin_unlock_irqrestore(&ar->arLock, flags);\n    ar->ap_profile_flag = 0;\n    return 0;\n}\n"""
        return replace_once(text, old_success, new_success,
                            "AP commit carrier readiness migration")

    old_decl = """int\nar6000_ap_mode_profile_commit(struct ar6_softc *ar)\n{\n    WMI_CONNECT_CMD p;\n    unsigned long  flags;\n\n    /* No change in AP's profile configuration */\n"""
    new_decl = """int\nar6000_ap_mode_profile_commit(struct ar6_softc *ar)\n{\n    WMI_CONNECT_CMD p;\n    int status;\n    unsigned long flags;\n\n    /* N3DS_AR6014_MOBILE_DATA_AP_GUARD: this is an AP qualification\n     * boundary, not a best-effort mode switch. Inputs are populated through\n     * the existing WEXT/private AP ABI. */\n    if (ar->arNextMode != AP_NETWORK || ar->arWmiReady == false ||\n        ar->arWlanState == WLAN_DISABLED) {\n        A_PRINTF(\"AP commit rejected: target is not AP-ready\\n\");\n        return -EOPNOTSUPP;\n    }\n\n    if (!ar->arSsidLen || ar->arSsidLen > sizeof(ar->arSsid)) {\n        A_PRINTF(\"AP commit rejected: invalid SSID length=%u\\n\",\n                 ar->arSsidLen);\n        return -EINVAL;\n    }\n\n    /* The generic AP ABI documents open and WPA-PSK/WPA2-PSK. Refuse a\n     * mixed/unknown cipher tuple rather than advertising an unusable AP.\n     * WPA2 AES is the Mobile Data protected mode. */\n    if (ar->arAuthMode == NONE_AUTH) {\n        if (ar->arPairwiseCrypto != NONE_CRYPT ||\n            ar->arGroupCrypto != NONE_CRYPT) {\n            A_PRINTF(\"AP commit rejected: open auth with cipher\\n\");\n            return -EOPNOTSUPP;\n        }\n    } else if (ar->arAuthMode == WPA2_PSK_AUTH) {\n        if (ar->arPairwiseCrypto != AES_CRYPT ||\n            ar->arGroupCrypto != AES_CRYPT) {\n            A_PRINTF(\"AP commit rejected: WPA2 requires AES\\n\");\n            return -EOPNOTSUPP;\n        }\n    } else if (ar->arAuthMode != WPA_PSK_AUTH &&\n               ar->arAuthMode != (WPA_PSK_AUTH | WPA2_PSK_AUTH)) {\n        A_PRINTF(\"AP commit rejected: unsupported key management=%u\\n\",\n                 ar->arAuthMode);\n        return -EOPNOTSUPP;\n    }\n\n    /* No change in AP's profile configuration */\n"""
    text = replace_once(text, old_decl, new_decl, "AP commit guard")

    old_send = """    wmi_ap_profile_commit(ar->arWmi, &p);\n    spin_lock_irqsave(&ar->arLock, flags);\n    ar->arConnected  = true;\n    netif_carrier_on(ar->arNetDev);\n    spin_unlock_irqrestore(&ar->arLock, flags);\n    ar->ap_profile_flag = 0;\n    return 0;\n}\n"""
    new_send = """    /* N3DS_AR6014_AP_COMMIT_ACCEPTED_READY: Nintendo's AP-mode\n     * firmware does not emit the station-mode self-connect event. Preserve\n     * the original vendor contract: successful AP_CONFIG_COMMIT enqueue is\n     * the host readiness boundary; client association remains independently\n     * evidenced through the bounded station list/status path. */\n    status = wmi_ap_profile_commit(ar->arWmi, &p);\n    if (status != 0) {\n        A_PRINTF(\"AP commit rejected by host transport: %d; rolling back STA\\n\",\n                 status);\n        if (ar->arWmiReady == true)\n            wmi_disconnect_cmd(ar->arWmi);\n        ar->arNetworkType = INFRA_NETWORK;\n        ar->arNextMode = INFRA_NETWORK;\n        ar->arConnectPending = false;\n        ar->arConnected = false;\n        ar->ap_profile_flag = 0;\n        netif_carrier_off(ar->arNetDev);\n        netif_wake_queue(ar->arNetDev);\n        return -EIO;\n    }\n\n    spin_lock_irqsave(&ar->arLock, flags);\n    ar->arConnected = true;\n    netif_carrier_on(ar->arNetDev);\n    spin_unlock_irqrestore(&ar->arLock, flags);\n    ar->ap_profile_flag = 0;\n    return 0;\n}\n"""
    return replace_once(text, old_send, new_send, "AP commit result gate")


def patch_station_bounds(text: str) -> str:
    if STA_MARKER in text:
        return text

    old_decl = """void\nadd_new_sta(struct ar6_softc *ar, u8 *mac, u16 aid, u8 *wpaie,\n            u8 ielen, u8 keymgmt, u8 ucipher, u8 auth)\n{\n    u8 free_slot=aid-1;\n\n"""
    new_decl = """bool\nadd_new_sta(struct ar6_softc *ar, u8 *mac, u16 aid, u8 *wpaie,\n            u8 ielen, u8 keymgmt, u8 ucipher, u8 auth)\n{\n    u8 free_slot;\n\n    /* N3DS_AR6014_AP_STA_BOUNDS: assoc events originate in target RAM.\n     * Validate AID and IE length before indexing/copying host arrays. */\n    if (!aid || aid > AP_MAX_NUM_STA || ielen > IEEE80211_MAX_IE) {\n        A_PRINTF(\"AP assoc rejected: aid=%u ie_len=%u\\n\", aid, ielen);\n        return false;\n    }\n    free_slot = aid - 1;\n\n"""
    text = replace_once(text, old_decl, new_decl, "AP station bounds")
    old_tail = """    ar->arAPStats.sta[free_slot].aid = aid;\n}\n"""
    new_tail = """    ar->arAPStats.sta[free_slot].aid = aid;\n    return true;\n}\n"""
    text = replace_once(text, old_tail, new_tail, "AP station result")
    old_call = """        add_new_sta(ar, bssid, channel /*aid*/,\n            assocInfo /* WPA IE */, assocRespLen /* IE len */,\n            listenInterval&0xFF /* Keymgmt */, beaconInterval /* cipher */,\n            (listenInterval>>8)&0xFF /* auth alg */);\n\n        /* Send event to application */\n"""
    new_call = """        if (!add_new_sta(ar, bssid, channel /*aid*/,\n            assocInfo /* WPA IE */, assocRespLen /* IE len */,\n            listenInterval&0xFF /* Keymgmt */, beaconInterval /* cipher */,\n            (listenInterval>>8)&0xFF /* auth alg */))\n            return;\n\n        /* Send event to application */\n"""
    return replace_once(text, old_call, new_call, "AP station event gate")


def patch_ap_failure_cleanup(text: str) -> str:
    """Clear AP-only host state if AP_CONFIG_COMMIT was rejected."""
    marker = "N3DS_AR6014_AP_ROLLBACK"
    if marker in text:
        return text
    old = """        ar->arConnectPending = false;
        ar->arConnected = false;
        ar->ap_profile_flag = 0;
        netif_carrier_off(ar->arNetDev);
"""
    new = """        ar->arConnectPending = false;
        ar->arConnected = false;
        ar->ap_profile_flag = 0;
        /* N3DS_AR6014_AP_ROLLBACK: no stale AP station state after a
         * transport-level commit failure. */
        A_MEMZERO(ar->arBssid, sizeof(ar->arBssid));
        ar->arBssChannel = 0;
        A_MEMZERO(ar->sta_list, sizeof(ar->sta_list));
        A_MEMZERO(&ar->arAPStats, sizeof(ar->arAPStats));
        netif_carrier_off(ar->arNetDev);
"""
    return replace_once(text, old, new, "AP commit rollback cleanup")


def patch_ap_stats(text: str) -> str:
    if STATS_MARKER in text:
        return text

    old = """    if (ar->arWmiReady == false) {\n        return -EIO;\n    }\n    if (copy_from_user(&action, (char *)((unsigned int*)rq->ifr_data + 1),\n"""
    new = """    /* N3DS_AR6014_AP_STATS_GUARD: AP_GET_STAT is meaningful only after\n     * WEXT has selected AP_NETWORK. The proven WMI_AP_MODE_STAT payload\n     * contains per-station traffic counters, not RSSI; callers must display\n     * signal as unknown until a target AP RSSI event is evidenced. */\n    if (ar->arNetworkType != AP_NETWORK || ar->arNextMode != AP_NETWORK) {\n        return -EOPNOTSUPP;\n    }\n    if (ar->arWmiReady == false) {\n        return -EIO;\n    }\n    if (copy_from_user(&action, (char *)((unsigned int*)rq->ifr_data + 1),\n"""
    return replace_once(text, old, new, "AP stats mode guard")


def patch_ap_ready_event(text: str) -> str:
    if READY_MARKER in text:
        return text
    old = """skip_key:
            ar->arConnected  = true;
            return;
        }
"""
    new = """skip_key:
            /* N3DS_AR6014_AP_READY_EVENT: this self-connect event is the
             * target's AP acceptance signal. Only now may the host publish
             * Connected/carrier state after the profile commit. */
            spin_lock_irqsave(&ar->arLock, flags);
            ar->arConnected = true;
            netif_carrier_on(ar->arNetDev);
            spin_unlock_irqrestore(&ar->arLock, flags);
            return;
        }
"""
    return replace_once(text, old, new, "AP ready event gate")


def patch_mobile_data_ioctl_header(text: str) -> str:
    if "AR6000_IOCTL_N3DS_MOBILE_DATA" not in text:
        if "#define AR6000_XIOCTL_N3DS_MOBILE_DATA_AP             162\n" in text:
            anchor = "#define AR6000_XIOCTL_N3DS_MOBILE_DATA_AP             162\n"
            text = replace_once(
                text,
                anchor,
                anchor +
                "#define AR6000_IOCTL_N3DS_MOBILE_DATA "
                "(SIOCDEVPRIVATE + 15)\n",
                "mobile-data direct ioctl number",
            )
        else:
            anchor = "#define AR6000_XIOCTL_WMI_SET_EXCESS_TX_RETRY_THRES     161\n"
            text = replace_once(
                text,
                anchor,
                anchor +
                "#define AR6000_IOCTL_N3DS_MOBILE_DATA "
                "(SIOCDEVPRIVATE + 15)\n",
                "mobile-data direct ioctl number",
            )
    if "N3DS_MOBILE_DATA_AP_MIN_CHANNEL" in text:
        return text
    if IOCTL_MARKER in text:
        old = "#define N3DS_MOBILE_DATA_AP_STOP                      3\n"
        new = old + (
            "#define N3DS_MOBILE_DATA_AP_MIN_CHANNEL               1\n"
            "#define N3DS_MOBILE_DATA_AP_MAX_CHANNEL               14\n"
            "#define N3DS_MOBILE_DATA_AP_MAX_SSID                  32\n"
        )
        return replace_once(text, old, new, "mobile-data ioctl header upgrade")
    old = "#define AR6000_XIOCTL_WMI_SET_EXCESS_TX_RETRY_THRES     161\n"
    new = old + r"""
/*
 * N3DS_AR6014_MOBILE_DATA_IOCTL: fixed-width host control for the
 * already-supported WEXT AP profile. No passphrase is carried here:
 * WPA2/AES credentials remain in the existing WEXT key path.
 */
#define AR6000_XIOCTL_N3DS_MOBILE_DATA_AP             162
#define N3DS_MOBILE_DATA_AP_VERSION                   1
#define N3DS_MOBILE_DATA_AP_START_OPEN                1
#define N3DS_MOBILE_DATA_AP_START_WPA2                2
#define N3DS_MOBILE_DATA_AP_STOP                      3
#define N3DS_MOBILE_DATA_AP_MIN_CHANNEL               1
#define N3DS_MOBILE_DATA_AP_MAX_CHANNEL               14
#define N3DS_MOBILE_DATA_AP_MAX_SSID                  32
typedef struct {
    u32 version;
    u32 action;
    u16 channel;
    u8  ssid_len;
    u8  reserved;
    u8  ssid[32];
} N3DS_MOBILE_DATA_AP_CONTROL;
"""
    return replace_once(text, old, new, "mobile-data ioctl header")


def patch_mobile_data_filter(text: str) -> str:
    if "(INFRA_NETWORK | AP_NETWORK)," in text and \
       "AR6000_XIOCTL_N3DS_MOBILE_DATA_AP" in text:
        return text
    if "AR6000_XIOCTL_N3DS_MOBILE_DATA_AP" in text:
        old = "(AP_NETWORK),                                   /* AR6000_XIOCTL_N3DS_MOBILE_DATA_AP             162  */\n"
        new = "(INFRA_NETWORK | AP_NETWORK),                   /* AR6000_XIOCTL_N3DS_MOBILE_DATA_AP             162  */\n"
        return replace_once(text, old, new, "mobile-data ioctl filter upgrade")
    old = r"""(INFRA_NETWORK | ADHOC_NETWORK),                /* AR6000_XIOCTL_WMI_SET_EXCESS_TX_RETRY_THRES     161  */
};"""
    new = r"""(INFRA_NETWORK | ADHOC_NETWORK),                /* AR6000_XIOCTL_WMI_SET_EXCESS_TX_RETRY_THRES     161  */
(INFRA_NETWORK | AP_NETWORK),                   /* AR6000_XIOCTL_N3DS_MOBILE_DATA_AP             162  */
};"""
    return replace_once(text, old, new, "mobile-data ioctl filter")


def patch_mobile_data_ioctl(text: str) -> str:
    if IOCTL_MARKER in text:
        return text
    old = r"""        case AR6000_XIOCTL_AP_COMMIT_CONFIG:
        {
            ret = ar6000_ap_mode_profile_commit(ar);
            break;
        }
"""
    new = old + r"""        case AR6000_XIOCTL_N3DS_MOBILE_DATA_AP:
        {
            N3DS_MOBILE_DATA_AP_CONTROL control;

            /* N3DS_AR6014_MOBILE_DATA_IOCTL: fixed-width control only.
             * WEXT mode selection and WPA2 key setup remain the documented
             * legacy ABI; this command only commits/stops that profile. */
            if (copy_from_user(&control, userdata, sizeof(control))) {
                ret = -EFAULT;
                break;
            }
            if (control.version != N3DS_MOBILE_DATA_AP_VERSION) {
                ret = -EINVAL;
                break;
            }
            if (control.reserved != 0) {
                ret = -EINVAL;
                break;
            }
            if (control.action == N3DS_MOBILE_DATA_AP_STOP) {
                if (ar->arWmiReady == true)
                    if (ar->arConnected || ar->arConnectPending)
                        wmi_disconnect_cmd(ar->arWmi);
                ar->arNetworkType = INFRA_NETWORK;
                ar->arNextMode = INFRA_NETWORK;
                ar->arConnectPending = false;
                ar->arConnected = false;
                ar->ap_profile_flag = 0;
                ar->arSsidLen = 0;
                ar->arChannelHint = 0;
                ar->arBssChannel = 0;
                A_MEMZERO(ar->arSsid, sizeof(ar->arSsid));
                A_MEMZERO(ar->arBssid, sizeof(ar->arBssid));
                A_MEMZERO(ar->sta_list, sizeof(ar->sta_list));
                A_MEMZERO(&ar->arAPStats, sizeof(ar->arAPStats));
                ar->arDot11AuthMode = OPEN_AUTH;
                ar->arAuthMode = NONE_AUTH;
                ar->arPairwiseCrypto = NONE_CRYPT;
                ar->arPairwiseCryptoLen = 0;
                ar->arGroupCrypto = NONE_CRYPT;
                ar->arGroupCryptoLen = 0;
                netif_carrier_off(ar->arNetDev);
                netif_wake_queue(ar->arNetDev);
                break;
            }
            if (control.action != N3DS_MOBILE_DATA_AP_START_OPEN &&
                control.action != N3DS_MOBILE_DATA_AP_START_WPA2) {
                ret = -EINVAL;
                break;
            }
            if (control.channel < N3DS_MOBILE_DATA_AP_MIN_CHANNEL ||
                control.channel > N3DS_MOBILE_DATA_AP_MAX_CHANNEL) {
                ret = -EINVAL;
                break;
            }
            if (!control.ssid_len ||
                control.ssid_len > N3DS_MOBILE_DATA_AP_MAX_SSID) {
                ret = -EINVAL;
                break;
            }
            if (control.action == N3DS_MOBILE_DATA_AP_START_WPA2 &&
                (ar->arAuthMode != WPA2_PSK_AUTH ||
                 ar->arPairwiseCrypto != AES_CRYPT ||
                 ar->arGroupCrypto != AES_CRYPT ||
                 ar->ap_mode_bkey.ik_keylen == 0)) {
                ret = -EOPNOTSUPP;
                break;
            }
            /* Stop a station profile before queueing the AP profile. The
             * legacy WEXT path performs the same host-side queue cleanup
             * after switching modes; doing it here keeps a stale station
             * carrier/packet queue from surviving a Mobile Data start. */
            if (ar->arNetworkType != AP_NETWORK &&
                (ar->arConnected || ar->arConnectPending)) {
                if (ar->arWmiReady == true)
                    wmi_disconnect_cmd(ar->arWmi);
                ar->arConnectPending = false;
                ar->arConnected = false;
                netif_stop_queue(ar->arNetDev);
                ar6000_TxDataCleanup(ar);
                netif_wake_queue(ar->arNetDev);
                A_MEMZERO(ar->arBssid, sizeof(ar->arBssid));
                ar->arBssChannel = 0;
            }
            memset(ar->arSsid, 0, sizeof(ar->arSsid));
            memcpy(ar->arSsid, control.ssid, control.ssid_len);
            ar->arSsidLen = control.ssid_len;
            if (control.channel)
                ar->arChannelHint = control.channel;
            if (control.action == N3DS_MOBILE_DATA_AP_START_OPEN) {
                ar->arDot11AuthMode = OPEN_AUTH;
                ar->arAuthMode = NONE_AUTH;
                ar->arPairwiseCrypto = NONE_CRYPT;
                ar->arPairwiseCryptoLen = 0;
                ar->arGroupCrypto = NONE_CRYPT;
                ar->arGroupCryptoLen = 0;
            }
            ar->arNextMode = AP_NETWORK;
            ar->ap_profile_flag = 1;
            ret = ar6000_ap_mode_profile_commit(ar);
            break;
        }
"""
    return replace_once(text, old, new, "mobile-data ioctl implementation")


def patch_mobile_data_ioctl_upgrade(text: str) -> str:
    """Upgrade the first shipped AP ioctl revision in-place."""
    if "N3DS_AR6014_MOBILE_DATA_IOCTL_UPGRADE" in text or \
       ("if (control.reserved != 0)" in text and
        "ar6000_TxDataCleanup(ar)" in text):
        return text
    if IOCTL_MARKER not in text:
        return text

    old = "            if (control.version != N3DS_MOBILE_DATA_AP_VERSION) {\n                ret = -EINVAL;\n                break;\n            }\n            if (control.action == N3DS_MOBILE_DATA_AP_STOP) {\n                if (ar->arWmiReady == true)\n                    wmi_disconnect_cmd(ar->arWmi);\n"
    new = "            if (control.version != N3DS_MOBILE_DATA_AP_VERSION) {\n                ret = -EINVAL;\n                break;\n            }\n            if (control.reserved != 0) {\n                ret = -EINVAL;\n                break;\n            }\n            if (control.action == N3DS_MOBILE_DATA_AP_STOP) {\n                if (ar->arWmiReady == true)\n                    if (ar->arConnected || ar->arConnectPending)\n                        wmi_disconnect_cmd(ar->arWmi);\n"
    text = replace_once(text, old, new, "mobile-data ioctl validation upgrade")

    old = "                ar->arConnected = false;\n                ar->ap_profile_flag = 0;\n                netif_carrier_off(ar->arNetDev);\n"
    new = "                ar->arConnected = false;\n                ar->ap_profile_flag = 0;\n                ar->arSsidLen = 0;\n                ar->arChannelHint = 0;\n                ar->arBssChannel = 0;\n                A_MEMZERO(ar->arSsid, sizeof(ar->arSsid));\n                A_MEMZERO(ar->arBssid, sizeof(ar->arBssid));\n                A_MEMZERO(ar->sta_list, sizeof(ar->sta_list));\n                A_MEMZERO(&ar->arAPStats, sizeof(ar->arAPStats));\n                ar->arDot11AuthMode = OPEN_AUTH;\n                ar->arAuthMode = NONE_AUTH;\n                ar->arPairwiseCrypto = NONE_CRYPT;\n                ar->arPairwiseCryptoLen = 0;\n                ar->arGroupCrypto = NONE_CRYPT;\n                ar->arGroupCryptoLen = 0;\n                netif_carrier_off(ar->arNetDev);\n"
    text = replace_once(text, old, new, "mobile-data stop cleanup upgrade")

    old = "            memset(ar->arSsid, 0, sizeof(ar->arSsid));\n            if (!control.ssid_len || control.ssid_len > sizeof(ar->arSsid)) {\n"
    new = "            if (control.channel < N3DS_MOBILE_DATA_AP_MIN_CHANNEL ||\n                control.channel > N3DS_MOBILE_DATA_AP_MAX_CHANNEL) {\n                ret = -EINVAL;\n                break;\n            }\n            if (!control.ssid_len ||\n                control.ssid_len > N3DS_MOBILE_DATA_AP_MAX_SSID) {\n"
    text = replace_once(text, old, new, "mobile-data input bounds upgrade")

    old = "                (ar->arAuthMode != WPA2_PSK_AUTH ||\n                 ar->arPairwiseCrypto != AES_CRYPT ||\n                 ar->arGroupCrypto != AES_CRYPT)) {\n"
    new = "                (ar->arAuthMode != WPA2_PSK_AUTH ||\n                 ar->arPairwiseCrypto != AES_CRYPT ||\n                 ar->arGroupCrypto != AES_CRYPT ||\n                 ar->ap_mode_bkey.ik_keylen == 0)) {\n"
    text = replace_once(text, old, new, "mobile-data WPA2 key gate upgrade")

    old = "                ret = -EOPNOTSUPP;\n                break;\n            }\n            memset(ar->arSsid, 0, sizeof(ar->arSsid));\n"
    new = "                ret = -EOPNOTSUPP;\n                break;\n            }\n            /* N3DS_AR6014_MOBILE_DATA_IOCTL_UPGRADE: stop station TX before\n             * queueing AP_CONFIG_COMMIT, then leave the queue recoverable. */\n            if (ar->arNetworkType != AP_NETWORK &&\n                (ar->arConnected || ar->arConnectPending)) {\n                if (ar->arWmiReady == true)\n                    wmi_disconnect_cmd(ar->arWmi);\n                ar->arConnectPending = false;\n                ar->arConnected = false;\n                netif_stop_queue(ar->arNetDev);\n                ar6000_TxDataCleanup(ar);\n                netif_wake_queue(ar->arNetDev);\n                A_MEMZERO(ar->arBssid, sizeof(ar->arBssid));\n                ar->arBssChannel = 0;\n            }\n            memset(ar->arSsid, 0, sizeof(ar->arSsid));\n"
    return replace_once(text, old, new, "mobile-data station cleanup upgrade")


def patch_private_ioctl_reachability(text: str) -> str:
    """Make the existing extended ioctl switch reachable through WEXT."""
    if WEXT_MARKER in text:
        for required in ("ar6000_ioctl_extended", ".private          = (iw_handler *)ath_private_handlers",
                         ".num_private      = ARRAY_SIZE(ath_private_handlers)"):
            if required not in text:
                raise RuntimeError("marked private WEXT route lacks " + required)
        return text

    anchor = """struct iw_handler_def ath_iw_handler_def = {
    .standard         = (iw_handler *)ath_handlers,
    .num_standard     = ARRAY_SIZE(ath_handlers),
    .private          = NULL,
    .num_private      = 0,
};
"""
    replacement = r"""/* N3DS_AR6014_PRIVATE_IOCTL_REACHABLE: command 162 lives behind the
 * driver's extended private ioctl.  The modern WEXT core rejects private
 * commands before ar6000_ioctl() unless the slot is explicitly registered. */
extern int ar6000_ioctl(struct net_device *dev, struct ifreq *rq, int cmd);

static int ar6000_ioctl_extended(struct net_device *dev,
                                 struct iw_request_info *info,
                                 union iwreq_data *wrqu, char *extra)
{
    struct ifreq request;

    memset(&request, 0, sizeof(request));
    request.ifr_data = wrqu->data.pointer;
    return ar6000_ioctl(dev, &request, info->cmd);
}

static const iw_handler ath_private_handlers[] = {
    [AR6000_IOCTL_EXTENDED - SIOCIWFIRSTPRIV] =
        (iw_handler) ar6000_ioctl_extended,
};

struct iw_handler_def ath_iw_handler_def = {
    .standard         = (iw_handler *)ath_handlers,
    .num_standard     = ARRAY_SIZE(ath_handlers),
    .private          = (iw_handler *)ath_private_handlers,
    .num_private      = ARRAY_SIZE(ath_private_handlers),
};
"""
    return replace_once(text, anchor, replacement,
                        "mobile-data private WEXT reachability")


def patch_direct_ioctl_reachability(driver: str, ioctl: str) -> tuple[str, str]:
    """Route the fixed payload through ndo_do_ioctl, bypassing WEXT rejection."""
    if DIRECT_MARKER not in driver:
        anchor = "static struct net_device_ops ar6000_netdev_ops = {\n"
        replacement = (
            "/* N3DS_AR6014_MOBILE_DATA_DIRECT_IOCTL: WEXT rejects the "
            "vendor's\n"
            " * highest private slot before its registered handler runs.  "
            "Expose the same\n"
            " * fixed-width extended payload through a collision-checked "
            "netdev command. */\n"
            "extern int ar6000_ioctl(struct net_device *dev, struct ifreq "
            "*rq, int cmd);\n\n"
            + anchor
        )
        driver = replace_once(driver, anchor, replacement,
                              "mobile-data direct ioctl declaration")
        driver = replace_once(
            driver,
            "    .ndo_set_rx_mode        = ar6000_set_multicast_list,\n",
            "    .ndo_set_rx_mode        = ar6000_set_multicast_list,\n"
            "    .ndo_do_ioctl           = ar6000_ioctl,\n",
            "mobile-data direct ioctl callback",
        )
    else:
        for required in (".ndo_do_ioctl           = ar6000_ioctl,",
                         "extern int ar6000_ioctl"):
            if required not in driver:
                raise RuntimeError("marked direct ioctl route lacks " + required)

    old = "    if (cmd == AR6000_IOCTL_EXTENDED) {\n"
    new = (
        "    /* N3DS_AR6014_MOBILE_DATA_DIRECT_IOCTL: both commands carry "
        "the\n"
        "     * vendor xioctl number in the first payload word. */\n"
        "    if (cmd == AR6000_IOCTL_EXTENDED ||\n"
        "        cmd == AR6000_IOCTL_N3DS_MOBILE_DATA) {\n"
    )
    if DIRECT_MARKER not in ioctl:
        ioctl = replace_once(ioctl, old, new,
                             "mobile-data direct ioctl dispatch")
    elif "cmd == AR6000_IOCTL_N3DS_MOBILE_DATA" not in ioctl:
        raise RuntimeError("marked direct ioctl dispatch lacks command")
    return driver, ioctl


def main() -> None:
    for path in (DRIVER, IOCTL, DRIVER_H, FILTER, WEXT):
        if not path.is_file():
            raise SystemExit(f"missing canonical AP source: {path}")
    driver = DRIVER.read_text(encoding="utf-8")
    ioctl = IOCTL.read_text(encoding="utf-8")
    driver_h = DRIVER_H.read_text(encoding="utf-8")
    filter_source = FILTER.read_text(encoding="utf-8")
    wext = WEXT.read_text(encoding="utf-8")
    driver = patch_fwmode(driver)
    driver = patch_ap_commit(driver)
    driver = patch_ap_failure_cleanup(driver)
    driver = patch_station_bounds(driver)
    driver = patch_ap_ready_event(driver)
    ioctl = patch_ap_stats(ioctl)
    driver_h = patch_mobile_data_ioctl_header(driver_h)
    filter_source = patch_mobile_data_filter(filter_source)
    ioctl = patch_mobile_data_ioctl(ioctl)
    ioctl = patch_mobile_data_ioctl_upgrade(ioctl)
    wext = patch_private_ioctl_reachability(wext)
    driver, ioctl = patch_direct_ioctl_reachability(driver, ioctl)
    DRIVER.write_text(driver, encoding="utf-8")
    IOCTL.write_text(ioctl, encoding="utf-8")
    DRIVER_H.write_text(driver_h, encoding="utf-8")
    FILTER.write_text(filter_source, encoding="utf-8")
    WEXT.write_text(wext, encoding="utf-8")
    print("patch_ar6014_mobiledata_ap: fail-closed AP commit/station guards installed")


if __name__ == "__main__":
    main()
