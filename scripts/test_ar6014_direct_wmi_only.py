#!/usr/bin/env python3
"""Regression checks for direct full-header NWM BSS events without RAM harvest."""

import importlib.util
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "scripts/patch_ar6014_remove_ram_harvest.py"
spec = importlib.util.spec_from_file_location("direct_wmi_patch", PATCH_PATH)
patcher = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(patcher)

# Captured #202 BSSIDs beginning a9:ff prove HDR2 consumed the little-endian
# s16 RSSI as the first two MAC bytes.  Model both interpretations exactly.
real_bssid = bytes.fromhex("b6705dcc1122")
body = b"\x01\x02\x03\x04\x05\x06\x07\x08" + struct.pack("<HH", 100, 0x0411)
body += b"\x00\x08HomeWifi" + b"\x01\x01\x82"
full = struct.pack("<HBBh6sI", 2412, 1, 8, -87, real_bssid, 0) + body
assert len(full[:16]) == 16
assert full[4:10] == bytes.fromhex("a9ffb6705dcc")
assert full[16 + 12] == 0 and full[16 + 13] == 8
assert full[12 + 12] == 100  # old HDR2 conversion points at beacon interval

script = PATCH_PATH.read_text()
for required in (
    "N3DS_AR6014_DIRECT_WMI_ONLY",
    "N3DS_NWM_FULL_BSS_HEADER",
    "wmi_n3ds_full_bss_header",
    "status = wmi_bssInfo_event_rx(wmip, datap, len)",
    "direct BSS accepted=%u; no RAM harvest",
):
    assert required in script

for forbidden in (
    "run patch_ar6014_targeted_harvest.py",
    "run patch_ar6014_validated_bss_harvest.py",
    "run patch_ar6014_direct_bss_preference.py",
    "run patch_wpa_scan_harvest_timeout.py",
    "run test_ar6014_validated_bss.py",
    "run test_ar6014_direct_bss_preference.py",
):
    assert forbidden not in (ROOT / "scripts/rebuild_everything.sh").read_text()

verify = (ROOT / "scripts/verify_release_artifacts.sh").read_text()
assert "FATAL: RAM harvest source survived" in verify
assert "N3DS_NWM_FULL_BSS_HEADER" in verify
assert "direct BSS accepted=%u; no RAM harvest" in verify

print("ar6014_direct_wmi_only: PASS")
