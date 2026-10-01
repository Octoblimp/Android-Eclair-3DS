#!/usr/bin/env python3
"""Patch legacy Settings Wi-Fi security and remembered-network semantics.

The old Settings code treated every scan result whose capability text could not
be parsed as OPEN.  That is unsafe for a malformed protected beacon: the
supplicant may still expose an RSN/WPA/privacy marker even when detailed IE
parsing degraded.  Keep OPEN reserved for explicit open evidence and use an
UNKNOWN value for missing/degraded text so setupSecurity cannot silently set
KeyMgmt.NONE.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
PATHS = (
    ROOT / "third_party/settings/src/com/android/settings/wifi/AccessPointState.java",
)
MARKER = "N3DS_SETTINGS_WIFI_SECURITY_REPAIR"
SCAN_MARKER = "N3DS_SETTINGS_SCAN_SECURITY_FAIL_CLOSED"
SCAN_CURRENT_MARKER = "N3DS_SETTINGS_OPEN_CAPABILITY_ALLOWLIST"
SCAN_CURRENT_VERSION_MARKER = "N3DS_SETTINGS_SCAN_SECURITY_V3"
UNKNOWN_SETUP_MARKER = "N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED"
CONNECTABILITY_MARKER = "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE"
PROTECTED_EVIDENCE_MARKER = "N3DS_SETTINGS_PROTECTED_SCAN_EVIDENCE"
WPA_GROUP_MARKER = "N3DS_SETTINGS_WPA_GROUP_CIPHERS_V2"

OLD_GET_SECURITY = """    public static String getWifiConfigurationSecurity(WifiConfiguration wifiConfig) {
        if (!TextUtils.isEmpty(wifiConfig.eap.value())) {
            return EAP;
        } else if (!TextUtils.isEmpty(wifiConfig.preSharedKey)) {
            return PSK;
        } else if (!TextUtils.isEmpty(wifiConfig.wepKeys[0])) {
            return WEP;
        }
        return OPEN;
    }"""

NEW_GET_SECURITY = """    /* N3DS_SETTINGS_WIFI_SECURITY_REPAIR: correctly classify saved WPA/WPA2-PSK
     * networks even when wpa_supplicant masks or omits cleartext preSharedKey,
     * and populate full KeyMgmt/Protocol/Cipher/AuthAlgorithm bitsets for both
     * PSK and OPEN so wpa_supplicant never rejects connections with privacy
     * or auth mismatches. */
    public static String getWifiConfigurationSecurity(WifiConfiguration wifiConfig) {
        if (wifiConfig == null) {
            return OPEN;
        }
        if (!TextUtils.isEmpty(wifiConfig.eap.value()) ||
            (wifiConfig.allowedKeyManagement != null &&
             (wifiConfig.allowedKeyManagement.get(KeyMgmt.WPA_EAP) ||
              wifiConfig.allowedKeyManagement.get(KeyMgmt.IEEE8021X)))) {
            return EAP;
        } else if (!TextUtils.isEmpty(wifiConfig.preSharedKey) ||
                   (wifiConfig.allowedKeyManagement != null &&
                    wifiConfig.allowedKeyManagement.get(KeyMgmt.WPA_PSK))) {
            return PSK;
        } else if (!TextUtils.isEmpty(wifiConfig.wepKeys[0]) ||
                   (wifiConfig.allowedAuthAlgorithms != null &&
                    wifiConfig.allowedAuthAlgorithms.get(AuthAlgorithm.SHARED)) ||
                   (wifiConfig.allowedKeyManagement != null &&
                    wifiConfig.allowedKeyManagement.get(KeyMgmt.NONE) &&
                    wifiConfig.wepTxKeyIndex >= 0 && wifiConfig.wepTxKeyIndex < 4 &&
                    !TextUtils.isEmpty(wifiConfig.wepKeys[wifiConfig.wepTxKeyIndex]))) {
            return WEP;
        }
        return OPEN;
    }"""

OLD_SETUP_SECURITY = """        } else if (security.equals(PSK)){
            // If password is empty, it should be left untouched
            if (!TextUtils.isEmpty(mPassword)) {
                if (mPassword.length() == 64 && isHex(mPassword)) {
                    // Goes unquoted as hex
                    config.preSharedKey = mPassword;
                } else {
                    // Goes quoted as ASCII
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
        }"""

NEW_SETUP_SECURITY = """        } else if (security.equals(PSK)){
            // If password is empty, it should be left untouched
            if (!TextUtils.isEmpty(mPassword)) {
                if (mPassword.length() == 64 && isHex(mPassword)) {
                    // Goes unquoted as hex
                    config.preSharedKey = mPassword;
                } else {
                    // Goes quoted as ASCII
                    config.preSharedKey = convertToQuotedString(mPassword);
                }
            }
            config.allowedAuthAlgorithms.set(AuthAlgorithm.OPEN);
            config.allowedProtocols.set(Protocol.WPA);
            config.allowedProtocols.set(Protocol.RSN);
            config.allowedKeyManagement.set(KeyMgmt.WPA_PSK);
            config.allowedPairwiseCiphers.set(PairwiseCipher.TKIP);
            config.allowedPairwiseCiphers.set(PairwiseCipher.CCMP);
            /* N3DS_SETTINGS_WPA_GROUP_CIPHERS_V2: wpa_supplicant 2.10
             * rejects the legacy mixed "WEP40 WEP104 TKIP CCMP" group set.
             * WPA-PSK/EAP profiles advertise only their valid group ciphers;
             * the separate WEP branch retains KeyMgmt.NONE and WEP keys. */
            config.allowedGroupCiphers.set(GroupCipher.TKIP);
            config.allowedGroupCiphers.set(GroupCipher.CCMP);
        } else if (security.equals(EAP)) {
            config.allowedAuthAlgorithms.set(AuthAlgorithm.OPEN);
            config.allowedProtocols.set(Protocol.WPA);
            config.allowedProtocols.set(Protocol.RSN);
            config.allowedKeyManagement.set(KeyMgmt.WPA_EAP);
            config.allowedKeyManagement.set(KeyMgmt.IEEE8021X);
            config.allowedPairwiseCiphers.set(PairwiseCipher.TKIP);
            config.allowedPairwiseCiphers.set(PairwiseCipher.CCMP);
            config.allowedGroupCiphers.set(GroupCipher.TKIP);
            config.allowedGroupCiphers.set(GroupCipher.CCMP);
            if (!TextUtils.isEmpty(mPassword)) {
                config.password.setValue(convertToQuotedString(mPassword));
            }
        } else if (security.equals(OPEN)) {
            config.allowedAuthAlgorithms.set(AuthAlgorithm.OPEN);
            config.allowedKeyManagement.set(KeyMgmt.NONE);
        }"""

SCAN_SECURITY_SIGNATURE = "    public static String getScanResultSecurity(ScanResult scanResult)"
SCAN_HELPER_SIGNATURE = "    private static boolean isExplicitOpenCapability(String cap)"
SCAN_HELPER_COMMENT = "    /* N3DS_SETTINGS_SCAN_SECURITY_FAIL_CLOSED"
CONNECTABLE_SIGNATURE = "    public boolean isConnectable()"

NEW_SCAN_SECURITY = """    /* N3DS_SETTINGS_SCAN_SECURITY_FAIL_CLOSED: only an explicit
     * N3DS_SETTINGS_SCAN_SECURITY_V3: canonical AccessPointState security
     * vocabulary is PSK/EAP/WEP/OPEN/UNKNOWN.  A valid standard supplicant
     * security token is authoritative even when a diagnostic marker records
     * a malformed duplicate probe/beacon IE for the same BSS.
     * capability allowlisted by isExplicitOpenCapability() means open.
     * Empty/degraded flags are not proof of an open BSS; preserve upstream
     * WEP/privacy and malformed RSN/WPA markers as protected/unknown evidence.
     * Settings does not see the raw 802.11 privacy bit; the lower layer must
     * preserve it as a capability marker before this method is called. */
    private static boolean isExplicitOpenCapability(String cap) {
        /* N3DS_SETTINGS_OPEN_CAPABILITY_ALLOWLIST: keep this deliberately
         * bounded. Unknown tokens (including [MALFORMED]) never imply OPEN. */
        final String[] openCapabilities = {
            "[ESS]", "[OPEN]", "[ESS][OPEN]", "[OPEN][ESS]",
            "[ESS][WPS]", "[WPS][ESS]",
            "[ESS][WPS-PBC]", "[WPS-PBC][ESS]",
            "[ESS][WPS-AUTH]", "[WPS-AUTH][ESS]",
            "[ESS][WPS-PIN]", "[WPS-PIN][ESS]"
        };
        for (int i = openCapabilities.length - 1; i >= 0; i--) {
            if (openCapabilities[i].equals(cap)) {
                return true;
            }
        }
        return false;
    }

    public static String getScanResultSecurity(ScanResult scanResult) {
        if (scanResult == null || TextUtils.isEmpty(scanResult.capabilities)) {
            Log.w(TAG, "N3DS_SETTINGS_SCAN_SECURITY_UNKNOWN empty capabilities");
            return UNKNOWN;
        }

        final String cap = scanResult.capabilities.toUpperCase(Locale.US);
        /* Prefer the standard, successfully parsed capability tokens emitted
         * by wpa_supplicant.  The N3DS diagnostic tokens are deliberately not
         * accepted as a security class: N3DS-RSN-RAW, for example, proves
         * only that a raw IE existed, not that it parsed as WPA2. */
        if (cap.contains("IEEE8021X")) {
            return EAP;
        }
        if (cap.contains("WPA-EAP") || cap.contains("-EAP") ||
            cap.contains("[EAP")) {
            return EAP;
        }
        if (cap.contains("[WPA2-") || cap.contains("[WPA-") ||
            cap.contains("[RSN-") || cap.contains("PSK")) {
            return PSK;
        }
        if (cap.contains("[WEP]") || cap.contains("[PRIVACY]")) {
            return WEP;
        }
        /* No valid standard class was present.  Malformed/raw diagnostics
         * remain fail-closed and are suppressed by WifiLayer before the UI. */
        if (cap.contains("N3DS-SECURITY-UNKNOWN")) {
            return UNKNOWN;
        }
        if (isExplicitOpenCapability(cap)) {
            return OPEN;
        }

        Log.w(TAG, "N3DS_SETTINGS_SCAN_SECURITY_UNKNOWN capabilities=" +
                scanResult.capabilities);
        return UNKNOWN;
    }"""

PROTECTED_EVIDENCE_METHOD = """    /* N3DS_SETTINGS_PROTECTED_SCAN_EVIDENCE: an UNKNOWN
     * capability may still be safely linked to an exact remembered protected
     * profile only when the lower layer preserved both the malformed marker
     * and explicit privacy/RSN/WPA evidence.  Empty or token-less UNKNOWN
     * rows remain non-actionable and are never treated as OPEN. */
    public static boolean hasProtectedCapabilityEvidence(ScanResult scanResult) {
        if (scanResult == null || TextUtils.isEmpty(scanResult.capabilities)) {
            return false;
        }
        final String cap = scanResult.capabilities.toUpperCase(Locale.US);
        if (!cap.contains("N3DS-SECURITY-UNKNOWN")) {
            return false;
        }
        return cap.contains("N3DS-PRIVACY") ||
                cap.contains("N3DS-RSN-RAW") ||
                cap.contains("N3DS-WPA-RAW");
    }
"""

NEW_CONNECTABLE = """    /* N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE: an AP with missing or
     * unclassified security may remain visible for diagnosis, but it must not
     * be offered as an actionable connection target. */
    public boolean isConnectable() {
        return !primary && seen && !TextUtils.isEmpty(security) &&
                !UNKNOWN.equals(security);
    }"""


def classify_capabilities(capabilities: str) -> str:
    """Host-side mirror of the Java scan classifier for focused regressions."""
    if not capabilities:
        return "Unknown"
    cap = capabilities.upper()
    if "IEEE8021X" in cap:
        return "EAP"
    if "WPA-EAP" in cap or "-EAP" in cap or "[EAP" in cap:
        return "EAP"
    if "[WPA2-" in cap or "[WPA-" in cap or "[RSN-" in cap or "PSK" in cap:
        return "PSK"
    if "[WEP]" in cap or "[PRIVACY]" in cap:
        return "WEP"
    if "N3DS-SECURITY-UNKNOWN" in cap:
        return "Unknown"
    open_capabilities = {
        "[ESS]", "[OPEN]", "[ESS][OPEN]", "[OPEN][ESS]",
        "[ESS][WPS]", "[WPS][ESS]",
        "[ESS][WPS-PBC]", "[WPS-PBC][ESS]",
        "[ESS][WPS-AUTH]", "[WPS-AUTH][ESS]",
        "[ESS][WPS-PIN]", "[WPS-PIN][ESS]",
    }
    if cap in open_capabilities:
        return "Open"
    return "Unknown"


def replace_method(text: str, signature: str, replacement: str) -> str:
    """Replace one Java method body using balanced braces."""
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
    return text[:start] + replacement + text[end + 1:]


def add_scan_security_constants(text: str) -> str:
    if 'public static final String UNKNOWN = "Unknown";' not in text:
        anchor = '    public static final String OPEN = "Open";'
        if text.count(anchor) != 1:
            raise RuntimeError("could not find OPEN security constant")
        text = text.replace(
            anchor,
            anchor + '\n    public static final String UNKNOWN = "Unknown";',
            1,
        )
    if "import java.util.Locale;" not in text:
        anchor = "import android.util.Log;"
        if text.count(anchor) != 1:
            raise RuntimeError("could not find Log import")
        text = text.replace(anchor, anchor + "\nimport java.util.Locale;", 1)
    return text


def remove_prior_scan_helpers(text: str) -> str:
    """Remove every earlier marker-bearing helper before the classifier."""
    while True:
        classifier = text.index(SCAN_SECURITY_SIGNATURE)
        helper = text.find(SCAN_HELPER_SIGNATURE, 0, classifier)
        if helper < 0:
            return text

        start = text.rfind(SCAN_HELPER_COMMENT, 0, helper)
        if start < 0:
            start = helper
        brace = text.index("{", helper)
        depth = 0
        end = None
        for pos in range(brace, len(text)):
            if text[pos] == "{":
                depth += 1
            elif text[pos] == "}":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break
        if end is None:
            raise RuntimeError("unclosed scan security helper")
        text = text[:start] + text[end:]


def patch_scan_security(text: str) -> str:
    # The first version of this repair used the same marker (and, in some
    # generated sources, even the allowlist marker) but returned undeclared
    # WPA/WPA2 identifiers. Currentness is therefore tied to a version marker
    # and the actual method body, not to a broad marker elsewhere in the file.
    method = ""
    if SCAN_SECURITY_SIGNATURE in text:
        start = text.index(SCAN_SECURITY_SIGNATURE)
        brace = text.index("{", start)
        depth = 0
        for pos in range(brace, len(text)):
            if text[pos] == "{":
                depth += 1
            elif text[pos] == "}":
                depth -= 1
                if depth == 0:
                    method = text[start:pos + 1]
                    break
    undeclared = ("return WPA2;", "return WPA;", "return WPA_EAP;",
                  "return IEEE8021X;")
    if (SCAN_CURRENT_VERSION_MARKER in text and method and
            text.count(SCAN_HELPER_SIGNATURE) == 1 and
            not any(token in method for token in undeclared)):
        return text
    text = remove_prior_scan_helpers(text)
    text = add_scan_security_constants(text)
    return replace_method(text, SCAN_SECURITY_SIGNATURE, NEW_SCAN_SECURITY)


def patch_protected_evidence(text: str) -> str:
    if PROTECTED_EVIDENCE_MARKER in text:
        if "hasProtectedCapabilityEvidence(ScanResult scanResult)" not in text:
            raise RuntimeError("protected scan evidence marker is incomplete")
        return text
    anchor = "    public static String getScanResultSecurity(ScanResult scanResult)"
    if text.count(anchor) != 1:
        raise RuntimeError("protected scan evidence anchor changed")
    return text.replace(anchor, PROTECTED_EVIDENCE_METHOD + "\n" + anchor, 1)


def patch_connectability(text: str) -> str:
    if CONNECTABILITY_MARKER in text:
        return text
    return replace_method(text, CONNECTABLE_SIGNATURE, NEW_CONNECTABLE)


def patch_unknown_setup(text: str) -> str:
    if UNKNOWN_SETUP_MARKER in text:
        return text

    old_empty = """        if (TextUtils.isEmpty(security)) {
            security = OPEN;
            Log.w(TAG, "Empty security, assuming open");
        }"""
    new_empty = """        if (TextUtils.isEmpty(security)) {
            security = UNKNOWN;
            Log.w(TAG, "N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED empty security");
        }"""
    if text.count(old_empty) != 1:
        raise RuntimeError("could not find empty-security fallback")
    text = text.replace(old_empty, new_empty, 1)

    old_open = """        } else if (security.equals(OPEN)) {
            config.allowedAuthAlgorithms.set(AuthAlgorithm.OPEN);
            config.allowedKeyManagement.set(KeyMgmt.NONE);
        }"""
    new_open = """        } else if (security.equals(OPEN)) {
            config.allowedAuthAlgorithms.set(AuthAlgorithm.OPEN);
            config.allowedKeyManagement.set(KeyMgmt.NONE);
        } else {
            /* N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED: never turn an
             * unclassified scan result into an open network configuration. */
            Log.w(TAG, "N3DS_SETTINGS_UNKNOWN_SECURITY_FAIL_CLOSED security="
                    + security);
        }"""
    if text.count(old_open) != 1:
        raise RuntimeError("could not find OPEN setup branch")
    return text.replace(old_open, new_open, 1)


def patch_wpa_group_ciphers(text: str) -> str:
    """Remove WEP group ciphers only from the PSK/EAP setup branches."""
    setup = "private void setupSecurity(WifiConfiguration config)"
    if setup not in text:
        raise RuntimeError("could not find setupSecurity for WPA cipher repair")
    start = text.index(setup)
    brace = text.index("{", start)
    depth = 0
    end = None
    for pos in range(brace, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                end = pos + 1
                break
    if end is None:
        raise RuntimeError("unclosed setupSecurity method")
    before, method, after = text[:start], text[start:end], text[end:]
    if WPA_GROUP_MARKER in method:
        return text

    legacy = """            config.allowedGroupCiphers.set(GroupCipher.WEP40);
            config.allowedGroupCiphers.set(GroupCipher.WEP104);
            config.allowedGroupCiphers.set(GroupCipher.TKIP);
            config.allowedGroupCiphers.set(GroupCipher.CCMP);"""
    if method.count(legacy) != 2:
        raise RuntimeError(
            "expected legacy WEP/TKIP/CCMP group set in PSK and EAP branches"
        )
    psk = """            /* N3DS_SETTINGS_WPA_GROUP_CIPHERS_V2: wpa_supplicant 2.10
             * rejects the legacy mixed WEP/WPA group set. WPA-PSK/EAP
             * profiles use only TKIP/CCMP; the WEP branch remains separate. */
            config.allowedGroupCiphers.set(GroupCipher.TKIP);
            config.allowedGroupCiphers.set(GroupCipher.CCMP);"""
    method = method.replace(legacy, psk, 1)
    method = method.replace(
        legacy,
        """            config.allowedGroupCiphers.set(GroupCipher.TKIP);
            config.allowedGroupCiphers.set(GroupCipher.CCMP);""",
        1,
    )
    return before + method + after


def patch(text: str) -> str:
    if MARKER not in text:
        if OLD_GET_SECURITY not in text:
            raise RuntimeError("could not find OLD_GET_SECURITY anchor")
        text = text.replace(OLD_GET_SECURITY, NEW_GET_SECURITY, 1)

        if OLD_SETUP_SECURITY not in text:
            raise RuntimeError("could not find OLD_SETUP_SECURITY anchor")
        text = text.replace(OLD_SETUP_SECURITY, NEW_SETUP_SECURITY, 1)

    text = patch_scan_security(text)
    text = patch_protected_evidence(text)
    text = patch_unknown_setup(text)
    text = patch_wpa_group_ciphers(text)
    return patch_connectability(text)


def main() -> None:
    found = False
    for path in PATHS:
        if not path.is_file():
            continue
        found = True
        original = path.read_text(encoding="utf-8")
        updated = patch(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print(f"patch_settings_wifi_security: updated {path}")
        else:
            print(f"patch_settings_wifi_security: already applied to {path}")
    if not found:
        raise SystemExit("missing target files")


if __name__ == "__main__":
    main()
