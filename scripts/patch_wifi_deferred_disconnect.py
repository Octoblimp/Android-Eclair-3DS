#!/usr/bin/env python3
"""Keep stale legacy Wi-Fi disconnect cleanup from taking down a retry."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
SOURCE = ROOT / "third_party/frameworks/base/wifi/java/android/net/wifi/WifiStateTracker.java"
MARKER = "N3DS_WIFI_DEFERRED_DISCONNECT_GUARD"
STATE_GATE_MARKER = "N3DS_WIFI_DEFERRED_DISCONNECT_STATE_GATE"
DHCP_RETRY_MARKER = "N3DS_WIFI_DHCP_RECONNECT_AFTER_TIMEOUT"


def once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def install_original_guard(text: str) -> str:
    helper_anchor = """    private boolean wifiManagerDisableNetwork(int networkId) {
"""
    helper = """    /* N3DS_WIFI_DEFERRED_DISCONNECT_GUARD: a failed BSSID can leave
     * the five-second disconnect timer pending while wpa_supplicant retries a
     * different BSSID in the same remembered ESS.  A pending timer must not
     * disable wlan0 underneath that replacement association. */
    private static boolean n3dsAssociationInProgress(SupplicantState state) {
        return state == SupplicantState.ASSOCIATING ||
                state == SupplicantState.ASSOCIATED ||
                state == SupplicantState.FOUR_WAY_HANDSHAKE ||
                state == SupplicantState.GROUP_HANDSHAKE;
    }

    private void n3dsCancelStaleDisconnect(SupplicantState state) {
        if (mDisconnectPending && n3dsAssociationInProgress(state)) {
            if (LOCAL_LOGD) {
                Log.d(TAG, "N3DS: cancel stale deferred disconnect during " + state);
            }
            cancelDisconnect();
        }
    }

"""
    text = once(text, helper_anchor, helper + helper_anchor,
                "tracker helper anchor")

    state_anchor = """                mPasswordKeyMayBeIncorrect = false;

                /*
                 * Keep track of the supplicant state and check if we should
"""
    state_replacement = """                mPasswordKeyMayBeIncorrect = false;

                /*
                 * A new association attempt supersedes the previous BSSID's
                 * deferred cleanup.  Cancel before the timer can call
                 * resetInterface()/disableInterface() on the active retry.
                 */
                n3dsCancelStaleDisconnect(newState);

                /*
                 * Keep track of the supplicant state and check if we should
"""
    text = once(text, state_anchor, state_replacement,
                "supplicant state cancellation")

    timer_anchor = """            case EVENT_DEFERRED_DISCONNECT:
                if (mWifiInfo.getSupplicantState() != SupplicantState.UNINITIALIZED) {
                    handleDisconnectedState(DetailedState.DISCONNECTED);
                }
                break;
"""
    timer_replacement = """            case EVENT_DEFERRED_DISCONNECT:
                /*
                 * The message can already be dequeued when a replacement
                 * association cancels it.  Never run stale cleanup after that
                 * cancellation; doing so disables wlan0 during association.
                 */
                if (mDisconnectPending &&
                        mWifiInfo.getSupplicantState() != SupplicantState.UNINITIALIZED) {
                    handleDisconnectedState(DetailedState.DISCONNECTED);
                }
                break;
"""
    return once(text, timer_anchor, timer_replacement,
                "deferred timer guard")


def install_state_gate(text: str) -> str:
    if STATE_GATE_MARKER in text:
        return text.replace(
            "                state == SupplicantState.AUTHENTICATING ||\n", "", 1
        )

    if MARKER not in text:
        text = install_original_guard(text)

    helper_anchor = """    private static boolean n3dsAssociationInProgress(SupplicantState state) {
        return state == SupplicantState.ASSOCIATING ||
                state == SupplicantState.ASSOCIATED ||
                state == SupplicantState.FOUR_WAY_HANDSHAKE ||
                state == SupplicantState.GROUP_HANDSHAKE;
    }

"""
    helper = helper_anchor + """    private static boolean n3dsDeferredDisconnectAllowed(SupplicantState state) {
        return state == SupplicantState.DISCONNECTED ||
                state == SupplicantState.INACTIVE;
    }

"""
    text = once(text, helper_anchor, helper,
                "state-gated deferred helper anchor")

    old_timer = """            case EVENT_DEFERRED_DISCONNECT:
                /*
                 * The message can already be dequeued when a replacement
                 * association cancels it.  Never run stale cleanup after that
                 * cancellation; doing so disables wlan0 during association.
                 */
                if (mDisconnectPending &&
                        mWifiInfo.getSupplicantState() != SupplicantState.UNINITIALIZED) {
                    handleDisconnectedState(DetailedState.DISCONNECTED);
                }
                break;
"""
    new_timer = """            case EVENT_DEFERRED_DISCONNECT:
                /*
                 * N3DS_WIFI_DEFERRED_DISCONNECT_STATE_GATE: a timer message
                 * can race the queued ASSOCIATING event.  Only perform the
                 * delayed reset while the tracker is still disconnected; any
                 * transition or active state belongs to the new station
                 * attempt and must retain wlan0.
                 */
                SupplicantState deferredState = mWifiInfo.getSupplicantState();
                if (mDisconnectPending &&
                        n3dsDeferredDisconnectAllowed(deferredState)) {
                    handleDisconnectedState(DetailedState.DISCONNECTED);
                } else if (mDisconnectPending &&
                        deferredState != SupplicantState.UNINITIALIZED) {
                    if (LOCAL_LOGD) {
                        Log.d(TAG, "N3DS: cancel stale deferred disconnect in "
                                + deferredState);
                    }
                    cancelDisconnect();
                }
                break;
"""
    return once(text, old_timer, new_timer,
                "state-gated deferred timer")


def install_dhcp_failure_retry(text: str) -> str:
    """Reconnect after a DHCP timeout when supplicant reports plain DISCONNECTED.

    Eclair's original tracker only queues EVENT_DEFERRED_RECONNECT from the
    DORMANT supplicant state. A local WifiNative.disconnectCommand() issued
    after NetworkUtils.runDhcp() times out normally produces DISCONNECTED
    instead, leaving the remembered network parked forever. Keep the
    intentional disconnect (so DHCP and the interface are cleaned up), but
    queue the existing bounded reconnect path explicitly. The run-state gate
    prevents a retry queued just before Wi-Fi-off from turning the radio back
    on after the user has stopped it.
    """
    if DHCP_RETRY_MARKER in text:
        return text

    success_anchor = """                mReconnectCount = 0;
                mHaveIpAddress = true;
"""
    success_replacement = """                /* N3DS_WIFI_DHCP_RECONNECT_AFTER_TIMEOUT:
                 * a successful lease supersedes any stale retry left by an
                 * earlier timeout. */
                removeMessages(EVENT_DEFERRED_RECONNECT);
                mReconnectCount = 0;
                mHaveIpAddress = true;
"""
    text = once(text, success_anchor, success_replacement,
                "DHCP success retry cancellation")

    failure_anchor = """            case EVENT_INTERFACE_CONFIGURATION_FAILED:
                if (mWifiInfo.getSupplicantState() != SupplicantState.UNINITIALIZED) {
                    // Wi-Fi interface configuration state changed:
                    // [31- 1] Reserved for future use
                    // [ 0- 0] Interface configuration succeeded (1) or failed (0)
                    EventLog.writeEvent(EVENTLOG_INTERFACE_CONFIGURATION_STATE_CHANGED, 0);
                
                    mHaveIpAddress = false;
                    mWifiInfo.setIpAddress(0);
                    mObtainingIpAddress = false;
                    synchronized(this) {
                        WifiNative.disconnectCommand();
                    }
                }
                break;
"""
    failure_replacement = """            case EVENT_INTERFACE_CONFIGURATION_FAILED:
                if (mWifiInfo.getSupplicantState() != SupplicantState.UNINITIALIZED) {
                    // Wi-Fi interface configuration state changed:
                    // [31- 1] Reserved for future use
                    // [ 0- 0] Interface configuration succeeded (1) or failed (0)
                    EventLog.writeEvent(EVENTLOG_INTERFACE_CONFIGURATION_STATE_CHANGED, 0);
                
                    mHaveIpAddress = false;
                    mWifiInfo.setIpAddress(0);
                    mObtainingIpAddress = false;

                    /* N3DS_WIFI_DHCP_RECONNECT_AFTER_TIMEOUT: runDhcp() has
                     * already waited for its bounded result timeout. The
                     * legacy failure path disconnects, but only schedules a
                     * reconnect for DORMANT; this driver reports a plain
                     * DISCONNECTED event, so a remembered network otherwise
                     * remains parked forever after one failed lease. */
                    mDisconnectExpected = true;
                    removeMessages(EVENT_DEFERRED_RECONNECT);
                    synchronized(this) {
                        WifiNative.disconnectCommand();
                    }
                    if (mRunState == RUN_STATE_RUNNING && !mIsScanOnly &&
                            mLastNetworkId != -1) {
                        sendEmptyMessageDelayed(EVENT_DEFERRED_RECONNECT,
                                RECONNECT_DELAY_MSECS);
                    }
                }
                break;
"""
    text = once(text, failure_anchor, failure_replacement,
                "DHCP failure reconnect")

    reconnect_anchor = """            case EVENT_DEFERRED_RECONNECT:
                /*
                 * If we've exceeded the maximum number of retries for reconnecting
                 * to a given network, disable the network so that the supplicant
                 * will try some other network, if any is available.
                 * TODO: network ID may have changed since we stored it.
                 */
                if (mWifiInfo.getSupplicantState() != SupplicantState.UNINITIALIZED) {
"""
    reconnect_replacement = """            case EVENT_DEFERRED_RECONNECT:
                /*
                 * If we've exceeded the maximum number of retries for reconnecting
                 * to a given network, disable the network so that the supplicant
                 * will try some other network, if any is available.
                 * TODO: network ID may have changed since we stored it.
                 */
                /* A DHCP retry must never resurrect an explicit Wi-Fi stop. */
                if (mRunState == RUN_STATE_RUNNING && !mIsScanOnly &&
                        mWifiInfo.getSupplicantState() != SupplicantState.UNINITIALIZED) {
"""
    return once(text, reconnect_anchor, reconnect_replacement,
                "DHCP retry run-state gate")


def patch(text: str) -> str:
    # Keep this hook safe for both untouched source and the already guarded
    # source in the current canonical WSL tree.
    text = install_state_gate(text)
    return install_dhcp_failure_retry(text)


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"missing canonical framework source: {SOURCE}")
    original = SOURCE.read_text()
    updated = patch(original)
    if updated != original:
        SOURCE.write_text(updated)
        print("patch_wifi_deferred_disconnect: state-gated retry teardown guard installed")
    else:
        print("patch_wifi_deferred_disconnect: already applied")


if __name__ == "__main__":
    main()
