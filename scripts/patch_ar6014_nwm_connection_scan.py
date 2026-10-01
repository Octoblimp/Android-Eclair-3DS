#!/usr/bin/env python3
"""Match Nintendo NWM's connection-scan command order and lifetime."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


CFG = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
    "ath6k_legacy/os/linux/cfg80211.c"
)
MARKER = "N3DS_AR6014_NWM_CONNECTION_SCAN"

HELPER_ANCHOR = '''#define N3DS_MAX_SCAN_PROBED_SSIDS 5

static int
ar6k_cfg80211_scan(struct wiphy *wiphy,
'''

HELPER_NEW = r'''#define N3DS_MAX_SCAN_PROBED_SSIDS 5

/* N3DS_AR6014_NWM_CONNECTION_SCAN: the raw NWM path at 0x0012ad70
 * programs selected-SSID slot zero, command 8's connection-scan policy,
 * command 17's persistent channel table, command 9's BSS filter, and only
 * then command 7 START_SCAN.  Slot zero must survive a successful discovery
 * scan because WMI_CONNECT consumes that selected profile; auxiliary slots
 * remain per-request and are always released. */
#define N3DS_NWM_CONNECTION_SCAN_DWELL_MS 20
#define N3DS_NWM_CONNECTION_SCAN_FLAGS \
    (CONNECT_SCAN_CTRL_FLAGS | ACTIVE_SCAN_CTRL_FLAGS)

static int
n3ds_ar6014_program_scan_ssids(struct ar6_softc *ar,
                               struct cfg80211_scan_request *request)
{
    u8 i, extra_slot = 0;
    bool selected_programmed = false;

    for (i = 0; i < request->n_ssids; i++) {
        u8 slot;

        if (!request->ssids[i].ssid_len)
            continue;
        if (!selected_programmed) {
            slot = 0;
            selected_programmed = true;
        } else {
            if (extra_slot >= N3DS_MAX_SCAN_PROBED_SSIDS)
                break;
            slot = ++extra_slot;
        }
        if (wmi_probedSsid_cmd(ar->arWmi, slot, SPECIFIC_SSID_FLAG,
                               request->ssids[i].ssid_len,
                               request->ssids[i].ssid) != 0)
            return -EIO;
    }

    /* A broadcast scan must retire a selected profile from an earlier scan. */
    if (!selected_programmed &&
        wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL) != 0)
        return -EIO;
    return 0;
}

static void
n3ds_ar6014_clear_scan_ssids(struct ar6_softc *ar,
                             struct cfg80211_scan_request *request,
                             bool clear_selected)
{
    u8 i, extra_slot = 0;
    bool selected_seen = false;

    for (i = 0; i < request->n_ssids; i++) {
        if (!request->ssids[i].ssid_len)
            continue;
        if (!selected_seen) {
            selected_seen = true;
            if (clear_selected)
                wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG,
                                   0, NULL);
            continue;
        }
        if (extra_slot >= N3DS_MAX_SCAN_PROBED_SSIDS)
            break;
        wmi_probedSsid_cmd(ar->arWmi, ++extra_slot, DISABLE_SSID_FLAG,
                           0, NULL);
    }
}

static int
ar6k_cfg80211_scan(struct wiphy *wiphy,
'''

FILTER_OLD = '''    if (!ar->arUserBssFilter) {
        if (wmi_bssfilter_cmd(ar->arWmi,
                             (ar->arConnected ? ALL_BUT_BSS_FILTER : ALL_BSS_FILTER),
                             0) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("%s: Couldn't set bss filtering\\n", __func__));
            return -EIO;
        }
    }

'''

SCAN_RET_OLD = '''    struct ar6_softc *ar = (struct ar6_softc *)ar6k_priv(ndev);
    int ret = 0;
    u32 forceFgScan = 0;
'''

SCAN_RET_NEW = '''    struct ar6_softc *ar = (struct ar6_softc *)ar6k_priv(ndev);
    u32 forceFgScan = 0;
'''

PREP_OLD = '''    /* N3DS_AR6014_NWM_CHANNEL_TABLE: command 17 persists the 11G MHz
     * channel set used by the target-owned WMI_CONNECT search.  START_SCAN's
     * separate list is retained because it bounds this host-requested scan. */
    if (wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE,
                                  num_channels, channel_list) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: NWM channel table programming failed channels=%d\\n",
             num_channels));
        return -EIO;
    }
    if (trace_scan)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: NWM channel table mode=11G channels=%d\\n",
             num_channels));

    /* N3DS_CFG80211_SCAN_REQUEST_ORDER: the Nintendo target can report an
     * empty SCAN_COMPLETE immediately after accepting START_SCAN.  On SMP,
     * the WMI receive worker may therefore run before this caller returns.
     * Publish request ownership before sending the command so completion
     * cannot observe NULL; give ownership back to cfg80211 if send fails. */
    if (cmpxchg(&ar->scan_request, NULL, request) != NULL)
        return -EBUSY;

    {
        u8 i, programmed = 0;

        for (i = 0; i < request->n_ssids &&
                    programmed < N3DS_MAX_SCAN_PROBED_SSIDS; i++) {
            if (!request->ssids[i].ssid_len)
                continue;
            if (wmi_probedSsid_cmd(ar->arWmi, programmed + 1,
                                   SPECIFIC_SSID_FLAG,
                                   request->ssids[i].ssid_len,
                                   request->ssids[i].ssid) != 0) {
                while (programmed)
                    wmi_probedSsid_cmd(ar->arWmi, programmed--,
                                       DISABLE_SSID_FLAG, 0, NULL);
                cmpxchg(&ar->scan_request, request, NULL);
                return -EIO;
            }
            programmed++;
        }
    }

'''

PREP_NEW = r'''    /* N3DS_CFG80211_SCAN_REQUEST_ORDER: publish ownership before the
     * target can return an immediate completion.  Every setup error below
     * unwinds the same slot and ownership state. */
    if (cmpxchg(&ar->scan_request, NULL, request) != NULL)
        return -EBUSY;

    /* NWM 0x0012ad70 order: selected slot 0 -> command 8 -> command 17 ->
     * command 9 -> command 7.  CONNECT_SCAN is the field #244 omitted: host
     * scans could report BSSes while WMI_CONNECT's own search returned
     * NO_NETWORK_AVAIL. */
    if (n3ds_ar6014_program_scan_ssids(ar, request) != 0)
        goto setup_fail;
    if (wmi_scanparams_cmd(ar->arWmi, 0xffff, 0xffff, 0xffff,
                           N3DS_NWM_CONNECTION_SCAN_DWELL_MS,
                           N3DS_NWM_CONNECTION_SCAN_DWELL_MS,
                           N3DS_NWM_CONNECTION_SCAN_DWELL_MS,
                           0, N3DS_NWM_CONNECTION_SCAN_FLAGS, 0, 0) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: NWM connection-scan policy programming failed\n"));
        goto setup_fail;
    }
    if (wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE,
                                  num_channels, channel_list) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: NWM channel table programming failed channels=%d\n",
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
            ("AR6002 scan: NWM connection scan flags=0x%x dwell=%u "
             "channel_table=%d start_list=0\n",
             N3DS_NWM_CONNECTION_SCAN_FLAGS,
             N3DS_NWM_CONNECTION_SCAN_DWELL_MS, num_channels));

'''

START_OLD = '''    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \\
                         0, 0, num_channels, channel_list) != 0) {
        u8 i, programmed = 0;

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("%s: wmi_startscan_cmd failed\\n", __func__));
        /* N3DS_SCAN_START_FAILURE_CLEANUP: command 10 slots were armed
         * before START_SCAN, so a rejected start must not leave stale probes. */
        for (i = 0; i < request->n_ssids &&
                    programmed < N3DS_MAX_SCAN_PROBED_SSIDS; i++) {
            if (!request->ssids[i].ssid_len)
                continue;
            programmed++;
            wmi_probedSsid_cmd(ar->arWmi, programmed,
                               DISABLE_SSID_FLAG, 0, NULL);
        }
        cmpxchg(&ar->scan_request, request, NULL);
        ret = -EIO;
    } else if (trace_scan) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: START_SCAN submitted\\n"));
    }

    return ret;
'''

START_NEW = r'''    /* NWM command 7 uses the persistent command-17 table: its own list is
     * empty, and the selected profile remains the slot-zero scan authority. */
    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \
                         N3DS_NWM_CONNECTION_SCAN_DWELL_MS, 0,
                         0, NULL) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("%s: wmi_startscan_cmd failed\n", __func__));
        goto setup_fail;
    }
    if (trace_scan)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: START_SCAN submitted\n"));
    return 0;

setup_fail:
    /* N3DS_SCAN_START_FAILURE_CLEANUP: no connect can consume slot zero. */
    n3ds_ar6014_clear_scan_ssids(ar, request, true);
    cmpxchg(&ar->scan_request, request, NULL);
    return -EIO;
'''

COMPLETE_OLD = '''    /* Directed-SSID slots were programmed before START_SCAN and must be
     * released on both success and abort, before returning the request. */
    {
        u8 i, programmed = 0;

        for (i = 0; i < request->n_ssids &&
                    programmed < N3DS_MAX_SCAN_PROBED_SSIDS; i++) {
            if (!request->ssids[i].ssid_len)
                continue;
            programmed++;
            wmi_probedSsid_cmd(ar->arWmi, programmed,
                               DISABLE_SSID_FLAG, 0, NULL);
        }
    }
'''

COMPLETE_NEW = '''    /* Auxiliary slots are per-request.  Preserve selected slot zero only
     * after a successful scan so the following WMI_CONNECT sees the profile. */
    n3ds_ar6014_clear_scan_ssids(ar, request, scan_info.aborted);
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_cfg(text: str) -> str:
    if MARKER in text:
        return text
    text = replace_once(text, HELPER_ANCHOR, HELPER_NEW, "SSID helpers")
    text = replace_once(
        text, SCAN_RET_OLD, SCAN_RET_NEW, "retired scan result"
    )
    text = replace_once(text, FILTER_OLD, "", "early BSS filter")
    text = replace_once(text, PREP_OLD, PREP_NEW, "NWM scan preparation")
    text = replace_once(text, START_OLD, START_NEW, "persistent-table START_SCAN")
    return replace_once(
        text, COMPLETE_OLD, COMPLETE_NEW, "scan completion slot lifetime"
    )


def main() -> None:
    original = CFG.read_text(encoding="utf-8")
    patched = patch_cfg(original)
    if patched != original:
        CFG.write_text(patched, encoding="utf-8")
        print("ar6014_nwm_connection_scan: patched")
    else:
        print("ar6014_nwm_connection_scan: already patched")


if __name__ == "__main__":
    main()
