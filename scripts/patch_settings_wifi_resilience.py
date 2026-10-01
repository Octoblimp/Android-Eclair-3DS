#!/usr/bin/env python3
"""Guard Settings Wi-Fi callbacks while preserving credential privacy."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
SOURCE = ROOT / "third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
MARKER = "N3DS_SETTINGS_WIFI_CALLBACK_GUARD"
REMEMBERED_MARKER = "N3DS_SETTINGS_REMEMBERED_UNSEEN_VISIBILITY"
CONNECT_GUARD_MARKER = "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE"
SAVE_GUARD_MARKER = "N3DS_SETTINGS_UNKNOWN_SAVE_REJECTED"
MANUAL_RETRY_MARKER = "N3DS_SETTINGS_MANUAL_REASSOCIATE_V2"
PRIORITY_GUARD_MARKER = "N3DS_SETTINGS_PRIORITY_FAILURE_GUARD"


def once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError(f"{label}: expected one match, found {text.count(old)}")
    return text.replace(old, new, 1)


def wrap_method(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    end = None
    for pos in range(brace, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                end = pos
                break
    if end is None:
        raise RuntimeError("unclosed method: " + signature)
    body = text[brace + 1:end]
    wrapped = ("{\n        String action = null;\n"
               "            /* " + MARKER + ": a framework restart can deliver a\n"
               "             * partial Wi-Fi broadcast. Keep transient binder/null\n"
               "             * races from killing Settings; log only action/type. */\n"
               "            try {" + body + "\n"
               "            } catch (RuntimeException e) {\n"
               "                Log.e(TAG, \"N3DS_SETTINGS_WIFI_CALLBACK_FAILED action=\"\n"
               "                        + action + \" type=\" + e.getClass().getName());\n"
               "            }\n        }")
    return text[:brace] + wrapped + text[end + 1:]


def _patch_base(text):
    text = wrap_method(text, "public void onReceive(Context context, Intent intent)")
    text = once(
        text,
        "final String action = intent.getAction();",
        "action = intent == null ? null : intent.getAction();\n"
        "            if (action == null) return;",
        "receiver null action",
    )
    text = once(
        text,
        "mWifiManager = (WifiManager) mContext.getSystemService(Context.WIFI_SERVICE);",
        "mWifiManager = (WifiManager) mContext.getSystemService(Context.WIFI_SERVICE);\n"
        "        if (mWifiManager == null) Log.e(TAG, \"N3DS_SETTINGS_WIFI_UNAVAILABLE\");",
        "WifiManager availability",
    )
    text = once(
        text,
        "final WifiInfo wifiInfo = mWifiManager.getConnectionInfo();\n        \n        String ssid = wifiInfo.getSSID();",
        "if (mWifiManager == null) return null;\n"
        "        final WifiInfo wifiInfo = mWifiManager.getConnectionInfo();\n"
        "        if (wifiInfo == null) return null;\n"
        "        String ssid = wifiInfo.getSSID();",
        "current AP null guard",
    )
    text = once(
        text,
        "private void handleNetworkStateChanged(NetworkInfo info, String bssid) {",
        "private void handleNetworkStateChanged(NetworkInfo info, String bssid) {\n"
        "        if (info == null) {\n"
        "            Log.w(TAG, \"N3DS_SETTINGS_WIFI_NETWORK_STATE_MISSING\");\n"
        "            return;\n"
        "        }",
        "network state null guard",
    )
    text = once(
        text,
        "            ap.setStatus(DetailedState.FAILED);",
        "            if (ap != null) ap.setStatus(DetailedState.FAILED);",
        "failed AP null guard",
    )
    text = once(
        text,
        "boolean retValue = mWifiManager.saveConfiguration();",
        "boolean retValue;\n"
        "        try {\n"
        "            retValue = mWifiManager.saveConfiguration();\n"
        "        } catch (RuntimeException e) {\n"
        "            Log.e(TAG, \"N3DS_SETTINGS_WIFI_SAVE_FAILED type=\" + e.getClass().getName());\n"
        "            return false;\n"
        "        }",
        "saveConfiguration binder guard",
    )
    text = once(
        text,
        "if (!mWifiManager.enableNetwork(state.networkId, disableOthers)) {\n"
        "            return false;\n"
        "        }",
        "if (mWifiManager == null || state == null) return false;\n"
        "        try {\n"
        "            if (!mWifiManager.enableNetwork(state.networkId, disableOthers)) {\n"
        "                return false;\n"
        "            }\n"
        "        } catch (RuntimeException e) {\n"
        "            Log.e(TAG, \"N3DS_SETTINGS_WIFI_ENABLE_FAILED type=\" + e.getClass().getName());\n"
        "            return false;\n"
        "        }",
        "enableNetwork binder guard",
    )
    text = once(
        text,
        "final List<WifiConfiguration> wifiConfigs = mWifiManager.getConfiguredNetworks();\n"
        "        return wifiConfigs;",
        "if (mWifiManager == null) return Collections.emptyList();\n"
        "        try {\n"
        "            final List<WifiConfiguration> wifiConfigs = mWifiManager.getConfiguredNetworks();\n"
        "            return wifiConfigs == null ? Collections.<WifiConfiguration>emptyList() : wifiConfigs;\n"
        "        } catch (RuntimeException e) {\n"
        "            Log.e(TAG, \"N3DS_SETTINGS_WIFI_CONFIGS_FAILED type=\" + e.getClass().getName());\n"
        "            return Collections.emptyList();\n"
        "        }",
        "configured networks binder guard",
    )
    required = (MARKER, "N3DS_SETTINGS_WIFI_CALLBACK_FAILED",
                "N3DS_SETTINGS_WIFI_UNAVAILABLE",
                "N3DS_SETTINGS_WIFI_NETWORK_STATE_MISSING",
                "N3DS_SETTINGS_WIFI_SAVE_FAILED",
                "N3DS_SETTINGS_WIFI_ENABLE_FAILED")
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError("Wi-Fi resilience patch incomplete: " + repr(missing))
    return text


def patch_remembered_visibility(text):
    if REMEMBERED_MARKER in text:
        return text

    old = """            checkNextHighestPriority(ap.priority);
            
            if (mCallback != null) {
                mCallback.onAccessPointSetChanged(ap, true);
            }"""
    callback = """            /* N3DS_SETTINGS_REMEMBERED_UNSEEN_VISIBILITY: configured
             * profiles are inserted into mApOtherList even when the current
             * scan does not contain their BSS. Notify the adapter immediately
             * so a remembered HomeWifi-like profile remains visible as
             * "Not in range" instead of disappearing until the next scan. */
            if (mCallback != null) {
                mCallback.onAccessPointSetChanged(ap, true);
            }"""
    if text.count(old) == 1:
        return text.replace(
            old,
            "            checkNextHighestPriority(ap.priority);\n\n" + callback,
            1,
        )

    # A clean source variant may have lost the callback while retaining the
    # configured-profile insertion. Repair that form instead of silently
    # accepting a remembered network that can never reach the adapter.
    check = "            checkNextHighestPriority(ap.priority);"
    if text.count(check) != 1:
        raise RuntimeError(
            "remembered access-point callback anchor changed: "
            + str(text.count(old))
            + " full anchors, "
            + str(text.count(check))
            + " priority anchors"
        )
    return text.replace(check, check + "\n\n" + callback, 1)


def patch_unknown_connection_guards(text):
    """Reject unknown APs before WifiLayer can call addConfiguration."""
    if CONNECT_GUARD_MARKER not in text:
        old = "    public boolean connectToNetwork(AccessPointState state) {\n"
        new = old + """        if (state == null || !state.isConnectable()) {
            Log.w(TAG, "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE");
            return false;
        }
