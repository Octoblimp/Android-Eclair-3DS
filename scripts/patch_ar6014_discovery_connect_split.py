#!/usr/bin/env python3
"""Separate host wildcard discovery from NWM's selected-profile scan state."""
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path


CFG = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
    "ath6k_legacy/os/linux/cfg80211.c"
)
MARKER = "N3DS_AR6014_DISCOVERY_CONNECT_SPLIT"
OLD_PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_connection_scan.py")

TOP_ANCHOR = '''extern int reconnect_flag;
'''

TOP_NEW = r'''extern int reconnect_flag;

/* N3DS_AR6014_NWM_CONNECTION_SCAN:
 * N3DS_AR6014_DISCOVERY_CONNECT_SPLIT: #245 proved that applying NWM's
 * selected-profile scan verbatim to a cfg80211 discovery request can finish
 * in about 100 ms with zero BSS records.  Preserve Nintendo's slot-zero,
 * command-8, command-17, and filter order only at connect submission.
 * N3DS_AR6014_CONNECT_SCAN_DWELL_REGRESSION: the #245->#247 split
 * accidentally replaced the disassembly-verified 20 ms home/active/passive
 * dwell recovered at 0x0012ad70 (documented in HANDOFF.md's #245 entry,
 * command 8 with periods 0xffff and dwell 20 ms) with an invented 105 ms
 * value, on the mistaken theory that it needed to exceed a beacon interval.
 * That caused every real-hardware WPA2 connect to end in NWM disconnect
 * reason 1 (NO_NETWORK_AVAIL) about 4.5s later, even though the identical
 * BSS was already visible to host discovery. Restore the real firmware's
 * 20 ms dwell. */
#define N3DS_NWM_CONNECT_SCAN_DWELL_MS 20
#define N3DS_NWM_CONNECT_SCAN_FLAGS \
    (CONNECT_SCAN_CTRL_FLAGS | ACTIVE_SCAN_CTRL_FLAGS)
'''

DISCOVERY_HELPER_NEW = r'''#define N3DS_MAX_SCAN_PROBED_SSIDS 5

/* Host discovery owns slots 1..5.  Slot zero is reserved for the profile
 * handed to WMI_CONNECT.  An empty cfg80211 SSID is not "nothing": it is the
 * wildcard probe represented by NWM/WMI flag 2 (ANY_SSID_FLAG). */
static int
n3ds_ar6014_program_discovery_ssids(struct ar6_softc *ar,
                                    struct cfg80211_scan_request *request,
                                    bool *wildcard_scan)
{
    u8 i;
    u8 count = request->n_ssids;

    *wildcard_scan = false;
    if (count > N3DS_MAX_SCAN_PROBED_SSIDS)
        count = N3DS_MAX_SCAN_PROBED_SSIDS;

    for (i = 0; i < count; i++) {
        u8 flag = request->ssids[i].ssid_len ?
                  SPECIFIC_SSID_FLAG : ANY_SSID_FLAG;

        if (flag == ANY_SSID_FLAG)
            *wildcard_scan = true;
        if (wmi_probedSsid_cmd(ar->arWmi, i + 1, flag,
                               request->ssids[i].ssid_len,
                               request->ssids[i].ssid) != 0)
            return -EIO;
    }
    return 0;
}

static void
n3ds_ar6014_clear_discovery_ssids(struct ar6_softc *ar,
                                  struct cfg80211_scan_request *request)
{
    u8 slot;
    u8 count = request->n_ssids;

    if (count > N3DS_MAX_SCAN_PROBED_SSIDS)
        count = N3DS_MAX_SCAN_PROBED_SSIDS;
    for (slot = 1; slot <= count; slot++)
        wmi_probedSsid_cmd(ar->arWmi, slot, DISABLE_SSID_FLAG, 0, NULL);
}

static int
ar6k_cfg80211_scan(struct wiphy *wiphy,
'''

SCAN_VARS_OLD = '''    bool trace_scan = scan_trace_count < 16;
    u16 channel_list[WMI_MAX_CHANNELS];
'''

