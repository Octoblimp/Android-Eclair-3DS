#!/usr/bin/env python3
"""Regression contract for Settings' exact remembered Wi-Fi profile path."""
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/patch_settings_wifi_remembered_profile.py"
VERIFY = ROOT / "scripts/verify_release_artifacts.sh"
CANONICAL = Path(
    f"{A3DS_ROOT}/third_party/settings/src/com/android/settings/wifi"
)


LAYER_FIXTURE = r'''public class WifiLayer {
    private WifiConfiguration findConfiguredNetwork(AccessPointState state) {
        final List<WifiConfiguration> wifiConfigs = getConfiguredNetworks();
        for (int i = wifiConfigs.size() - 1; i >= 0; i--) {
            final WifiConfiguration wifiConfig = wifiConfigs.get(i);
            if (state.matchesWifiConfiguration(wifiConfig) >= AccessPointState.MATCH_WEAK) {
                return wifiConfig;
            }
        }
        return null;
    }

    private void handleScanResultsAvailable() {
                    final String ssid = AccessPointState.convertToQuotedString(scanResult.SSID);
                    String security = AccessPointState.getScanResultSecurity(scanResult);
                    
                    // See if this AP is part of a group of APs (e.g., any large
                    // wifi network has many APs, we'll only show one) that we've
                    // seen in this scan
                    AccessPointState ap = findApLocked(newScanList, AccessPointState.NETWORK_ID_ANY,
                                                 AccessPointState.BSSID_ANY, ssid, security);

                    // Yup, we've seen this network.
                    if (ap != null) {
                        if (WifiManager.compareSignalLevel(scanResult.level, ap.signal) > 0) {
                            ap.setSignal(scanResult.level);
                        }
                        continue;
                    }

                    // Find the AP in either our old scan list, or our non-seen
                    // configured networks list
                    ap = findApLocked(AccessPointState.NETWORK_ID_ANY, AccessPointState.BSSID_ANY,
                                ssid, security);

                    if (ap != null) {
                        oldScanList.remove(ap);
                        mApOtherList.remove(ap);
                    } else {
                        ap = new AccessPointState(mContext);
                    }

                    // Give it the latest state
                    ap.updateFromScanResult(scanResult);

                    if (mCallback != null) {
                        mCallback.onAccessPointSetChanged(ap, true);
                    }
                    newScanList.add(ap);
    }

    public boolean connectToNetwork(AccessPointState state) {
        if (state == null || !state.isConnectable()) {
            Log.w(TAG, "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE");
            return false;
        }
        WifiConfiguration config = findConfiguredNetwork(state);
        if (config == null) {
            config = addConfiguration(state, 0);
            if (config == null) return false;
        } else {
            state.updateWifiConfiguration(config);
        }
        managerEnableNetwork(state, false);
        setHighestPriorityStateAndSave(state, config);
        managerEnableNetwork(state, true);
        return true;
    }

    private boolean managerSaveConfiguration() { return true; }
    private boolean setHighestPriorityStateAndSave(AccessPointState state,
            WifiConfiguration config) { return managerSaveConfiguration(); }
}
'''

SETTINGS_FIXTURE = r'''public class WifiSettings {
    private void connectToNetwork(AccessPointState state) {
        if (state.hasSecurity() && !state.hasPassword()) {
            showAccessPointDialog(state, AccessPointDialog.MODE_INFO);
        } else {
            mWifiLayer.connectToNetwork(state);
        }
    }

    public boolean onPreferenceTreeClick(PreferenceScreen preferenceScreen,
            Preference preference) {
        if (preference instanceof AccessPointPreference) {
            AccessPointState state = ((AccessPointPreference) preference).getAccessPointState();
            showAccessPointDialog(state, AccessPointDialog.MODE_INFO);
        }
        return false;
    }
}
'''

DIALOG_FIXTURE = r'''public class AccessPointDialog {
    private void updatePasswordField() {
        String password = getEnteredPassword();
        boolean passwordIsEmpty = TextUtils.isEmpty(password);
        if (passwordIsEmpty && (!mState.hasPassword() ||
                mMode == MODE_RETRY_PASSWORD) &&
                mState.security != AccessPointState.OPEN && !mState.isEnterprise()) {
            showPasswordError();
            return;
        }
        if (!passwordIsEmpty) mState.setPassword(password);
    }
}
'''

