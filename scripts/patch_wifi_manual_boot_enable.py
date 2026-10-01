#!/usr/bin/env python3
"""Install the file-controlled Wi-Fi boot policy in every source mirror."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
REL = Path("third_party/frameworks/base/services/java/com/android/server/WifiService.java")
TARGETS = [HERE / REL, Path(A3DS_ROOT) / REL]
MARKER = "N3DS_WIFI_FILE_BOOT_ENABLE"

LEGACY = """        // N3DS_WIFI_MANUAL_BOOT_ENABLE: a failed experimental scan leaves
        // WIFI_ON persisted. Start radio-off and require an explicit Settings
        // toggle after Android reaches HOME.
        if (wifiEnabled) {
            Log.w(TAG, "Deferring persisted Wi-Fi enable until an explicit user toggle");
            persistWifiEnabled(false);
            wifiEnabled = false;
        }
"""

OLD = """    private boolean getPersistedWifiEnabled() {
        final ContentResolver cr = mContext.getContentResolver();
"""

NEW = """    private boolean getPersistedWifiEnabled() {
        // N3DS_WIFI_FILE_BOOT_ENABLE: /sdcard is the bind-mounted
        // linux/android payload.  The project-owned toggle is read here rather
        // than passed to wpa_supplicant (where it would be a fatal unknown
        // directive).  A missing or malformed value falls back to Android's
        // normal persisted setting.
        int fileSetting = getFileWifiEnabled();
        if (fileSetting >= 0) {
            return fileSetting == 1;
        }
        final ContentResolver cr = mContext.getContentResolver();
"""

METHOD_ANCHOR = """    private void persistWifiEnabled(boolean enabled) {
"""

METHOD = """    private int getFileWifiEnabled() {
        java.io.File config = new java.io.File(
                "/sdcard/persistent/shared/wpa_supplicant.conf");
        if (!config.isFile()) return -1;
        java.io.BufferedReader reader = null;
        try {
            reader = new java.io.BufferedReader(new java.io.FileReader(config));
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if ("wifi_on_boot=1".equals(line)) return 1;
                if ("wifi_on_boot=0".equals(line)) return 0;
            }
        } catch (java.io.IOException e) {
            Log.w(TAG, "Unable to read Wi-Fi boot policy; using Android setting");
        } finally {
            if (reader != null) {
                try { reader.close(); } catch (java.io.IOException ignored) { }
            }
        }
        return -1;
    }

"""


def patch(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace(LEGACY, "")
    legacy_marker = "        // N3DS_WIFI_MANUAL_BOOT_ENABLE:"
    if legacy_marker in text:
        start = text.index(legacy_marker)
        end_marker = "        mAlarmManager ="
        end = text.find(end_marker, start)
        if end < 0:
            raise SystemExit(f"legacy Wi-Fi guard end anchor missing: {path}")
        text = text[:start] + text[end:]
    if MARKER not in text:
        if text.count(OLD) != 1:
            raise SystemExit(f"Wi-Fi boot-policy anchor mismatch: {path}")
        text = text.replace(OLD, NEW, 1)
        if text.count(METHOD_ANCHOR) != 1:
            raise SystemExit(f"Wi-Fi helper anchor mismatch: {path}")
        text = text.replace(METHOD_ANCHOR, METHOD + METHOD_ANCHOR, 1)
    if "N3DS_WIFI_MANUAL_BOOT_ENABLE" in text:
        raise SystemExit(f"legacy manual-only Wi-Fi policy remains: {path}")
    path.write_text(text, encoding="utf-8")
    print(f"patch_wifi_manual_boot_enable: file boot policy ready in {path}")


for target in dict.fromkeys(TARGETS):
    patch(target)

if not any(target.is_file() for target in TARGETS):
    raise SystemExit("patch_wifi_manual_boot_enable: no WifiService source found")
