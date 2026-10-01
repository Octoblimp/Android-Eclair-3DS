#!/usr/bin/env python3
"""Advertise the legacy AR6002 driver's supported cfg80211 scan IE size."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PATH = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
    "ath6k_legacy/os/linux/cfg80211.c"
)

OLD = """    /* max num of ssids that can be probed during scanning */
    wdev->wiphy->max_scan_ssids = MAX_PROBED_SSID_INDEX;
    wdev->wiphy->bands[NL80211_BAND_2GHZ] = &ar6k_band_2ghz;
"""

NEW = """    /* max num of ssids that can be probed during scanning */
    wdev->wiphy->max_scan_ssids = MAX_PROBED_SSID_INDEX;
    /* N3DS_CFG80211_SCAN_IE_CAPABILITY: wiphy_new() leaves this at zero.
     * wpa_supplicant 2.10 includes generic probe-request IEs, so nl80211
     * rejected every scan with -EINVAL before this driver's .scan callback.
     * Match the maintained ath6kl driver's advertised scan-IE limit. */
    wdev->wiphy->max_scan_ie_len = 1000;
    wdev->wiphy->bands[NL80211_BAND_2GHZ] = &ar6k_band_2ghz;
"""

text = PATH.read_text()
MARKER = "N3DS_CFG80211_SCAN_IE_CAPABILITY"
if MARKER in text:
    print("N3DS WiFi scan IE capability already present")
elif text.count(OLD) == 1:
    PATH.write_text(text.replace(OLD, NEW))
    print("Applied N3DS WiFi scan IE capability")
else:
    raise SystemExit("Expected unique legacy wiphy scan-capability block not found")
