#!/usr/bin/env python3
"""Static contract for Wi-Fi-backed 3DSTelco Settings and Phone ownership."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "content/settings/src/com/android/settings/MobileDataSettings.java"
MANIFEST = ROOT / "content/settings/AndroidManifest.xml"
SCREEN = ROOT / "content/settings/res/xml/settings.xml"
PHONE = ROOT / "content/stock-app-overlays/Phone/src/com/android/phone"
BUILD = ROOT / "scripts/build_settings_app.sh"
PIPELINE = ROOT / "scripts/rebuild_everything.sh"


def require(text: str, needle: str, label: str) -> None:
    assert needle in text, f"{label}: missing {needle!r}"


def main() -> None:
    java = JAVA.read_text(encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    screen = SCREEN.read_text(encoding="utf-8")
    phone = "\n".join(path.read_text(encoding="utf-8") for path in PHONE.glob("*.java"))
    build = BUILD.read_text(encoding="utf-8")
    pipeline = PIPELINE.read_text(encoding="utf-8")

    for marker in (
        "class MobileDataSettings",
        'setTitle("3DSTelco Mobile Data")',
        'DEFAULT_ENDPOINT = "https://3dstelco.divergen.io"',
        'KEY_ENABLED = "n3ds_telco_enabled"',
        'KEY_ENDPOINT = "n3ds_telco_endpoint"',
        'content://io.divergen.telco/status',
        'ACTION_CONFIG_CHANGED = "io.divergen.telco.action.CONFIG_CHANGED"',
        'ACTION_ENROLL = "io.divergen.telco.action.ENROLL"',
        'ACTION_POLL = "io.divergen.telco.action.POLL"',
        'Settings.System.putInt',
        'Settings.System.putString',
        'setClassName(PHONE_PACKAGE, PHONE_SERVICE)',
        'getNetworkInfo(ConnectivityManager.TYPE_WIFI)',
        'wifi != null && wifi.isConnected()',
        '"https".equalsIgnoreCase(uri.getScheme())',
        'uri.getUserInfo() != null',
        'uri.getQuery() != null',
        'uri.getFragment() != null',
        'mCode.setPersistent(false)',
        'mCode.setText("")',
        '"[A-Z0-9]{8,80}"',
        'normalizeProvisioningCode',
        'endpoint_changed',
        'registerReceiver(mStateReceiver',
        'unregisterReceiver(mStateReceiver)',
        'Original Phone service is unavailable',
        'this does not create an access point',
    ):
        require(java, marker, "MobileDataSettings")

    for forbidden in (
        "SharedPreferences",
        "SystemProperties",
        "LocalSocket",
        "service.mobiledata.",
        "sys.mobiledata.",
        "Starting AP",
        "AP active",
        "WPA2",
        "SSID",
        "ADB over Data",
    ):
        assert forbidden not in java, f"retired AP implementation remains: {forbidden}"

    require(manifest, 'android:name="io.divergen.telco.ACCESS"', "Settings signature permission")
    require(manifest, 'android:name=".MobileDataSettings"', "Settings activity")
    require(screen, 'android:title="3DSTelco Mobile Data"', "Settings entry")
    require(screen, 'android:summary="Configure an HTTPS calling and messaging server over Wi-Fi"', "Settings entry")
    require((ROOT / "content/settings/src/com/android/settings/Settings.java").read_text(encoding="utf-8"),
            "N3DS_TELCO_SETTINGS_V2", "Settings runtime identity marker")
    assert "local AP" not in screen and "ADB over Data" not in screen

    # Settings and Phone must agree exactly, and credentials must be endpoint-bound.
    for marker in (
        'KEY_ENABLED = "n3ds_telco_enabled"',
        'KEY_ENDPOINT = "n3ds_telco_endpoint"',
        'ACTION_CONFIG_CHANGED = "io.divergen.telco.action.CONFIG_CHANGED"',
        'getBooleanExtra("endpoint_changed", false)',
        '.putString("endpoint", endpoint)',
        'TelcoContract.endpoint(context).equals(credentialEndpoint)',
        "cancelSchedule()",
    ):
        require(phone, marker, "original Phone contract")

    require(build, "MobileDataSettings.java", "Settings build overlay")
    require(pipeline, "run test_mobile_data_settings.py", "build pipeline")
    assert pipeline.index("run test_mobile_data_settings.py") < pipeline.index("run build_settings_app.sh")
    print("mobile_data_settings: PASS")


if __name__ == "__main__":
    main()