"""
        text = once(text, old, new, "connect unknown-security guard")

    if SAVE_GUARD_MARKER not in text:
        old = "    public boolean saveNetwork(AccessPointState state) {\n"
        new = old + """        if (state == null || TextUtils.isEmpty(state.security) ||
                AccessPointState.UNKNOWN.equals(state.security)) {
            Log.w(TAG, "N3DS_SETTINGS_UNKNOWN_SAVE_REJECTED");
            return false;
        }
"""
        text = once(text, old, new, "save unknown-security guard")
    return text


def patch_manual_connect_retry(text):
    """Make an explicit row selection restart association and honor failures."""
    if PRIORITY_GUARD_MARKER not in text:
        old = "        setHighestPriorityStateAndSave(state, config);"
        new = """        /* N3DS_SETTINGS_PRIORITY_FAILURE_GUARD: do not continue to
         * SELECT_NETWORK after updateNetwork/saveConfiguration rejected the
         * selected profile. The caller must see a real connection failure. */
        if (!setHighestPriorityStateAndSave(state, config)) {
            error(R.string.error_connecting);
            return false;
        }"""
        text = once(text, old, new, "priority failure guard")

    if MANUAL_RETRY_MARKER not in text:
        old = """        if (mCurrentSupplicantState == SupplicantState.DISCONNECTED ||
                mCurrentSupplicantState == SupplicantState.SCANNING) {
            mWifiManager.reconnect();
        }"""
        new = """        /* N3DS_SETTINGS_MANUAL_REASSOCIATE_V2: an explicit tap must
         * restart the selected profile even while supplicant is ASSOCIATING;
         * SELECT_NETWORK alone is a documented no-op in that state. */
        try {
            if (!mWifiManager.reassociate()) {
                Log.e(TAG, "N3DS_SETTINGS_MANUAL_REASSOCIATE_FAILED");
                error(R.string.error_connecting);
                return false;
            }
        } catch (RuntimeException e) {
            Log.e(TAG, "N3DS_SETTINGS_MANUAL_REASSOCIATE_FAILED type=" +
                    e.getClass().getName());
            error(R.string.error_connecting);
            return false;
        }"""
        text = once(text, old, new, "manual reassociation")
    return text


def patch(text):
    if MARKER not in text:
        text = _patch_base(text)
    text = patch_remembered_visibility(text)
    text = patch_unknown_connection_guards(text)
    text = patch_manual_connect_retry(text)
    required = (MARKER, REMEMBERED_MARKER,
                CONNECT_GUARD_MARKER, SAVE_GUARD_MARKER,
                MANUAL_RETRY_MARKER, PRIORITY_GUARD_MARKER)
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError("Wi-Fi remembered visibility patch incomplete: " + repr(missing))
    return text

def main():
    if not SOURCE.is_file():
        raise SystemExit("missing canonical Settings source: " + str(SOURCE))
    original = SOURCE.read_text()
    updated = patch(original)
    if updated != original:
        SOURCE.write_text(updated)
        print("patch_settings_wifi_resilience: callback/binder/remembered-visibility guards installed")
    else:
        print("patch_settings_wifi_resilience: already applied")


if __name__ == "__main__":
    main()