SCAN_VARS_NEW = '''    bool trace_scan = scan_trace_count < 16;
    bool wildcard_scan = false;
    u16 channel_list[WMI_MAX_CHANNELS];
'''

DISCOVERY_PREP_NEW = r'''    /* N3DS_CFG80211_SCAN_REQUEST_ORDER: publish ownership before the
     * target can return an immediate completion. Every setup error below
     * releases the request and every slot armed for this discovery. */
    if (cmpxchg(&ar->scan_request, NULL, request) != NULL)
        return -EBUSY;

    if (n3ds_ar6014_program_discovery_ssids(ar, request,
                                            &wildcard_scan) != 0)
        goto setup_fail;
    if (wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE,
                                  num_channels, channel_list) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: discovery channel table failed channels=%d\n",
             num_channels));
        goto setup_fail;
    }
    if (!ar->arUserBssFilter &&
        wmi_bssfilter_cmd(ar->arWmi,
                         (ar->arConnected ? ALL_BUT_BSS_FILTER : ALL_BSS_FILTER),
                         0) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("%s: Couldn't set bss filtering\n", __func__));
        goto setup_fail;
    }
    if (trace_scan)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: discovery explicit channels=%d wildcard=%u\n",
             num_channels, wildcard_scan));

'''

DISCOVERY_START_NEW = r'''    /* Host discovery needs command 7's explicit channel list.  #245's
     * start_list=0 adaptation was valid only for NWM's selected-profile
     * connection scan and completed with zero BSS records on hardware. */
    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \
                         0, 0, num_channels, channel_list) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("%s: wmi_startscan_cmd failed\n", __func__));
        goto setup_fail;
    }
    if (trace_scan)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: START_SCAN submitted explicit_channels=%d\n",
             num_channels));
    return 0;

setup_fail:
    n3ds_ar6014_clear_discovery_ssids(ar, request);
    cmpxchg(&ar->scan_request, request, NULL);
    return -EIO;
'''

DISCOVERY_COMPLETE_NEW = '''    /* Slots 1..5 are request-local. Slot zero belongs to connect. */
    n3ds_ar6014_clear_discovery_ssids(ar, request);
'''

CONNECT_CHANNEL_OLD = '''    if (ar->arChannelHint) {
        status = n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
        if (status != 0) {
            up(&ar->arSem);
            return -EIO;
        }
    }

'''

CONNECT_FILTER_OLD = '''    if (!ar->arUserBssFilter) {
        if (wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("%s: Couldn't set bss filtering\n", __func__));
            up(&ar->arSem);
            return -EIO;
        }
    }

'''

CONNECT_FILTER_START = '''    if (!ar->arUserBssFilter) {
        if (wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0) != 0) {
'''

CONNECT_FILTER_END = '''    ar->arNetworkType = ar->arNextMode;
'''

CONNECT_SLOT_OLD = '''    reconnect_flag = 0;
    /* Register the directed SSID and tell the target that cfg80211 already
     * selected the BSS. */
    wmi_probedSsid_cmd(ar->arWmi, 0, SPECIFIC_SSID_FLAG,
                       ar->arSsidLen, ar->arSsid);
'''

CONNECT_SETUP_NEW = r'''    reconnect_flag = 0;
    /* NWM 0x0012ad70 setup adapted to cfg80211's preselected BSS path:
     * selected slot 0 -> command 8 -> command 17 -> command 9 -> CONNECT.
     * CONNECT_SCAN makes WMI_CONNECT perform its target-side search; command
     * 7 remains exclusively the host discovery operation above. */
    status = wmi_probedSsid_cmd(ar->arWmi, 0, SPECIFIC_SSID_FLAG,
                                ar->arSsidLen, ar->arSsid);
    if (status != 0) {
        up(&ar->arSem);
        return -EIO;
    }
    status = wmi_scanparams_cmd(ar->arWmi, 0xffff, 0xffff, 0xffff,
                                N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                0, N3DS_NWM_CONNECT_SCAN_FLAGS, 0, 0);
    if (status != 0) {
        wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);
        up(&ar->arSem);
        return -EIO;
    }
    if (ar->arChannelHint) {
        status = n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
        if (status != 0) {
            wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);
            up(&ar->arSem);
            return -EIO;
        }
    }
    if (!ar->arUserBssFilter &&
        wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0) != 0) {
        wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                        ("%s: Couldn't set bss filtering\n", __func__));
        up(&ar->arSem);
        return -EIO;
    }
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM scan policy flags=0x%x dwell=%u slot=0 channel=%u\n",
         N3DS_NWM_CONNECT_SCAN_FLAGS, N3DS_NWM_CONNECT_SCAN_DWELL_MS,
         ar->arChannelHint));
'''

