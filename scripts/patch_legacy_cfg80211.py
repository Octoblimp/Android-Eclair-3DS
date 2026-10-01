from a3ds_paths import A3DS_ROOT
import re

path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/cfg80211.c"
with open(path) as f:
    content = f.read()

def replace_regex_once(pattern, new, label):
    global content
    matches = list(re.finditer(pattern, content))
    assert len(matches) == 1, f"{label}: expected exactly 1 match, found {len(matches)}"
    content = content[:matches[0].start()] + new + content[matches[0].end():]

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

def replace_all(old, new, label, expected):
    global content
    count = content.count(old)
    assert count == expected, f"{label}: expected {expected} matches, found {count}"
    content = content.replace(old, new)

# 1. Band enum rename (7 occurrences: CHAN2G/CHAN5G macros + any direct uses)
replace_all("IEEE80211_BAND_2GHZ", "NL80211_BAND_2GHZ", "band 2ghz rename", 4)
replace_all("IEEE80211_BAND_5GHZ", "NL80211_BAND_5GHZ", "band 5ghz rename", 3)

# 2. cfg80211_put_bss needs a wiphy first argument now (2 call sites, both
# inside ar6k_cfg80211_connect_event which has ar->wdev->wiphy in scope)
replace_all(
    "\t    cfg80211_put_bss(bss);",
    "\t    cfg80211_put_bss(ar->wdev->wiphy, bss);",
    "put_bss #1", 1,
)
replace_all(
    "    cfg80211_put_bss(bss);",
    "    cfg80211_put_bss(ar->wdev->wiphy, bss);",
    "put_bss #2", 1,
)

# 3. cfg80211_ibss_joined needs a channel argument now.
# connect_event: ibss_channel is in scope.
replace_once(
    "        cfg80211_ibss_joined(ar->arNetDev, bssid, GFP_KERNEL);\n        return;\n    }\n\n    if (false == ar->arConnected) {",
    "        cfg80211_ibss_joined(ar->arNetDev, bssid, ibss_channel, GFP_KERNEL);\n        return;\n    }\n\n    if (false == ar->arConnected) {",
    "ibss_joined in connect_event",
)
# disconnect_event: no channel tracked at this point (this is an ad-hoc
# rejoin-after-loss notification, not our primary station-mode path) --
# pass NULL, matching what cfg80211_ibss_joined tolerates when no specific
# channel is known.
replace_once(
    "        A_MEMZERO(bssid, ETH_ALEN);\n        cfg80211_ibss_joined(ar->arNetDev, bssid, GFP_KERNEL);\n        return;",
    "        A_MEMZERO(bssid, ETH_ALEN);\n        cfg80211_ibss_joined(ar->arNetDev, bssid, NULL, GFP_KERNEL);\n        return;",
    "ibss_joined in disconnect_event",
)

# 4. cfg80211_roamed: old 6-arg form -> new struct cfg80211_roam_info form.
replace_once(
    """    } else {
        /* inform roam event to cfg80211 */
	cfg80211_roamed(ar->arNetDev, ibss_channel, bssid,
                        assocReqIe, assocReqLen,
                        assocRespIe, assocRespLen,
                        GFP_KERNEL);
    }""",
    """    } else {
        /* inform roam event to cfg80211 */
        struct cfg80211_roam_info roam_info = {
            .channel = ibss_channel,
            .bssid = bssid,
            .req_ie = assocReqIe,
            .req_ie_len = assocReqLen,
            .resp_ie = assocRespIe,
            .resp_ie_len = assocRespLen,
        };
        cfg80211_roamed(ar->arNetDev, &roam_info, GFP_KERNEL);
    }""",
    "cfg80211_roamed restructure",
)

# 5. cfg80211_disconnected gained a "locally_generated" bool before gfp.
replace_regex_once(
    r"cfg80211_disconnected\(ar->arNetDev,\s*reason,\s*NULL, 0,\s*GFP_KERNEL\);",
    "cfg80211_disconnected(ar->arNetDev,\n\t\t\t\t\t\t\t      reason,\n\t\t\t\t\t\t\t      NULL, 0,\n\t\t\t\t\t\t\t      false,\n\t\t\t\t\t\t\t      GFP_KERNEL);",
    "disconnected #1 (connect_event failure path)",
)

