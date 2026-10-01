#!/usr/bin/env python3
"""Contracts for failures demonstrated by the 2026-09-05 live ADB capture."""

import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
patcher = (ROOT / "scripts/patch_telco_stock_apps.py").read_text(encoding="utf-8")
status = (ROOT / "third_party/frameworks/base/services/java/com/android/server/status/StatusBarPolicy.java").read_text(encoding="utf-8")
status_patcher = (ROOT / "scripts/patch_telco_statusbar.py").read_text(encoding="utf-8")
pipeline = (ROOT / "scripts/rebuild_everything.sh").read_text(encoding="utf-8")
verifier = (ROOT / "scripts/verify_release_artifacts.sh").read_text(encoding="utf-8")

for marker in (
    "N3DS_MMS_MISSING_DRM_PROVIDER_GUARD",
    '<uses-permission android:name="io.divergen.telco.ACCESS" />',
):
    assert marker in patcher, marker

# N3DS_DIALER_OPTIONAL_TONE_JNI keeps the keypad alive when the ToneGenerator
# JNI is missing, instead of taking an UnsatisfiedLinkError.  It used to be
# asserted against patch_telco_stock_apps.py, but the dialer source that hunk
# edited is no longer in the workspace and nothing here rebuilds Contacts.apk,
# so the only place the guard can be checked is the artifact that ships it.
#
# N3DS_NO_STOCK_CONTACTS (#317): that app, and the guards with it, is retired.
# N3dsDialer is the dialer; ContactsProvider stays.  Now the check is that the
# stock app did not come back.
contacts_apk = ROOT / "sdcard/linux/android/system/app/Contacts.apk"
assert not contacts_apk.exists(), "retired stock Contacts.apk is staged: %s" % contacts_apk

assert "N3DS_TELCO_STATUSBAR_ONLINE_STATE" in status
assert "N3DS_TELCO_STATUSBAR_LATENCY_BARS" in status
assert "n3ds_telco_status" in status
assert "n3ds_telco_latency_ms" in status
assert "getN3dsTelcoSignalLevel()" in status
for threshold in ("latency < 150", "latency < 400", "latency < 1000", "latency < 2500"):
    assert threshold in status, threshold
assert "now - sample > 45000" in status
assert "n3ds_telco_ping" not in status
assert "N3DS_TELCO_STATUSBAR_ONLINE_STATE" in status_patcher
assert "N3DS_TELCO_STATUSBAR_LATENCY_BARS" in status_patcher
assert "n3ds_telco_status" in status_patcher
assert "n3ds_telco_latency_ms" in status_patcher
assert 'if "n3ds_telco_ping" in source' in status_patcher

service = (ROOT / "content/stock-app-overlays/Phone/src/com/android/phone/TelcoService.java").read_text(encoding="utf-8")
http = (ROOT / "content/stock-app-overlays/Phone/src/com/android/phone/TelcoHttp.java").read_text(encoding="utf-8")
config = (ROOT / "content/stock-app-overlays/Phone/src/com/android/phone/TelcoConfig.java").read_text(encoding="utf-8")
settings = (ROOT / "content/settings/src/com/android/settings/MobileDataSettings.java").read_text(encoding="utf-8")
assert "publishLatency(this, latency)" in service
assert "02:00:00:00:00:00" in service
assert "mobile_data_on_boot_set" in service and "setMobileDataOnBoot" in service
assert "TelcoConfig.writeEnrollment" in http
assert "output.getFD().sync()" in config and "atomically replace" in config
assert "Unable to atomically replace registration file" in config
assert "mobile_data_on_boot_set" in settings

assert "run patch_telco_statusbar.py" in pipeline
assert "test_telco_live_regressions.py" in verifier
print("telco_live_regressions: PASS")
