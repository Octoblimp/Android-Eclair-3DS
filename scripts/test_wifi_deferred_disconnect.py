#!/usr/bin/env python3
"""Focused source contract for the remembered-association timer race."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

SOURCE = Path(f"{A3DS_ROOT}/third_party/frameworks/base/wifi/java/android/net/wifi/WifiStateTracker.java")
MARKER = "N3DS_WIFI_DEFERRED_DISCONNECT_GUARD"
STATE_GATE_MARKER = "N3DS_WIFI_DEFERRED_DISCONNECT_STATE_GATE"
DHCP_RETRY_MARKER = "N3DS_WIFI_DHCP_RECONNECT_AFTER_TIMEOUT"
REQUIRED = (
    "n3dsAssociationInProgress",
    "n3dsDeferredDisconnectAllowed",
    "n3dsCancelStaleDisconnect(newState)",
    "mDisconnectPending &&",
    "handleDisconnectedState(DetailedState.DISCONNECTED);",
    "mDisconnectExpected = true;",
    "sendEmptyMessageDelayed(EVENT_DEFERRED_RECONNECT,",
    "mRunState == RUN_STATE_RUNNING && !mIsScanOnly",
)


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"missing canonical framework source: {SOURCE}")
    text = SOURCE.read_text()
    if MARKER not in text or STATE_GATE_MARKER not in text:
        raise SystemExit("deferred disconnect guard marker missing")
    if DHCP_RETRY_MARKER not in text:
        raise SystemExit("DHCP timeout reconnect marker missing")
    for needle in REQUIRED:
        if needle not in text:
            raise SystemExit(f"deferred disconnect guard missing: {needle}")
    if "SupplicantState.AUTHENTICATING" in text:
        raise SystemExit("target enum does not define AUTHENTICATING")

    call = text.index("n3dsCancelStaleDisconnect(newState)")
    timer = text.index("case EVENT_DEFERRED_DISCONNECT:")
    guard = text.index("if (mDisconnectPending &&", timer)
    state_gate = text.index("n3dsDeferredDisconnectAllowed(deferredState)", timer)
    helper = text.index("private static boolean n3dsAssociationInProgress")
    if not call < timer < guard < state_gate:
        raise SystemExit("guard ordering does not protect the deferred timer")
    success = text.index("case EVENT_INTERFACE_CONFIGURATION_SUCCEEDED:")
    failure = text.index("case EVENT_INTERFACE_CONFIGURATION_FAILED:")
    retry = text.index(DHCP_RETRY_MARKER, failure)
    reconnect = text.index("case EVENT_DEFERRED_RECONNECT:")
    if not reconnect < success < failure < retry:
        raise SystemExit("DHCP timeout retry ordering is not localized to failure")
    failure_end = text.index("case EVENT_DRIVER_STATE_CHANGED:", failure)
    failure_block = text[failure:failure_end]
    for needle in ("mDisconnectExpected = true;",
                   "WifiNative.disconnectCommand();",
                   "sendEmptyMessageDelayed(EVENT_DEFERRED_RECONNECT,",
                   "mLastNetworkId != -1"):
        if needle not in failure_block:
            raise SystemExit(f"DHCP timeout retry missing: {needle}")
    reconnect_block = text[reconnect:success]
    if "mRunState == RUN_STATE_RUNNING" not in reconnect_block:
        raise SystemExit("DHCP retry is not guarded by the Wi-Fi run state")
    allowed = text[text.index("private static boolean n3dsDeferredDisconnectAllowed"):
                   text.index("private boolean wifiManagerDisableNetwork")]
    for state in ("SupplicantState.DISCONNECTED", "SupplicantState.INACTIVE"):
        if state not in allowed:
            raise SystemExit(f"deferred timer gate lost safe state: {state}")
    # Explicit Wi-Fi off and Mobile Data handover use disconnectAndStop and
    # must retain their normal stop path; the stale association guard must not
    # replace or bypass it.
    stop = text[text.index("public synchronized boolean disconnectAndStop"):
               text.index("public synchronized boolean restart")]
    if "mRunState = RUN_STATE_STOPPING" not in stop or "WifiNative.disconnectCommand()" not in stop:
        raise SystemExit("intentional stop/handover path was altered")

    print("test_wifi_deferred_disconnect: PASS")


if __name__ == "__main__":
    main()
