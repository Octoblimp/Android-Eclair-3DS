#!/usr/bin/env python3
"""Constrain AR6014 scans to its real 2.4-GHz radio and reject corrupt BSS security.

The Nintendo 3DS AR6014 is an 802.11b/g 2.4-GHz device.  The legacy driver
nevertheless advertised its generic 5-GHz table and submitted START_SCAN with
numChannels=0, causing firmware-wide scans that took long enough for cfg80211
results to age out.  Direct WMI BSSINFO events also need the same fail-closed
privacy/RSN invariant as the validated RAM fallback.

This patch is intentionally idempotent and targets the canonical WSL build
tree.  It fails if the expected source shape drifts.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
CFG = ROOT / "drivers/staging/ath6k_legacy/os/linux/cfg80211.c"
WMI = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi.c"

SCAN_MARKER = "N3DS_AR6014_2GHZ_SCAN_CHANNELS"
BSS_MARKER = "N3DS_WMI_DIRECT_BSS_SECURITY_INTEGRITY"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_cfg80211(text: str) -> str:
    if SCAN_MARKER in text:
        return text

    text = replace_once(
        text,
        "    wdev->wiphy->bands[NL80211_BAND_2GHZ] = &ar6k_band_2ghz;\n"
        "    wdev->wiphy->bands[NL80211_BAND_5GHZ] = &ar6k_band_5ghz;\n",
        "    /* N3DS_AR6014_2GHZ_ONLY_WIPHY: Nintendo's AR6014 is an\n"
        "     * 802.11b/g 2.4-GHz radio.  Do not advertise generic 5-GHz\n"
        "     * channels that this target cannot scan or associate on. */\n"
        "    wdev->wiphy->bands[NL80211_BAND_2GHZ] = &ar6k_band_2ghz;\n"
        "    wdev->wiphy->bands[NL80211_BAND_5GHZ] = NULL;\n",
        "wiphy band restriction",
    )

    text = replace_once(
        text,
        "    bool trace_scan = scan_trace_count < 16;\n",
        "    bool trace_scan = scan_trace_count < 16;\n"
        "    u16 channel_list[WMI_MAX_CHANNELS];\n"
        "    s8 num_channels = 0;\n"
        "    u8 channel_index;\n",
        "scan channel declarations",
    )

    anchor = """    if(ar->arConnected) {
        forceFgScan = 1;
    }

"""
    bounded = """    if(ar->arConnected) {
        forceFgScan = 1;
    }

    /* N3DS_AR6014_2GHZ_SCAN_CHANNELS: honor cfg80211's request, but submit
     * only valid AR6014 2.4-GHz frequencies.  numChannels=0 means an
     * unrestricted firmware scan and was producing 13-17 second cycles. */
    for (channel_index = 0;
         channel_index < request->n_channels &&
         num_channels < WMI_MAX_CHANNELS;
         channel_index++) {
        u16 freq = request->channels[channel_index]->center_freq;

        if (freq == 2484 ||
            (freq >= 2412 && freq <= 2472 && !((freq - 2412) % 5)))
            channel_list[num_channels++] = freq;
    }
    if (!num_channels) {
        static const u16 ar6014_2ghz_channels[] = {
            2412, 2417, 2422, 2427, 2432, 2437, 2442,
            2447, 2452, 2457, 2462, 2467, 2472, 2484
        };

        memcpy(channel_list, ar6014_2ghz_channels,
               sizeof(ar6014_2ghz_channels));
        num_channels = ARRAY_SIZE(ar6014_2ghz_channels);
    }

"""
    text = replace_once(text, anchor, bounded, "bounded channel construction")

    text = replace_once(
        text,
        """            ("AR6002 scan: cfg80211 request ssids=%u first_len=%u channels=%u\\n",
             request->n_ssids,
             request->n_ssids ? request->ssids[0].ssid_len : 0,
             request->n_channels));
""",
        """            ("AR6002 scan: cfg80211 request ssids=%u first_len=%u channels=%u submitted_2ghz=%d\\n",
             request->n_ssids,
             request->n_ssids ? request->ssids[0].ssid_len : 0,
             request->n_channels, num_channels));