# Superseded v1 output retained the broad markers but still delegated
# compatibility to findConfiguredNetwork(), and its row click had no v2 row
# marker.  Keep this fixture permanently so a dirty canonical tree upgrades
# instead of being mistaken for an idempotent final state.
V1_LAYER_HELPER = r'''    /* N3DS_SETTINGS_REMEMBERED_PROFILE_REUSE: v1 */
    public boolean hasCompatibleConfiguredNetwork(AccessPointState state) {
        if (state == null || !state.isConnectable() ||
                TextUtils.isEmpty(state.security)) {
            return false;
        }
        WifiConfiguration config = findConfiguredNetwork(state);
        if (config == null) return false;
        state.updateFromWifiConfiguration(config);
        Log.i(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_REUSE security=" +
                state.security);
        return true;
    }

'''
V1_LAYER_FIXTURE = LAYER_FIXTURE.replace(
    "    public boolean connectToNetwork(AccessPointState state) {\n",
    V1_LAYER_HELPER +
    "    public boolean connectToNetwork(AccessPointState state) {\n", 1)

V1_SETTINGS_CONNECT = r'''    private void connectToNetwork(AccessPointState state) {
        if (state.hasSecurity() &&
                !mWifiLayer.hasCompatibleConfiguredNetwork(state)) {
            Log.i(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_PROMPT");
            showAccessPointDialog(state, AccessPointDialog.MODE_INFO);
        } else {
            mWifiLayer.connectToNetwork(state);
        }
    }
'''
V1_SETTINGS_ROW = """            AccessPointState state = ((AccessPointPreference) preference).getAccessPointState();
            if (state != null && state.hasSecurity()) {
                mWifiLayer.hasCompatibleConfiguredNetwork(state);
            }
            showAccessPointDialog(state, AccessPointDialog.MODE_INFO);"""
V1_SETTINGS_FIXTURE = SETTINGS_FIXTURE.replace(
    "    private void connectToNetwork(AccessPointState state) {\n"
    "        if (state.hasSecurity() && !state.hasPassword()) {\n"
    "            showAccessPointDialog(state, AccessPointDialog.MODE_INFO);\n"
    "        } else {\n"
    "            mWifiLayer.connectToNetwork(state);\n"
    "        }\n"
    "    }\n",
    V1_SETTINGS_CONNECT, 1).replace(
    "            AccessPointState state = ((AccessPointPreference) preference).getAccessPointState();\n"
    "            showAccessPointDialog(state, AccessPointDialog.MODE_INFO);",
    V1_SETTINGS_ROW, 1)

# Buildroot may wrap the cast/getter and indent the callback below an extra
# branch.  This was the source shape that made the old exact-string patcher
# report "row-click anchor missing" even though the row was present.
V1_SETTINGS_WRAPPED_ROW_FIXTURE = V1_SETTINGS_FIXTURE.replace(
    "            AccessPointState state = ((AccessPointPreference) preference).getAccessPointState();",
    "            AccessPointState state = ((AccessPointPreference) preference)\n"
    "                    .getAccessPointState();", 1)

V1_DIALOG_FIXTURE = DIALOG_FIXTURE.replace(
    "    private void updatePasswordField() {\n",
    "    private void updatePasswordField() {\n"
    "        /* N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT: v1 */\n"
    "        final boolean reuseRemembered = mMode != AccessPointDialog.MODE_RETRY_PASSWORD &&\n"
    "                mState != null && mWifiLayer.hasCompatibleConfiguredNetwork(mState);\n",
    1)

# The v1 dialog patch already guarded the password check with !reuseRemembered;
# migration must still add the v2 marker and retain the explicit retry clause.
V1_DIALOG_GUARDED_FIXTURE = V1_DIALOG_FIXTURE.replace(
    "        if (passwordIsEmpty && (!mState.hasPassword() ||\n"
    "                mMode == MODE_RETRY_PASSWORD) &&",
    "        if (passwordIsEmpty && !reuseRemembered &&\n"
    "                (!mState.hasPassword() || mMode == MODE_RETRY_PASSWORD) &&",
    1)

