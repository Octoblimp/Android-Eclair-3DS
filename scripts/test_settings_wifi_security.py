#!/usr/bin/env python3
"""Regression test for Settings Wi-Fi security classification and full bitset configuration."""
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/patch_settings_wifi_security.py"
FIXTURE = Path(f"{A3DS_ROOT}/third_party/settings/src/com/android/settings/wifi/AccessPointState.java")


SYNTHETIC_FIXTURE = r'''import android.net.wifi.ScanResult;
import android.net.wifi.WifiConfiguration;
import android.net.wifi.WifiConfiguration.AuthAlgorithm;
import android.net.wifi.WifiConfiguration.KeyMgmt;
import android.net.wifi.WifiConfiguration.PairwiseCipher;
import android.net.wifi.WifiConfiguration.Protocol;
import android.net.wifi.WifiConfiguration.GroupCipher;
import android.text.TextUtils;
import android.util.Log;

public final class AccessPointState {
    private static final String TAG = "AccessPointState";
    public static final String PSK = "PSK";
    public static final String EAP = "EAP";
    public static final String WEP = "WEP";
    public static final String OPEN = "Open";

    public boolean isConnectable() {
        return !primary && seen;
    }

    public static String getWifiConfigurationSecurity(WifiConfiguration wifiConfig) {
        if (!TextUtils.isEmpty(wifiConfig.eap.value())) {
            return EAP;
        } else if (!TextUtils.isEmpty(wifiConfig.preSharedKey)) {
            return PSK;
        } else if (!TextUtils.isEmpty(wifiConfig.wepKeys[0])) {
            return WEP;
        }
        return OPEN;
    }

    private void setupSecurity(WifiConfiguration config) {
        if (TextUtils.isEmpty(security)) {
            security = OPEN;
            Log.w(TAG, "Empty security, assuming open");
        }
        if (security.equals(WEP)) {
            config.allowedKeyManagement.set(KeyMgmt.NONE);
        } else if (security.equals(PSK)){
            // If password is empty, it should be left untouched
            if (!TextUtils.isEmpty(mPassword)) {
                if (mPassword.length() == 64 && isHex(mPassword)) {
                    config.preSharedKey = mPassword;
                } else {
                    config.preSharedKey = convertToQuotedString(mPassword);
                }
            }
        } else if (security.equals(EAP)) {
            config.allowedKeyManagement.set(KeyMgmt.WPA_EAP);
            config.allowedKeyManagement.set(KeyMgmt.IEEE8021X);
            if (!TextUtils.isEmpty(mPassword)) {
                config.password.setValue(convertToQuotedString(mPassword));
            }
        } else if (security.equals(OPEN)) {
            config.allowedKeyManagement.set(KeyMgmt.NONE);
        }
    }

    public static String getScanResultSecurity(ScanResult scanResult) {
        final String cap = scanResult.capabilities;
        final String[] securityModes = { WEP, WPA, WPA2, WPA_EAP, IEEE8021X };
        for (int i = securityModes.length - 1; i >= 0; i--) {
            if (cap.contains(securityModes[i])) return securityModes[i];
        }
        return OPEN;
    }
}
'''


PREVIOUS_SCAN_SECURITY = r'''    /* N3DS_SETTINGS_SCAN_SECURITY_FAIL_CLOSED: previous classifier */
    public static String getScanResultSecurity(ScanResult scanResult) {
        if (scanResult == null || TextUtils.isEmpty(scanResult.capabilities)) {
            return UNKNOWN;
        }
        final String cap = scanResult.capabilities.toUpperCase(Locale.US);
        if (cap.contains("IEEE8021X")) return IEEE8021X;
        if (cap.contains("WPA-EAP") || cap.contains("-EAP") ||
            cap.contains("[EAP")) return WPA_EAP;
        if (cap.contains("WPA2") || cap.contains("RSN") ||
            cap.contains("PSK")) return WPA2;
        if (cap.contains("WPA")) return WPA;
        if (cap.contains("WEP") || cap.contains("PRIVACY")) return WEP;
        return OPEN;
    }'''

