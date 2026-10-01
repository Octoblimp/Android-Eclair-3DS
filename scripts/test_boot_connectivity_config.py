#!/usr/bin/env python3
"""Focused source contract for file-controlled connectivity boot behavior."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREFS = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/android_prefs_init.sh"
WIFI_SERVICE = ROOT / "third_party/frameworks/base/services/java/com/android/server/WifiService.java"
WIFI_PATCH = ROOT / "scripts/patch_wifi_manual_boot_enable.py"
TELCO = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone/TelcoService.java"
TELCO_BOOT = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone/TelcoBootReceiver.java"
PHONE_TELCO_CONFIG = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone/TelcoConfig.java"
TELCO_PATCH = ROOT / "scripts/patch_telco_service.py"
STOCK_PATCH = ROOT / "scripts/patch_telco_stock_apps.py"
LEGACY_PREFS_ENTRY = ROOT / "scripts/patch_prefs.py"
PIPELINE = ROOT / "scripts/rebuild_everything.sh"


def require(text: str, needle: str, label: str) -> None:
    assert needle in text, f"{label}: missing {needle!r}"


def main() -> None:
    prefs = PREFS.read_text(encoding="utf-8")
    wifi = WIFI_SERVICE.read_text(encoding="utf-8")
    wifi_patch = WIFI_PATCH.read_text(encoding="utf-8")
    telco = TELCO.read_text(encoding="utf-8")
    telco_boot = TELCO_BOOT.read_text(encoding="utf-8")
    phone_telco_config = PHONE_TELCO_CONFIG.read_text(encoding="utf-8")
    telco_patch = TELCO_PATCH.read_text(encoding="utf-8")
    stock_patch = STOCK_PATCH.read_text(encoding="utf-8")
    legacy_prefs_entry = LEGACY_PREFS_ENTRY.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")

    require(prefs, "N3DS_WIFI_FILE_BOOT_POLICY", "preference initializer")
    require(prefs, "write_runtime_wifi", "supplicant sanitizer")
    require(prefs, "sync_runtime_wifi", "supplicant sync")
    require(prefs, "wifi_on_boot", "Wi-Fi boot toggle")
    assert 'atomic_copy "$PERSIST_WIFI" "$RUNTIME_WIFI"' not in prefs
    assert "sqlite3" not in prefs

    require(wifi, "N3DS_WIFI_FILE_BOOT_ENABLE", "WifiService")
    require(wifi, "/sdcard/persistent/shared/wpa_supplicant.conf", "WifiService path")
    require(wifi, '"wifi_on_boot=1"', "WifiService enabled value")
    require(wifi, '"wifi_on_boot=0"', "WifiService disabled value")
    assert "N3DS_WIFI_MANUAL_BOOT_ENABLE" not in wifi
    require(wifi_patch, "N3DS_WIFI_FILE_BOOT_ENABLE", "Wi-Fi patcher")
    require(pipeline, "run patch_wifi_manual_boot_enable.py", "release pipeline")

    canonical_mobile = "/sdcard/persistent/shared/mobile_registration.conf"
    require(telco, canonical_mobile, "TelcoService")
    require(telco, "readDeviceMac", "MAC discovery")
    require(telco, "Waiting for Wi-Fi hardware", "transient MAC handling")
    assert "/sdcard/linux/mobile_registration.conf" not in telco
    assert "/sdcard/linux/android/persistent" not in telco
    require(telco_patch, canonical_mobile, "TelcoService generator")
    assert "if (TelcoContract.enabled(context))" not in telco_boot
    require(telco_boot, "ACTION_CONFIG_CHANGED", "Telco boot configuration")
    require(telco_boot, "N3DS_TELCO_BOOT_RECEIVER_GUARD", "Telco boot guard")
    require(telco, "restoreFromConfig", "durable registration rehydrate")
    require(phone_telco_config, "N3DS_TELCO_DURABLE_REGISTRATION_READY", "durable registration file")

    require(stock_patch, "N3DS_MMS_MISSING_PROVIDER_GUARD", "Messages patcher")
    require(legacy_prefs_entry, "patch_update_safe_prefs.py", "safe legacy preferences entry")
    assert "sqlite3" not in legacy_prefs_entry
    require(pipeline, "run build_telco_release_apps.sh", "release app pipeline")
    print("boot_connectivity_config: PASS")


if __name__ == "__main__":
    main()