""",
        "bounded scan trace",
    )

    text = replace_once(
        text,
        """    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \\
                         0, 0, 0, NULL) != 0) {
""",
        """    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \\
                         0, 0, num_channels, channel_list) != 0) {
""",
        "START_SCAN explicit channels",
    )
    return text


DIRECT_VALIDATOR = r'''
/* N3DS_WMI_DIRECT_BSS_SECURITY_INTEGRITY: direct firmware BSSINFO is
 * untrusted.  Require a bounded IE stream and structurally valid RSN/WPA
 * suites, and never publish a protected IE with the privacy bit clear. */
static int n3ds_wmi_security_suite(const u8 *suite, const u8 *oui)
{
    return !memcmp(suite, oui, 3) && suite[3] != 0;
}

static int n3ds_wmi_validate_rsn(const u8 *ie, int len)
{
    static const u8 rsn_oui[3] = { 0x00, 0x0f, 0xac };
    int count, pos, i;

    if (len < 18 || ie[0] != 1 || ie[1] != 0 ||
        !n3ds_wmi_security_suite(ie + 2, rsn_oui))
        return 0;
    count = ie[6] | (ie[7] << 8);
    if (!count || count > 16 || 8 + count * 4 + 2 > len)
        return 0;
    pos = 8;
    for (i = 0; i < count; i++, pos += 4)
        if (!n3ds_wmi_security_suite(ie + pos, rsn_oui))
            return 0;
    count = ie[pos] | (ie[pos + 1] << 8);
    pos += 2;
    if (!count || count > 16 || pos + count * 4 > len)
        return 0;
    for (i = 0; i < count; i++, pos += 4)
        if (!n3ds_wmi_security_suite(ie + pos, rsn_oui))
            return 0;
    return 1;
}

static int n3ds_wmi_validate_wpa(const u8 *ie, int len)
{
    static const u8 wpa_oui[3] = { 0x00, 0x50, 0xf2 };
    int count, pos, i;

    if (len < 22 || memcmp(ie, "\x00\x50\xf2\x01", 4) ||
        ie[4] != 1 || ie[5] != 0 ||
        !n3ds_wmi_security_suite(ie + 6, wpa_oui))
        return 0;
    count = ie[10] | (ie[11] << 8);
    if (!count || count > 16 || 12 + count * 4 + 2 > len)
        return 0;
    pos = 12;
    for (i = 0; i < count; i++, pos += 4)
        if (!n3ds_wmi_security_suite(ie + pos, wpa_oui))
            return 0;
    count = ie[pos] | (ie[pos + 1] << 8);
    pos += 2;
    if (!count || count > 16 || pos + count * 4 > len)
        return 0;
    for (i = 0; i < count; i++, pos += 4)
        if (!n3ds_wmi_security_suite(ie + pos, wpa_oui))
            return 0;
    return 1;
}

static int n3ds_wmi_validate_bss_security(const u8 *body, int len)
{
    int pos = 12;
    int protected_ie = 0;
    u16 capability;

    if (len < 14 || body[12] != IEEE80211_ELEMID_SSID ||
        body[13] > IEEE80211_NWID_LEN || 14 + body[13] > len)
        return -1;
    capability = body[10] | (body[11] << 8);
    while (pos < len) {
        int id, ie_len;

        if (pos + 2 > len)
            return -2;
        id = body[pos];
        ie_len = body[pos + 1];
        pos += 2;
        if (ie_len > len - pos)
            return -2;
        if (id == IEEE80211_ELEMID_RSN) {
            if (!n3ds_wmi_validate_rsn(body + pos, ie_len))
                return -3;
            protected_ie = 1;
        } else if (id == IEEE80211_ELEMID_VENDOR && ie_len >= 4 &&
                   !memcmp(body + pos, "\x00\x50\xf2\x01", 4)) {
            if (!n3ds_wmi_validate_wpa(body + pos, ie_len))
                return -4;
            protected_ie = 1;
        }
        pos += ie_len;
    }
    if (protected_ie && !(capability & IEEE80211_CAPINFO_PRIVACY))
        return -5;
    return 0;
}

'''


def patch_wmi(text: str) -> str:
    if BSS_MARKER in text:
        return text

    anchor = "static int\nwmi_bssInfo_event_rx(struct wmi_t *wmip, u8 *datap, int len)\n"
    if text.count(anchor) != 1:
        raise RuntimeError(f"direct BSS function: expected one match, found {text.count(anchor)}")
    text = text.replace(anchor, DIRECT_VALIDATOR + anchor, 1)

    old = """    u8 beacon_ssid_len = 0;

    if (len <= sizeof(WMI_BSS_INFO_HDR)) {
"""
    new = """    u8 beacon_ssid_len = 0;
    static unsigned int n3ds_security_reject_traces;
    int security_status;

    if (len <= sizeof(WMI_BSS_INFO_HDR)) {
"""
    text = replace_once(text, old, new, "direct BSS validator declarations")

    old = """    bss = wlan_find_node(&wmip->wmi_scan_table, bih->bssid);

    if (bih->rssi > 0) {
"""
    new = """    security_status = n3ds_wmi_validate_bss_security(
        datap + sizeof(WMI_BSS_INFO_HDR), len - sizeof(WMI_BSS_INFO_HDR));
    if (security_status) {
        if (n3ds_security_reject_traces < 32) {
            n3ds_security_reject_traces++;
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 BSS: direct reject security=%d channel=%u bssid=%pM\\n",
                 security_status, bih->channel, bih->bssid));
        }
        return A_EINVAL;
    }

    bss = wlan_find_node(&wmip->wmi_scan_table, bih->bssid);

    if (bih->rssi > 0) {
"""
    return replace_once(text, old, new, "direct BSS validation call")


def main() -> None:
    for path in (CFG, WMI):
        if not path.exists():
            raise SystemExit(f"missing canonical source: {path}")
    CFG.write_text(patch_cfg80211(CFG.read_text()))
    WMI.write_text(patch_wmi(WMI.read_text()))
    print("patch_ar6014_2ghz_scan: bounded channels and direct BSS security installed")


if __name__ == "__main__":
    main()
