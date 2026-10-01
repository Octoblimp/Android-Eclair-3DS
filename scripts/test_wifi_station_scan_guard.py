#!/usr/bin/env python3
"""Focused contract for station-safe framework scan ownership."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
JNI = ROOT / "third_party/frameworks/base/core/jni/android_net_wifi_Wifi.cpp"
SERVICE = ROOT / "third_party/frameworks/base/services/java/com/android/server/WifiService.java"
TRACKER = ROOT / "third_party/frameworks/base/wifi/java/android/net/wifi/WifiStateTracker.java"
MARKER = "N3DS_WIFI_STATION_SCAN_OWNERSHIP"


def main() -> None:
    if not JNI.is_file() or not SERVICE.is_file() or not TRACKER.is_file():
        raise SystemExit("canonical Wi-Fi sources missing")
    jni = JNI.read_text()
    service = SERVICE.read_text()
    tracker = TRACKER.read_text()
    if jni.count(MARKER) != 1 or service.count(MARKER) != 1:
        raise SystemExit("station scan guard marker must appear once per owner")
    writer = jni[jni.index("android_net_wifi_setScanResultHandlingCommand"):
                 jni.index("android_net_wifi_addToBlacklistCommand")]
    if "mode = 1;" not in writer or "AP_SCAN %d" not in writer:
        raise SystemExit("JNI AP_SCAN writer is not clamped to station mode")
    if 'AP_SCAN %d", mode' not in writer:
        raise SystemExit("JNI writer lost bounded formatting")
    if 'return (jboolean)!cmdTooLong && doBooleanCommand(cmdstr, "OK");' not in writer:
        raise SystemExit("JNI AP_SCAN writer lost its bounded failure result")
    gate = service[service.index("public boolean startScan(boolean forceActive)"):
                service.index("public boolean setWifiEnabled(boolean enable)") ]
    for state in ("ASSOCIATING", "ASSOCIATED", "FOUR_WAY_HANDSHAKE", "GROUP_HANDSHAKE"):
        if f"case {state}:" not in gate:
            raise SystemExit(f"missing association scan gate: {state}")
    if "return false;" not in gate:
        raise SystemExit("association scan gate does not reject safely")
    if "setScanResultHandlingCommand" in gate:
        raise SystemExit("WifiService still writes AP_SCAN policy during startScan")
    if "return WifiNative.scanCommand(forceActive);" not in gate:
        raise SystemExit("WifiService lost the normal scan fallback")

    # The user-off and Mobile Data handover paths are intentionally separate
    # from the station-scan guard.  Keep their stop/restart contract visible in
    # the same focused regression so a safety fix cannot silently strand Wi-Fi.
    if "public synchronized boolean disconnectAndStop()" not in tracker:
        raise SystemExit("intentional Wi-Fi stop path missing")
    if "mRunState = RUN_STATE_STOPPING" not in tracker:
        raise SystemExit("Wi-Fi stop/handover state transition missing")
    if "case MESSAGE_STOP_WIFI:" not in service or "disconnectAndStop();" not in service:
        raise SystemExit("Mobile Data handover stop dispatch missing")
    scan_only = tracker[tracker.index("public synchronized void setScanOnlyMode"):
                        tracker.index("public synchronized void setBluetoothScanMode")]
    for needle in ("setScanResultHandlingCommand", "disconnectCommand()", "reconnectCommand()"):
        if needle not in scan_only:
            raise SystemExit(f"scan-only fallback path lost: {needle}")
    print("test_wifi_station_scan_guard: PASS")


if __name__ == "__main__":
    main()
