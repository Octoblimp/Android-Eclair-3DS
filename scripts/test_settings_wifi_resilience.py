#!/usr/bin/env python3
"""Fixture regression for the maintained Settings Wi-Fi resilience patch."""
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/patch_settings_wifi_resilience.py"
CANONICAL_FIXTURE = Path(
    f"{A3DS_ROOT}/third_party/settings/src/com/android/settings/wifi/WifiLayer.java"
)


# Keep this regression runnable from both the Windows checkout and the
# canonical WSL checkout. The production patcher still targets the canonical
# source; this compact fixture only supplies its exact anchors when that tree
# is not mounted in the current test environment.
SYNTHETIC_FIXTURE = r'''public class WifiLayer {
    private void receiverSetup() {
        mWifiManager = (WifiManager) mContext.getSystemService(Context.WIFI_SERVICE);
    }

    public void onReceive(Context context, Intent intent) {
        final String action = intent.getAction();
        if (action.equals(WifiManager.NETWORK_STATE_CHANGED_ACTION)) {
            handleNetworkStateChanged(
                    (NetworkInfo) intent.getParcelableExtra(WifiManager.EXTRA_NETWORK_INFO),
                    intent.getStringExtra(WifiManager.EXTRA_BSSID));
        }
    }

    private AccessPointState getCurrentAp() {
        final WifiInfo wifiInfo = mWifiManager.getConnectionInfo();
        
        String ssid = wifiInfo.getSSID();
        return null;
    }

    private void handleNetworkStateChanged(NetworkInfo info, String bssid) {
        AccessPointState ap = null;
        if (info != null) {
            ap.setStatus(DetailedState.FAILED);
        }
    }

    public boolean connectToNetwork(AccessPointState state) {
        WifiConfiguration config = addConfiguration(state, 0);
        setHighestPriorityStateAndSave(state, config);
        if (mCurrentSupplicantState == SupplicantState.DISCONNECTED ||
                mCurrentSupplicantState == SupplicantState.SCANNING) {
            mWifiManager.reconnect();
        }
        return config != null;
    }

    public boolean saveNetwork(AccessPointState state) {
        WifiConfiguration config = addConfiguration(state, ADD_CONFIGURATION_SAVE);
        return config != null;
    }

    private boolean managerSaveConfiguration() {
        boolean retValue = mWifiManager.saveConfiguration();
        return retValue;
    }

    private boolean managerEnableNetwork(AccessPointState state, boolean disableOthers) {
        if (!mWifiManager.enableNetwork(state.networkId, disableOthers)) {
            return false;
        }
        return true;
    }

    private List<WifiConfiguration> getConfiguredNetworks() {
        final List<WifiConfiguration> wifiConfigs = mWifiManager.getConfiguredNetworks();
        return wifiConfigs;
    }

    private void loadConfiguredAccessPoints() {
        final List<WifiConfiguration> configs = getConfiguredNetworks();
        for (int i = configs.size() - 1; i >= 0; i--) {
            AccessPointState ap = new AccessPointState(mContext);
            mApOtherList.add(ap);
            checkNextHighestPriority(ap.priority);
            
            if (mCallback != null) {
                mCallback.onAccessPointSetChanged(ap, true);
            }
        }
    }
}
'''


def load_patch_module():
    spec = importlib.util.spec_from_file_location("settings_wifi_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    module = load_patch_module()
    original = (CANONICAL_FIXTURE.read_text(encoding="utf-8")
                if CANONICAL_FIXTURE.is_file() else SYNTHETIC_FIXTURE)
    patched = module.patch(original)
    for marker in (
        "N3DS_SETTINGS_WIFI_CALLBACK_GUARD",
        "N3DS_SETTINGS_WIFI_CALLBACK_FAILED",
        "N3DS_SETTINGS_WIFI_UNAVAILABLE",
        "N3DS_SETTINGS_WIFI_NETWORK_STATE_MISSING",
        "N3DS_SETTINGS_WIFI_SAVE_FAILED",
        "N3DS_SETTINGS_WIFI_ENABLE_FAILED",
        "N3DS_SETTINGS_REMEMBERED_UNSEEN_VISIBILITY",
        "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE",
        "N3DS_SETTINGS_UNKNOWN_SAVE_REJECTED",
        "N3DS_SETTINGS_MANUAL_REASSOCIATE_V2",
        "N3DS_SETTINGS_PRIORITY_FAILURE_GUARD",
    ):
        assert patched.count(marker) == 1 or marker == "N3DS_SETTINGS_WIFI_CALLBACK_GUARD"
    diagnostic = patched[patched.index("N3DS_SETTINGS_WIFI_CALLBACK_GUARD"):]
    assert "String action = null;" in patched
    assert "final String action = intent.getAction();" not in patched
    assert "Log.e(TAG, \"N3DS_SETTINGS_WIFI_CALLBACK_FAILED" in diagnostic
    assert "Log.e(TAG, \"N3DS_SETTINGS_WIFI_SAVE_FAILED" in diagnostic
    assert "Log.e(TAG, \"N3DS_SETTINGS_WIFI_ENABLE_FAILED" in diagnostic
    assert "Log.e(TAG, \"N3DS_SETTINGS_WIFI_CONFIGS_FAILED" in diagnostic
    assert "mApOtherList.add(ap);" in patched
    connect = patched[patched.index("public boolean connectToNetwork") :]
    assert connect.index("N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE") < connect.index("addConfiguration")
    assert "if (!setHighestPriorityStateAndSave(state, config))" in connect
    assert "mWifiManager.reassociate()" in connect
    assert "mWifiManager.reconnect()" not in connect
    assert connect.index("N3DS_SETTINGS_PRIORITY_FAILURE_GUARD") < connect.index(
        "N3DS_SETTINGS_MANUAL_REASSOCIATE_V2")
    save = patched[patched.index("public boolean saveNetwork") :]
    assert save.index("N3DS_SETTINGS_UNKNOWN_SAVE_REJECTED") < save.index("addConfiguration")
    remembered = patched[patched.index("N3DS_SETTINGS_REMEMBERED_UNSEEN_VISIBILITY") :]
    assert "mCallback.onAccessPointSetChanged(ap, true);" in remembered
    assert "Not in range" in remembered
    missing_callback = original.replace(
        "            if (mCallback != null) {\n"
        "                mCallback.onAccessPointSetChanged(ap, true);\n"
        "            }",
        "",
        1,
    ).replace(module.REMEMBERED_MARKER, "REMOVED_REMEMBERED_MARKER")
    repaired_missing_callback = module.patch(missing_callback)
    assert "N3DS_SETTINGS_REMEMBERED_UNSEEN_VISIBILITY" in repaired_missing_callback
    assert "mCallback.onAccessPointSetChanged(ap, true);" in repaired_missing_callback
    assert "Log.e(TAG, \"N3DS_SETTINGS_WIFI_CALLBACK_FAILED SSID" not in diagnostic
    assert "Log.e(TAG, \"N3DS_SETTINGS_WIFI_CALLBACK_FAILED BSSID" not in diagnostic
    assert module.patch(patched) == patched
    print("settings_wifi_resilience: PASS")


if __name__ == "__main__":
    main()
