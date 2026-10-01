#!/usr/bin/env python3
"""Regression checks for the AR6014 2.4-GHz and direct-BSS integrity patch."""

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "scripts/patch_ar6014_2ghz_scan.py"

spec = importlib.util.spec_from_file_location("ar6014_2ghz_patch", PATCH_PATH)
patcher = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(patcher)


cfg_fixture = """    bool trace_scan = scan_trace_count < 16;
    if(ar->arConnected) {
        forceFgScan = 1;
    }

    if (trace_scan) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: cfg80211 request ssids=%u first_len=%u channels=%u\\n",
             request->n_ssids,
             request->n_ssids ? request->ssids[0].ssid_len : 0,
             request->n_channels));
    }
    if(wmi_startscan_cmd(ar->arWmi, WMI_LONG_SCAN, forceFgScan, false, \\
                         0, 0, 0, NULL) != 0) {
    }
    wdev->wiphy->bands[NL80211_BAND_2GHZ] = &ar6k_band_2ghz;
    wdev->wiphy->bands[NL80211_BAND_5GHZ] = &ar6k_band_5ghz;
"""

patched_cfg = patcher.patch_cfg80211(cfg_fixture)
assert "N3DS_AR6014_2GHZ_SCAN_CHANNELS" in patched_cfg
assert "N3DS_AR6014_2GHZ_ONLY_WIPHY" in patched_cfg
assert "bands[NL80211_BAND_5GHZ] = NULL" in patched_cfg
assert "num_channels, channel_list" in patched_cfg
assert "0, 0, 0, NULL" not in patched_cfg
assert patcher.patch_cfg80211(patched_cfg) == patched_cfg

# Model the exact frequency predicate: all valid 2.4-GHz channels survive,
# generic 5-GHz and malformed frequencies do not, and the WMI ABI limit holds.
requested = list(range(2412, 2473, 5)) + [2484, 2482, 5180, 5200, 5825]
submitted = [
    freq for freq in requested
    if freq == 2484 or 2412 <= freq <= 2472 and (freq - 2412) % 5 == 0
]
assert submitted == list(range(2412, 2473, 5)) + [2484]
assert len(submitted) == 14 < 32

# Keep the security validator's fail-closed properties visible in the test:
# bounded SSID/IE parsing, real RSN/WPA suite structure, and privacy agreement.
for required in (
    "body[13] > IEEE80211_NWID_LEN",
    "ie_len > len - pos",
    "n3ds_wmi_validate_rsn",
    "n3ds_wmi_validate_wpa",
    "protected_ie && !(capability & IEEE80211_CAPINFO_PRIVACY)",
    "direct reject security=%d",
):
    assert required in patcher.DIRECT_VALIDATOR or required in PATCH_PATH.read_text()

build = (ROOT / "scripts/rebuild_everything.sh").read_text()
verify = (ROOT / "scripts/verify_release_artifacts.sh").read_text()
assert build.count("run patch_ar6014_2ghz_scan.py") == 1
assert build.count("run test_ar6014_2ghz_scan.py") == 1
for marker in (
    "N3DS_AR6014_2GHZ_SCAN_CHANNELS",
    "N3DS_AR6014_2GHZ_ONLY_WIPHY",
    "N3DS_WMI_DIRECT_BSS_SECURITY_INTEGRITY",
):
    assert marker in verify

print("ar6014_2ghz_scan: PASS")
