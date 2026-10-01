#!/usr/bin/env python3
"""Throttle Settings auto scans while preserving an explicit manual Scan."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
PATHS = (
    Path(f"{A3DS_ROOT}/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"),
)
MARKER = "N3DS_WIFI_30S_DISCONNECTED_AUTO_SCAN"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text()
    if MARKER in text:
        if "N3DS_WIFI_AUTO_SCAN start interval=" not in text:
            text = replace_once(
                text,
                """        mLastAutoScanStart = now;
        attemptScan();
""",
                """        mLastAutoScanStart = now;
        Log.i(TAG, "N3DS_WIFI_AUTO_SCAN start interval="
                + CONTINUOUS_SCAN_DELAY_MS);
        attemptScan();
""",
                "automatic scan diagnostic",
            )
            path.write_text(text)
        return

    text = replace_once(
        text,
        "import android.os.Message;\n",
        "import android.os.Message;\nimport android.os.SystemClock;\n",
        "SystemClock import",
    )
    text = replace_once(
        text,
        "    private static final int CONTINUOUS_SCAN_DELAY_MS = 6000; \n",
        """    /* N3DS_WIFI_30S_DISCONNECTED_AUTO_SCAN: AR6014 scans are expensive.
     * This delay applies only to automatic disconnected refreshes; the menu's
     * explicit Scan command remains immediate. */
    private static final int CONTINUOUS_SCAN_DELAY_MS = 30000;
""",
        "continuous scan interval",
    )
    text = replace_once(
        text,
        "    private boolean mIsObtainingAddress;\n",
        """    private boolean mIsObtainingAddress;
    private boolean mIsConnected;
    private long mLastAutoScanStart;
""",
        "scan state fields",
    )
    old_resume = """        if (isWifiEnabled()) {
            // Kick start the continual scan
            queueContinuousScan();
        }
"""
    new_resume = """        if (isWifiEnabled()) {
            WifiInfo info = mWifiManager.getConnectionInfo();
            mIsConnected = info != null &&
                    info.getSupplicantState() == SupplicantState.COMPLETED;
            // Resume automatic refresh only while disconnected.
            queueContinuousScan();
        }
"""
    text = replace_once(text, old_resume, new_resume, "resume connection state")

    queue = """    private void queueContinuousScan() {
        mHandler.removeMessages(MESSAGE_ATTEMPT_SCAN);
        
        if (!mIsObtainingAddress) {
            // Don't do continuous scan while in obtaining IP state
            mHandler.sendEmptyMessageDelayed(MESSAGE_ATTEMPT_SCAN, CONTINUOUS_SCAN_DELAY_MS);
        }
    }
"""
    replacement = """    private void queueContinuousScan() {
        mHandler.removeMessages(MESSAGE_ATTEMPT_SCAN);

        // Never auto-scan an active connection. Manual attemptScan() remains
        // available from the Scan menu and deliberately bypasses this gate.
        if (!mIsObtainingAddress && !mIsConnected) {
            mHandler.sendEmptyMessageDelayed(MESSAGE_ATTEMPT_SCAN,
                    CONTINUOUS_SCAN_DELAY_MS);
        }
    }

    private void attemptAutoScan() {
        if (mIsConnected || mIsObtainingAddress || !isWifiEnabled()) {
            removeFutureScans();
            return;
        }
        long now = SystemClock.elapsedRealtime();
        long remaining = CONTINUOUS_SCAN_DELAY_MS - (now - mLastAutoScanStart);
        if (mLastAutoScanStart != 0 && remaining > 0) {
            mHandler.removeMessages(MESSAGE_ATTEMPT_SCAN);
            mHandler.sendEmptyMessageDelayed(MESSAGE_ATTEMPT_SCAN, remaining);
            return;
        }
        mLastAutoScanStart = now;
        Log.i(TAG, "N3DS_WIFI_AUTO_SCAN start interval="
                + CONTINUOUS_SCAN_DELAY_MS);
        attemptScan();
    }
"""
    text = replace_once(text, queue, replacement, "automatic scan gate")

    text = replace_once(
        text,
        """        handleDisablingScanWhileObtainingAddress(detailedState);
        
        // This will update the AP with its new info
""",
        """        mIsConnected = info.isConnected();
        handleDisablingScanWhileObtainingAddress(detailedState);

        // This will update the AP with its new info
""",
        "network connected tracking",
    )

    # Convert the three internal automatic call sites, leaving the public menu
    # call in WifiSettings.java pointed at immediate attemptScan().
    text = replace_once(
        text,
        """        if (attemptScan) {
            attemptScan();
        }
""",
        """        if (attemptScan) {
            attemptAutoScan();
        }
""",
        "refresh auto scan",
    )
    text = replace_once(
        text,
        """        if (wifiState == WIFI_STATE_ENABLED) {
            loadConfiguredAccessPoints();
            attemptScan();
""",
        """        if (wifiState == WIFI_STATE_ENABLED) {
            loadConfiguredAccessPoints();
            mIsConnected = false;
            attemptAutoScan();
""",
        "enable auto scan",
    )
    text = replace_once(
        text,
        """                case MESSAGE_ATTEMPT_SCAN:
                    attemptScan();
                    break;
""",
        """                case MESSAGE_ATTEMPT_SCAN:
                    attemptAutoScan();
                    break;
""",
        "handler auto scan",
    )
    path.write_text(text)


def main() -> None:
    found = False
    for path in PATHS:
        if path.is_file():
            found = True
            patch(path)
    if not found:
        raise SystemExit("no Settings WifiLayer source found")
    print("patch_wifi_scan_policy: 30-second disconnected auto scans installed")


if __name__ == "__main__":
    main()