# 6. cfg80211_scan_done now takes a struct cfg80211_scan_info* instead of
# a bool. Three call sites: disconnect_event (aborted), and two in
# scanComplete_event (aborted, completed).
replace_once(
    "    if (ar->scan_request) {\n\tcfg80211_scan_done(ar->scan_request, true);\n        ar->scan_request = NULL;\n    }",
    "    if (ar->scan_request) {\n\tstruct cfg80211_scan_info scan_info = { .aborted = true };\n\tcfg80211_scan_done(ar->scan_request, &scan_info);\n        ar->scan_request = NULL;\n    }",
    "scan_done in disconnect_event",
)
replace_once(
    "    if ((status == A_ECANCELED) || (status == A_EBUSY)) {\n\t    cfg80211_scan_done(ar->scan_request, true);\n\t    goto out;\n    }",
    "    if ((status == A_ECANCELED) || (status == A_EBUSY)) {\n\t    struct cfg80211_scan_info scan_info_aborted = { .aborted = true };\n\t    cfg80211_scan_done(ar->scan_request, &scan_info_aborted);\n\t    goto out;\n    }",
    "scan_done aborted in scanComplete_event",
)
replace_once(
    "    cfg80211_scan_done(ar->scan_request, false);",
    "    {\n\tstruct cfg80211_scan_info scan_info_done = { .aborted = false };\n\tcfg80211_scan_done(ar->scan_request, &scan_info_done);\n    }",
    "scan_done completed in scanComplete_event",
)

# 7. struct cfg80211_ibss_params: "channel" member replaced by "chandef"
# (a struct cfg80211_chan_def with a .chan member).
replace_once(
    "    if(ibss_param->channel) {\n        ar->arChannelHint = ibss_param->channel->center_freq;\n    }",
    "    if(ibss_param->chandef.chan) {\n        ar->arChannelHint = ibss_param->chandef.chan->center_freq;\n    }",
    "ibss_params channel -> chandef",
)

# 8. get_station: STATION_INFO_* -> BIT_ULL(NL80211_STA_INFO_*),
# RATE_INFO_FLAGS_40_MHZ_WIDTH -> txrate.bw = RATE_INFO_BW_40 (separate
# bandwidth field in modern kernels, not a flag bit), and mac must be const.
replace_once(
    "static int ar6k_get_station(struct wiphy *wiphy, struct net_device *dev,\n\t\t\t    u8 *mac, struct station_info *sinfo)",
    "static int ar6k_get_station(struct wiphy *wiphy, struct net_device *dev,\n\t\t\t    const u8 *mac, struct station_info *sinfo)",
    "get_station mac const",
)
replace_once(
    """	if (ar->arTargetStats.rx_bytes) {
		sinfo->rx_bytes = ar->arTargetStats.rx_bytes;
		sinfo->filled |= STATION_INFO_RX_BYTES;
		sinfo->rx_packets = ar->arTargetStats.rx_packets;
		sinfo->filled |= STATION_INFO_RX_PACKETS;
	}

	if (ar->arTargetStats.tx_bytes) {
		sinfo->tx_bytes = ar->arTargetStats.tx_bytes;
		sinfo->filled |= STATION_INFO_TX_BYTES;
		sinfo->tx_packets = ar->arTargetStats.tx_packets;
		sinfo->filled |= STATION_INFO_TX_PACKETS;
	}

	sinfo->signal = ar->arTargetStats.cs_rssi;
	sinfo->filled |= STATION_INFO_SIGNAL;""",
    """	if (ar->arTargetStats.rx_bytes) {
		sinfo->rx_bytes = ar->arTargetStats.rx_bytes;
		sinfo->filled |= BIT_ULL(NL80211_STA_INFO_RX_BYTES64);
		sinfo->rx_packets = ar->arTargetStats.rx_packets;
		sinfo->filled |= BIT_ULL(NL80211_STA_INFO_RX_PACKETS);
	}

	if (ar->arTargetStats.tx_bytes) {
		sinfo->tx_bytes = ar->arTargetStats.tx_bytes;
		sinfo->filled |= BIT_ULL(NL80211_STA_INFO_TX_BYTES64);
		sinfo->tx_packets = ar->arTargetStats.tx_packets;
		sinfo->filled |= BIT_ULL(NL80211_STA_INFO_TX_PACKETS);
	}

	sinfo->signal = ar->arTargetStats.cs_rssi;
	sinfo->filled |= BIT_ULL(NL80211_STA_INFO_SIGNAL);""",
    "get_station STATION_INFO flags",
)
replace_once(
    "\t\tsinfo->txrate.flags |= RATE_INFO_FLAGS_40_MHZ_WIDTH;\n\t\tsinfo->txrate.flags |= RATE_INFO_FLAGS_MCS;",
    "\t\tsinfo->txrate.bw = RATE_INFO_BW_40;\n\t\tsinfo->txrate.flags |= RATE_INFO_FLAGS_MCS;",
    "RATE_INFO_FLAGS_40_MHZ_WIDTH -> bw field",
)
replace_once(
    "\tsinfo->filled |= STATION_INFO_TX_BITRATE;",
    "\tsinfo->filled |= BIT_ULL(NL80211_STA_INFO_TX_BITRATE);",
    "STATION_INFO_TX_BITRATE",
)