OLD_SCAN_HELPER = r'''    /* N3DS_SETTINGS_SCAN_SECURITY_FAIL_CLOSED: previous open helper */
    private static boolean isExplicitOpenCapability(String cap) {
        return cap.equals("[ESS]");
    }
'''


def load_patch_module():
    spec = importlib.util.spec_from_file_location("settings_wifi_sec_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    module = load_patch_module()
    original = (FIXTURE.read_text(encoding="utf-8")
                if FIXTURE.is_file() else SYNTHETIC_FIXTURE)
    patched = module.patch(original)
    assert "N3DS_SETTINGS_WIFI_SECURITY_REPAIR" in patched
    assert "N3DS_SETTINGS_SCAN_SECURITY_FAIL_CLOSED" in patched
    assert "N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED" in patched
    assert "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE" in patched
    assert module.PROTECTED_EVIDENCE_MARKER in patched
    assert "hasProtectedCapabilityEvidence(ScanResult scanResult)" in patched
    assert "N3DS-SECURITY-UNKNOWN" in patched[patched.index(
        module.PROTECTED_EVIDENCE_MARKER):]
    evidence = patched[patched.index(module.PROTECTED_EVIDENCE_MARKER):
                       patched.index(module.PROTECTED_EVIDENCE_MARKER) + 900]
    assert "N3DS-PRIVACY" in evidence
    assert "N3DS-RSN-RAW" in evidence
    assert "N3DS-WPA-RAW" in evidence
    assert "!UNKNOWN.equals(security)" in patched
    assert "!primary && seen && !TextUtils.isEmpty(security)" in patched
    assert 'public static final String UNKNOWN = "Unknown";' in patched
    assert "toUpperCase(Locale.US)" in patched
    assert "N3DS_SETTINGS_OPEN_CAPABILITY_ALLOWLIST" in patched
    assert module.SCAN_CURRENT_VERSION_MARKER in patched
    assert patched.count(module.SCAN_HELPER_SIGNATURE) == 1
    assert module.patch(patched) == patched
    assert "config.allowedKeyManagement.set(KeyMgmt.WPA_PSK);" in patched
    assert module.WPA_GROUP_MARKER in patched
    setup = patched[patched.index("private void setupSecurity"):
                    patched.index("private static boolean isHexWepKey")]
    assert "GroupCipher.WEP40" not in setup
    assert "GroupCipher.WEP104" not in setup
    assert setup.count("GroupCipher.TKIP") == 2
    assert setup.count("GroupCipher.CCMP") == 2
    assert "config.allowedAuthAlgorithms.set(AuthAlgorithm.OPEN);" in patched
    assert "wifiConfig.allowedKeyManagement.get(KeyMgmt.WPA_PSK)" in patched
    assert "security = UNKNOWN;" in patched
    assert "security = OPEN;" not in patched[patched.index("private void setupSecurity"):]
    open_branch = patched[patched.index("} else if (security.equals(OPEN))") :]
    assert "config.allowedAuthAlgorithms.set(AuthAlgorithm.OPEN);" in open_branch
    assert "config.allowedKeyManagement.set(KeyMgmt.NONE);" in open_branch
    unknown_branch = patched[patched.index("N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED: never") :
                            patched.index("N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED: never") + 450]
    assert "config.allowedKeyManagement.set(KeyMgmt.NONE);" not in unknown_branch
    scan_source = patched[patched.index("getScanResultSecurity(ScanResult scanResult)") :]
    assert scan_source.index('cap.contains("[WPA2-")') < scan_source.index(
        'cap.contains("N3DS-SECURITY-UNKNOWN")')
    for undeclared in ("return WPA2;", "return WPA;", "return WPA_EAP;",
                       "return IEEE8021X;"):
        assert undeclared not in scan_source, undeclared
    for declared in ("return PSK;", "return EAP;", "return WEP;",
                     "return OPEN;", "return UNKNOWN;"):
        assert declared in scan_source, declared

    # Older generated sources may already contain the allowlist marker, so
    # prove migration is driven by the classifier body/version, not marker
    # presence alone.
    previous_with_allowlist = PREVIOUS_SCAN_SECURITY.replace(
        "previous classifier */",
        "previous classifier; N3DS_SETTINGS_OPEN_CAPABILITY_ALLOWLIST */")
    previous_variant = patched.replace(module.NEW_SCAN_SECURITY,
                                       previous_with_allowlist, 1)
    previous_variant = previous_variant.replace(
        module.SCAN_SECURITY_SIGNATURE,
        OLD_SCAN_HELPER + module.SCAN_SECURITY_SIGNATURE, 1)
    migrated = module.patch(previous_variant)
    assert "N3DS_SETTINGS_OPEN_CAPABILITY_ALLOWLIST" in migrated
    assert module.SCAN_CURRENT_VERSION_MARKER in migrated
    migrated_scan = migrated[migrated.index(
        "getScanResultSecurity(ScanResult scanResult)") :]
    for undeclared in ("return WPA2;", "return WPA;", "return WPA_EAP;",
                       "return IEEE8021X;"):
        assert undeclared not in migrated_scan, undeclared
    assert "return PSK;" in migrated_scan
    assert "return EAP;" in migrated_scan
    assert migrated.count(module.SCAN_HELPER_SIGNATURE) == 1

    # A prior migration could leave the old helper immediately before the V3
    # helper. Normalize that duplicate as well.
    duplicate_variant = patched.replace(
        module.SCAN_HELPER_COMMENT,
        OLD_SCAN_HELPER + module.SCAN_HELPER_COMMENT, 1)
    duplicate_migrated = module.patch(duplicate_variant)
    assert duplicate_migrated.count(module.SCAN_HELPER_SIGNATURE) == 1
    assert module.patch(duplicate_migrated) == duplicate_migrated
    
    expected = {
        "[ESS]": "Open",
        "[OPEN][ESS]": "Open",
        "[WEP][ESS]": "WEP",
        "[PRIVACY][ESS]": "WEP",
        "[RSN-?][ESS]": "PSK",
        "[WPA-?][ESS]": "PSK",
        "[WPA2-PSK-CCMP][ESS]": "PSK",
        "[IEEE8021X][ESS]": "EAP",
        "[ESS][WPS]": "Open",
        "": "Unknown",
        "[MALFORMED]": "Unknown",
        "[MALFORMED][ESS]": "Unknown",
        "[N3DS-SECURITY-UNKNOWN][N3DS-PRIVACY][ESS]": "Unknown",
        "[N3DS-SECURITY-UNKNOWN][N3DS-RSN-RAW][ESS]": "Unknown",
        "[N3DS-RSN-RAW][ESS]": "Unknown",
        # Exact #241 failure shape: a valid standard WPA2 result must outrank
        # a diagnostic emitted for a malformed duplicate probe/beacon IE.
        "[WPA2-PSK-CCMP][N3DS-PRIVACY][N3DS-RSN-RAW]"
        "[N3DS-SECURITY-UNKNOWN][ESS]": "PSK",
    }
    for capabilities, security in expected.items():
        actual = module.classify_capabilities(capabilities)
        assert actual == security, (capabilities, actual, security)

    def protected_evidence(capabilities):
        cap = (capabilities or "").upper()
        return ("N3DS-SECURITY-UNKNOWN" in cap and
                any(marker in cap for marker in (
                    "N3DS-PRIVACY", "N3DS-RSN-RAW", "N3DS-WPA-RAW")))

    # Only the lower-layer's explicit protected markers can bridge an
    # UNKNOWN scan result to an exact saved protected profile.  Empty,
    # malformed-without-evidence, and explicit open rows must remain false.
    assert protected_evidence(
        "[N3DS-SECURITY-UNKNOWN][N3DS-PRIVACY][ESS]")
    assert protected_evidence(
        "[N3DS-SECURITY-UNKNOWN][N3DS-RSN-RAW][ESS]")
    assert protected_evidence(
        "[N3DS-SECURITY-UNKNOWN][N3DS-WPA-RAW][ESS]")
    assert not protected_evidence("[N3DS-SECURITY-UNKNOWN][ESS]")
    assert not protected_evidence("")
    assert not protected_evidence("[ESS][OPEN]")
    assert module.patch(patched) == patched
    print("settings_wifi_security: PASS")


if __name__ == "__main__":
    main()
