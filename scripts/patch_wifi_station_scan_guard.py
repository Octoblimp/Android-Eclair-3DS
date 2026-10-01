#!/usr/bin/env python3
"""Keep framework scan policy in station mode during association."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
JNI = ROOT / "third_party/frameworks/base/core/jni/android_net_wifi_Wifi.cpp"
SERVICE = ROOT / "third_party/frameworks/base/services/java/com/android/server/WifiService.java"
MARKER = "N3DS_WIFI_STATION_SCAN_OWNERSHIP"


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_jni(text: str) -> str:
    if MARKER in text:
        return text
    old = """static jboolean android_net_wifi_setScanResultHandlingCommand(JNIEnv* env, jobject clazz, jint mode)
{
    char cmdstr[256];

    int numWritten = snprintf(cmdstr, sizeof(cmdstr), "AP_SCAN %d", mode);
    int cmdTooLong = numWritten >= (int)sizeof(cmdstr);

    return (jboolean)!cmdTooLong && doBooleanCommand(cmdstr, "OK");
}
"""
    new = """static jboolean android_net_wifi_setScanResultHandlingCommand(JNIEnv* env, jobject clazz, jint mode)
{
    char cmdstr[256];

    /* N3DS_WIFI_STATION_SCAN_OWNERSHIP: nl80211 on the legacy AR6014
     * target does not support wpa_supplicant ap_scan=2.  Framework callers
     * historically requested mode 2 for list-only scans, including while an
     * association was active.  Keep the control boundary station-safe. */
    mode = 1;
    int numWritten = snprintf(cmdstr, sizeof(cmdstr), "AP_SCAN %d", mode);
    int cmdTooLong = numWritten >= (int)sizeof(cmdstr);

    return (jboolean)!cmdTooLong && doBooleanCommand(cmdstr, "OK");
}
"""
    return once(text, old, new, "JNI scan-policy writer")


def patch_service(text: str) -> str:
    if MARKER in text:
        return text
    old = """            switch (mWifiStateTracker.getSupplicantState()) {
                case DISCONNECTED:
                case INACTIVE:
                case SCANNING:
                case DORMANT:
                    break;
                default:
                    WifiNative.setScanResultHandlingCommand(
                            WifiStateTracker.SUPPL_SCAN_HANDLING_LIST_ONLY);
                    break;
            }
            return WifiNative.scanCommand(forceActive);
"""
    new = """            switch (mWifiStateTracker.getSupplicantState()) {
                case DISCONNECTED:
                case INACTIVE:
                case SCANNING:
                case DORMANT:
                    break;
                case ASSOCIATING:
                case ASSOCIATED:
                case FOUR_WAY_HANDSHAKE:
                case GROUP_HANDSHAKE:
                    /* N3DS_WIFI_STATION_SCAN_OWNERSHIP: do not issue a
                     * scan while association/EAPOL owns the station.  The
                     * old list-only path wrote AP_SCAN=2 and dropped wlan0
                     * on this target. Settings will retry after state change. */
                    return false;
                default:
                    /* Keep nl80211 in its normal AP_SCAN=1 station mode. */
                    break;
            }
            return WifiNative.scanCommand(forceActive);
"""
    return once(text, old, new, "WifiService scan gate")


def main() -> None:
    if not JNI.is_file() or not SERVICE.is_file():
        raise SystemExit(f"missing canonical Wi-Fi sources: {JNI} / {SERVICE}")
    jni = JNI.read_text()
    service = SERVICE.read_text()
    updated_jni = patch_jni(jni)
    updated_service = patch_service(service)
    if updated_jni != jni:
        JNI.write_text(updated_jni)
    if updated_service != service:
        SERVICE.write_text(updated_service)
    if updated_jni != jni or updated_service != service:
        print("patch_wifi_station_scan_guard: station-safe scan ownership installed")
    else:
        print("patch_wifi_station_scan_guard: already applied")


if __name__ == "__main__":
    main()