CONNECT_SEND_OLD = '''    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
                            ar->arDot11AuthMode, NONE_AUTH,
                            nwm_pairwise_crypto, nwm_pairwise_crypto_len,
                            nwm_group_crypto, nwm_group_crypto_len,
                            ar->arSsidLen, ar->arSsid,
                            ar->arReqBssid, ar->arChannelHint,
                            ar->arConnectCtrlFlags);

    up(&ar->arSem);
'''

CONNECT_SEND_NEW = '''    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
                            ar->arDot11AuthMode, NONE_AUTH,
                            nwm_pairwise_crypto, nwm_pairwise_crypto_len,
                            nwm_group_crypto, nwm_group_crypto_len,
                            ar->arSsidLen, ar->arSsid,
                            ar->arReqBssid, ar->arChannelHint,
                            ar->arConnectCtrlFlags);
    if (status != 0)
        wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);

    up(&ar->arSem);
'''


def load_old_patcher():
    spec = importlib.util.spec_from_file_location("nwm_connection_scan", OLD_PATCH_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load NWM connection-scan patcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def remove_before_once(text: str, start: str, end: str, label: str) -> str:
    if text.count(start) != 1:
        raise RuntimeError(f"{label}: expected one start anchor, found {text.count(start)}")
    start_at = text.index(start)
    end_at = text.find(end, start_at)
    if end_at < 0:
        raise RuntimeError(f"{label}: end anchor not found")
    return text[:start_at] + text[end_at:]


def patch_cfg(text: str) -> str:
    if MARKER in text:
        return text
    old = load_old_patcher()
    if old.MARKER not in text:
        raise RuntimeError("#245 NWM connection-scan baseline marker is missing")

    text = replace_once(text, TOP_ANCHOR, TOP_NEW, "connect policy constants")
    text = replace_once(text, CONNECT_CHANNEL_OLD, "", "early channel setup")
    text = remove_before_once(text, CONNECT_FILTER_START, CONNECT_FILTER_END,
                              "early BSS filter")
    text = replace_once(text, CONNECT_SLOT_OLD, CONNECT_SETUP_NEW, "connect setup")
    text = replace_once(text, CONNECT_SEND_OLD, CONNECT_SEND_NEW, "connect cleanup")
    text = replace_once(text, old.HELPER_NEW, DISCOVERY_HELPER_NEW,
                        "discovery SSID helpers")
    text = replace_once(text, SCAN_VARS_OLD, SCAN_VARS_NEW,
                        "wildcard trace state")
    text = replace_once(text, old.PREP_NEW, DISCOVERY_PREP_NEW,
                        "discovery setup")
    text = replace_once(text, old.START_NEW, DISCOVERY_START_NEW,
                        "explicit discovery channels")
    return replace_once(text, old.COMPLETE_NEW, DISCOVERY_COMPLETE_NEW,
                        "discovery cleanup")


def main() -> None:
    original = CFG.read_text(encoding="utf-8")
    patched = patch_cfg(original)
    if patched != original:
        CFG.write_text(patched, encoding="utf-8")
        print("ar6014_discovery_connect_split: patched")
    else:
        print("ar6014_discovery_connect_split: already patched")


if __name__ == "__main__":
    main()