# This mirrors the canonical source encountered by the manager: v2 is present
# only in source comments and the no-reprompt marker has not reached code/Dex.
V2_COMMENT_ONLY_DIALOG_FIXTURE = V1_DIALOG_GUARDED_FIXTURE.replace(
    "/* N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT: v1 */",
    "/* N3DS_SETTINGS_REMEMBERED_PROFILE_V2: comment-only v2 */\n"
    "        /* N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT: v2 */",
    1)


def load_patch_module():
    spec = importlib.util.spec_from_file_location("remembered_profile_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def exact_profile(scan, profiles):
    """Host-side mirror: credentials are never part of this matching model."""
    if not scan["seen"] or not scan["security"] or scan["security"] == "Unknown":
        return None
    for profile in profiles:
        if (profile["ssid"] == scan["ssid"] and
                profile["security"] == scan["security"]):
            return profile
    return None


def selection_action(scan, profiles, retry=False, failed_association=False):
    if retry:
        return "prompt"
    compatible = exact_profile(scan, profiles)
    same_ssid = any(profile["ssid"] == scan["ssid"] for profile in profiles)
    changed_security = same_ssid and compatible is None
    if ((scan["security"] != "Open" and compatible is None) or
            changed_security):
        return "prompt"
    return "connect"


def assert_v2_contract(module, patched):
    assert module.VERSION_MARKER in patched["layer"]
    assert module.VERSION_MARKER in patched["settings"]
    assert module.VERSION_MARKER in patched["dialog"]
    assert module.VERSION_MARKER_V3 in patched["dialog"]
    assert module.VERSION_MARKER_V4 in patched["layer"]
    assert module.VERSION_MARKER_V4 in patched["settings"]
    assert module.UNKNOWN_SCAN_MERGE_MARKER in patched["layer"]
    assert module.UNKNOWN_SCAN_CURRENT_MARKER in patched["layer"]
    assert module.VERSION_MARKER_V4 in patched["settings"]
    helper_start = patched["layer"].index("public boolean hasCompatible")
    helper_end = patched["layer"].index("public boolean hasConfiguredNetworkForSsid")
    helper = patched["layer"][helper_start:helper_end]
    assert "findConfiguredNetwork(state)" not in helper
    assert "!state.isConnectable()" not in helper
    assert "!state.seen" in helper
    assert "state.ssid.equals(config.SSID)" in helper
    assert "getWifiConfigurationSecurity(config)" in helper
    merge_start = patched["layer"].index(module.UNKNOWN_SCAN_MERGE_MARKER)
    merge = patched["layer"][merge_start:]
    assert "AccessPointState.hasProtectedCapabilityEvidence(scanResult)" in merge
    assert "findUniqueRememberedProtectedApLocked(" in merge
    assert "mergeRememberedProtectedSecurityLocked(" in merge
    assert "newScanList, ssid, null" in merge
    assert "mApScanList, ssid, security" in merge
    assert "mApOtherList, ssid, security" in merge
    assert "AccessPointState.UNKNOWN.equals(reportedSecurity)" in merge
    assert "findConfiguredProtectedApLocked(mApOtherList" in merge
    assert "isKnownProtectedSecurity(ap.security)" in merge
    assert "conflicting saved" in merge
    assert module.UNKNOWN_SCAN_RESOLVED_MARKER in merge
    assert module.UNKNOWN_SCAN_SUPPRESSED_MARKER in merge
    assert "ap = rememberedAp;" in merge
    assert "if (!security.equals(ap.security))" in merge
    assert "N3DS_SETTINGS_UNKNOWN_SCAN_REMEMBERED_SECURITY=" not in merge
    # A saved row is not a duplicate until it is actually in newScanList.
    assert merge.index("AccessPointState ap = findApLocked(newScanList") < merge.index(
        "ap = rememberedAp;")
    assert merge.index(module.UNKNOWN_SCAN_SUPPRESSED_MARKER) < merge.index(
        "mCallback.onAccessPointSetChanged")
    assert "!reuseRemembered" in patched["dialog"]
    assert module.NO_REPROMPT_LOG in patched["dialog"]
    reuse_log_start = patched["dialog"].index("if (reuseRemembered)")
    reuse_log_end = patched["dialog"].index("}", reuse_log_start)
    assert module.NO_REPROMPT_LOG in patched["dialog"][reuse_log_start:reuse_log_end]


def assert_verifier_contract(module):
    """The source V2/V3 tags are comments; DEX checks must prove behavior."""
    verifier = VERIFY.read_text(encoding="utf-8")
    assert verifier.count("grep -F '%s'" % module.VERSION_MARKER) >= 3
    assert verifier.count("grep -F '%s'" % module.VERSION_MARKER_V3) >= 1
    for marker in (module.LAYER_MARKER, module.SETTINGS_PROMPT_MARKER,
                   module.NO_REPROMPT_LOG.split('"')[1],
                   module.UNKNOWN_SCAN_RESOLVED_MARKER,
                   module.UNKNOWN_SCAN_SUPPRESSED_MARKER):
        assert "| strings | grep -F '%s'" % marker in verifier
    assert "grep -F '%s'" % module.UNKNOWN_SCAN_CURRENT_MARKER in verifier
    # V2/V3 are source migration tags, not executable strings.  Requiring
    # either in classes.dex would reject a correctly packaged Settings.apk.
    assert "| strings | grep -F '%s'" % module.VERSION_MARKER not in verifier
    assert "| strings | grep -F '%s'" % module.VERSION_MARKER_V3 not in verifier


def main():
    module = load_patch_module()
    assert_verifier_contract(module)

    # Upgrade the exact superseded marked form found in the canonical WSL
    # tree.  This must be exercised independently of the clean fixture.
    assert module.LAYER_MARKER in V1_LAYER_FIXTURE
    assert module.SETTINGS_PROMPT_MARKER in V1_SETTINGS_FIXTURE
    assert module.DIALOG_MARKER in V1_DIALOG_FIXTURE
    assert module.VERSION_MARKER not in V1_LAYER_FIXTURE
    assert module.VERSION_MARKER not in V1_SETTINGS_FIXTURE
    assert module.VERSION_MARKER not in V1_DIALOG_FIXTURE
    v1 = module.patch_sources(V1_LAYER_FIXTURE, V1_SETTINGS_FIXTURE,
                              V1_DIALOG_FIXTURE)
    v1_patched = dict(zip(("layer", "settings", "dialog"), v1))
    assert_v2_contract(module, v1_patched)
    assert module.patch_sources(*v1) == v1

    wrapped_settings = module.patch_settings(V1_SETTINGS_WRAPPED_ROW_FIXTURE)
    assert module.VERSION_MARKER in wrapped_settings
    assert module.VERSION_MARKER_V4 in wrapped_settings
    assert "connectToNetwork(state);" in wrapped_settings

    guarded_dialog = module.patch_dialog(V1_DIALOG_GUARDED_FIXTURE)
    assert module.VERSION_MARKER in guarded_dialog
    assert guarded_dialog.count("MODE_RETRY_PASSWORD") >= 2
    assert "passwordIsEmpty && !reuseRemembered" in guarded_dialog
    assert module.NO_REPROMPT_LOG in guarded_dialog

    comment_only_v2 = module.patch_dialog(V2_COMMENT_ONLY_DIALOG_FIXTURE)
    assert module.VERSION_MARKER in comment_only_v2
    assert module.VERSION_MARKER_V3 in comment_only_v2
    assert module.NO_REPROMPT_LOG in comment_only_v2
    assert module.patch_dialog(comment_only_v2) == comment_only_v2

    if all(path.is_file() for path in (
            CANONICAL / "WifiLayer.java",
            CANONICAL / "WifiSettings.java",
            CANONICAL / "AccessPointDialog.java")):
        originals = {
            "layer": (CANONICAL / "WifiLayer.java").read_text(encoding="utf-8"),
            "settings": (CANONICAL / "WifiSettings.java").read_text(encoding="utf-8"),
            "dialog": (CANONICAL / "AccessPointDialog.java").read_text(encoding="utf-8"),
        }
    else:
        originals = {"layer": LAYER_FIXTURE, "settings": SETTINGS_FIXTURE,
                     "dialog": DIALOG_FIXTURE}

    patched = dict(zip(
        ("layer", "settings", "dialog"),
        module.patch_sources(originals["layer"], originals["settings"],
                             originals["dialog"])))
    assert_v2_contract(module, patched)
    assert module.LAYER_MARKER in patched["layer"]
    assert module.SETTINGS_PROMPT_MARKER in patched["settings"]
    assert module.DIALOG_MARKER in patched["dialog"]

    helper_start = patched["layer"].index("public boolean hasCompatible")
    helper_end = patched["layer"].index("public boolean hasConfiguredNetworkForSsid")
    helper = patched["layer"][helper_start:helper_end]
    assert "findConfiguredNetwork(state)" not in helper
    assert "!state.isConnectable()" not in helper
    assert "!state.seen" in helper
    assert "state.ssid.equals(config.SSID)" in helper
    assert "getWifiConfigurationSecurity(config)" in helper
    assert "network ID/BSSID" in helper
    assert "state.updateFromWifiConfiguration(config);" in helper
    assert "hasConfiguredNetworkForSsid" in patched["layer"]
    assert "preSharedKey" not in helper
    assert "managerSaveConfiguration" in patched["layer"]
    assert "addConfiguration" not in helper

    connect = patched["settings"][patched["settings"].index(
        "private void connectToNetwork") :]
    assert connect.index("hasCompatibleConfiguredNetwork") < connect.index(
        "showAccessPointDialog")
    row = patched["settings"][patched["settings"].index(
        "onPreferenceTreeClick") :]
    assert "android.net.NetworkInfo.DetailedState.CONNECTED" in row
    assert "N3DS_SETTINGS_REMEMBERED_PROFILE_ROW_CONNECT" in row
    assert row.index("showAccessPointDialog") < row.index("connectToNetwork(state)")
    layer_connect = patched["layer"][patched["layer"].index(
        "public boolean connectToNetwork") :]
    assert "!state.isConnectable()" not in layer_connect
    assert "!state.seen" in layer_connect

    dialog = patched["dialog"]
    assert "mMode != AccessPointDialog.MODE_RETRY_PASSWORD" in dialog
    assert "!reuseRemembered" in dialog
    assert module.patch_sources(patched["layer"], patched["settings"],
                                patched["dialog"]) == (patched["layer"],
                                                       patched["settings"],
                                                       patched["dialog"])

    saved_ssid = '"HomeWifi"'
    profiles = [{"ssid": saved_ssid, "security": "PSK", "networkId": 0,
                 "configured": True}]
    # The scan row is deliberately unmerged: its network ID is unset while
    # the saved profile has an assigned ID. Compatibility must still hold.
    compatible = {"ssid": saved_ssid, "security": "PSK", "seen": True,
                  "networkId": -1}
    mismatched_security = {"ssid": saved_ssid, "security": "Open", "seen": True,
                           "networkId": -1}
    absent = {"ssid": "Guest", "security": "PSK", "seen": True,
              "networkId": -1}
    assert compatible["ssid"].startswith('"') and compatible["ssid"].endswith('"')
    assert compatible["networkId"] != profiles[0]["networkId"]
    assert selection_action(compatible, profiles) == "connect"
    assert selection_action(mismatched_security, profiles) == "prompt"
    assert selection_action(absent, profiles) == "prompt"

    # Authentication failure must not turn into an unconditional secret reuse:
    # the retry dialog still accepts a replacement key.
    assert selection_action(compatible, profiles, retry=True) == "prompt"
    # A timeout/TEMP-DISABLED association failure does not change profile
    # compatibility; selecting the same row can reuse it without a new key.
    assert selection_action(compatible, profiles, failed_association=True) == "connect"

    # A degraded scan can reuse the exact protected row only with explicit
    # privacy/RSN/WPA evidence from the lower layer.  It must never bridge an
    # empty or token-less UNKNOWN row, nor an OPEN remembered profile.
    def unknown_scan_merge(scan, profile):
        caps = (scan.get("capabilities") or "").upper()
        evidence = ("N3DS-SECURITY-UNKNOWN" in caps and
                    any(token in caps for token in (
                        "N3DS-PRIVACY", "N3DS-RSN-RAW", "N3DS-WPA-RAW")))
        if (profile["ssid"] == scan["ssid"] and
                profile["security"] not in ("Open", "Unknown") and evidence):
            return profile
        return None

    unknown_protected = {
        "ssid": saved_ssid,
        "security": "Unknown",
        "capabilities": "[N3DS-SECURITY-UNKNOWN][N3DS-RSN-RAW][ESS]",
    }
    unknown_without_evidence = dict(unknown_protected)
    unknown_without_evidence["capabilities"] = "[N3DS-SECURITY-UNKNOWN][ESS]"
    assert unknown_scan_merge(unknown_protected, profiles[0]) is profiles[0]
    assert unknown_scan_merge(unknown_without_evidence, profiles[0]) is None
    assert unknown_scan_merge(unknown_protected,
                              {"ssid": saved_ssid, "security": "Open"}) is None

    def unknown_scan_merge_candidates(scan, candidates):
        caps = (scan.get("capabilities") or "").upper()
        evidence = ("N3DS-SECURITY-UNKNOWN" in caps and
                    any(token in caps for token in (
                        "N3DS-PRIVACY", "N3DS-RSN-RAW", "N3DS-WPA-RAW")))
        matching = [candidate for candidate in candidates
                    if candidate["ssid"] == scan["ssid"] and
                    candidate["security"] not in ("Open", "Unknown")]
        classes = {candidate["security"] for candidate in matching}
        if evidence and len(classes) == 1:
            return matching[0]
        return None

    assert unknown_scan_merge_candidates(
        unknown_protected, [profiles[0], profiles[0]]) is profiles[0]
    assert unknown_scan_merge_candidates(
        unknown_protected,
        [profiles[0], {"ssid": saved_ssid, "security": "WEP"}]) is None

    # V5 list behavior: UNKNOWN is never emitted as a UI row.  A protected
    # UNKNOWN scan may become one visible configured row through the exact
    # saved profile; a second BSSID only improves that row's signal.
    def visible_scan_rows(scans, candidates):
        rows = []
        callbacks = []
        for scan in scans:
            security = scan["security"]
            remembered = None
            if security == "Unknown":
                remembered = unknown_scan_merge_candidates(scan, candidates)
                if remembered is None:
                    continue
                security = remembered["security"]
            existing = next((row for row in rows
                             if row["ssid"] == scan["ssid"] and
                             row["security"] == security), None)
            if existing is not None:
                existing["signal"] = max(existing["signal"], scan["signal"])
                continue
            row = dict(remembered) if remembered is not None else {
                "ssid": scan["ssid"], "security": security,
                "configured": False,
            }
            row.update({"seen": True, "security": security,
                        "signal": scan["signal"]})
            rows.append(row)
            callbacks.append(row)
        return rows, callbacks

    bss_a = dict(unknown_protected, signal=-70)
    bss_b = dict(unknown_protected, signal=-48)
    unresolved = {
        "ssid": '"Mystery"', "security": "Unknown", "signal": -35,
        "capabilities": "[N3DS-SECURITY-UNKNOWN][ESS]",
    }
    rows, callbacks = visible_scan_rows([bss_a, bss_b, unresolved], profiles)
    assert len(rows) == 1
    assert len(callbacks) == 1
    assert rows[0]["ssid"] == saved_ssid
    assert rows[0]["security"] == "PSK"
    assert rows[0]["configured"] is True
    assert rows[0]["seen"] is True
    assert rows[0]["signal"] == -48
    assert all(row["security"] != "Unknown" for row in rows)

    # A reboot reloads the same persisted profile; no UI-only password state is
    # required for it to be selected again.
    reloaded_profiles = list(profiles)
    assert selection_action(compatible, reloaded_profiles) == "connect"
    print("settings_wifi_remembered_profile: PASS")


if __name__ == "__main__":
    main()
