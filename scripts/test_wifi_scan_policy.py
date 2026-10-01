#!/usr/bin/env python3
"""Regression checks for manual/automatic Settings scan separation."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/settings/src/com/android/settings/wifi")


def main() -> None:
    layer = (ROOT / "WifiLayer.java").read_text()
    settings = (ROOT / "WifiSettings.java").read_text()
    assert "N3DS_WIFI_30S_DISCONNECTED_AUTO_SCAN" in layer
    assert "CONTINUOUS_SCAN_DELAY_MS = 30000" in layer
    assert "if (!mIsObtainingAddress && !mIsConnected)" in layer
    assert "if (mIsConnected || mIsObtainingAddress || !isWifiEnabled())" in layer
    assert "long remaining = CONTINUOUS_SCAN_DELAY_MS - (now - mLastAutoScanStart)" in layer
    assert "case MESSAGE_ATTEMPT_SCAN:\n                    attemptAutoScan();" in layer
    assert "mIsConnected = info.isConnected();" in layer
    assert "N3DS_WIFI_AUTO_SCAN start interval=" in layer
    assert "mWifiLayer.attemptScan();" in settings
    print("wifi_scan_policy: PASS")


if __name__ == "__main__":
    main()