# 9. cfg80211_ops function signature updates. This driver is single-adapter
# (no multi-vif support -- add/del_virtual_intf already just return
# -EOPNOTSUPP), so these are minimal signature adaptations, not a rewrite
# of internal logic.
replace_once(
    """static struct net_device *
ar6k_cfg80211_add_virtual_intf(struct wiphy *wiphy, char *name,
            				    enum nl80211_iftype type, u32 *flags,
            				    struct vif_params *params)
{""",
    """static struct wireless_dev *
ar6k_cfg80211_add_virtual_intf(struct wiphy *wiphy, const char *name,
            				    unsigned char name_assign_type,
            				    enum nl80211_iftype type,
            				    struct vif_params *params)
{""",
    "add_virtual_intf signature",
)

replace_once(
    "static int\nar6k_cfg80211_del_virtual_intf(struct wiphy *wiphy, struct net_device *dev)\n{",
    "static int\nar6k_cfg80211_del_virtual_intf(struct wiphy *wiphy, struct wireless_dev *wdev)\n{",
    "del_virtual_intf signature",
)

replace_once(
    "static int\nar6k_cfg80211_change_iface(struct wiphy *wiphy, struct net_device *ndev,\n                           enum nl80211_iftype type, u32 *flags,\n                           struct vif_params *params)\n{",
    "static int\nar6k_cfg80211_change_iface(struct wiphy *wiphy, struct net_device *ndev,\n                           enum nl80211_iftype type,\n                           struct vif_params *params)\n{",
    "change_iface signature",
)

replace_once(
    """static int
ar6k_cfg80211_scan(struct wiphy *wiphy, struct net_device *ndev,
                   struct cfg80211_scan_request *request)
{
    struct ar6_softc *ar = (struct ar6_softc *)ar6k_priv(ndev);""",
    """static int
ar6k_cfg80211_scan(struct wiphy *wiphy,
                   struct cfg80211_scan_request *request)
{
    struct net_device *ndev = request->wdev->netdev;
    struct ar6_softc *ar = (struct ar6_softc *)ar6k_priv(ndev);""",
    "scan signature",
)

replace_once(
    "static int\nar6k_cfg80211_set_txpower(struct wiphy *wiphy, enum nl80211_tx_power_setting type, int dbm)\n{",
    "static int\nar6k_cfg80211_set_txpower(struct wiphy *wiphy, struct wireless_dev *wdev, enum nl80211_tx_power_setting type, int dbm)\n{",
    "set_txpower signature",
)

replace_once(
    "static int\nar6k_cfg80211_get_txpower(struct wiphy *wiphy, int *dbm)\n{",
    "static int\nar6k_cfg80211_get_txpower(struct wiphy *wiphy, struct wireless_dev *wdev, int *dbm)\n{",
    "get_txpower signature",
)

with open(path, 'w') as f:
    f.write(content)
print("ALL PATCHES APPLIED OK")
