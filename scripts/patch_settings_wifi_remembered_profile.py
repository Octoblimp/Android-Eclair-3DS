#!/usr/bin/env python3
"""Make Settings reuse an exact saved Wi-Fi profile without exposing secrets.

The legacy Settings UI decides whether to show a password field from the
scan-row's ``hasPassword`` bit.  A saved WPA profile can be represented by a
masked/empty key, or can temporarily fail to merge with the scan row when the
security classifier changes.  In either case the UI can ask for a password
even though WifiLayer can already find the exact configured network.

This patch adds one authority for that decision: a dedicated WifiLayer lookup
that compares the explicit quoted SSID and canonical security class without
depending on transient scan network ID/BSSID merge state.  It updates only the
in-memory AccessPointState, and leaves the existing enable/priority/save path
responsible for persistent wpa_supplicant.conf synchronisation.  A failed-auth
retry remains a genuine password retry.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import re


ROOT = Path(A3DS_ROOT)
WIFI_DIR = ROOT / "third_party/settings/src/com/android/settings/wifi"
PATHS = {
    "layer": WIFI_DIR / "WifiLayer.java",
    "settings": WIFI_DIR / "WifiSettings.java",
    "dialog": WIFI_DIR / "AccessPointDialog.java",
}

LAYER_MARKER = "N3DS_SETTINGS_REMEMBERED_PROFILE_REUSE"
SETTINGS_PROMPT_MARKER = "N3DS_SETTINGS_REMEMBERED_PROFILE_PROMPT"
DIALOG_MARKER = "N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT"
VERSION_MARKER = "N3DS_SETTINGS_REMEMBERED_PROFILE_V2"
VERSION_MARKER_V3 = "N3DS_SETTINGS_REMEMBERED_PROFILE_V3"
VERSION_MARKER_V4 = "N3DS_SETTINGS_REMEMBERED_PROFILE_V4"
ROW_CONNECT_MARKER = "N3DS_SETTINGS_REMEMBERED_PROFILE_ROW_CONNECT"
ROW_MARKER = "N3DS_SETTINGS_REMEMBERED_PROFILE_ROW_RESOLVE"
UNKNOWN_SCAN_MERGE_MARKER = "N3DS_SETTINGS_UNKNOWN_SCAN_REMEMBERED_MERGE"
UNKNOWN_SCAN_CURRENT_MARKER = "N3DS_SETTINGS_SCAN_ROWS_V5"
UNKNOWN_SCAN_RESOLVED_MARKER = "N3DS_SETTINGS_SAVED_SCAN_SECURITY_RESOLVED="
UNKNOWN_SCAN_SUPPRESSED_MARKER = "N3DS_SETTINGS_UNCLASSIFIED_SCAN_SUPPRESSED"
NO_REPROMPT_LOG = 'Log.i(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT");'


def replace_method(text: str, signature: str, replacement: str) -> str:
    """Replace one Java method, including its signature and balanced body."""
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
                end = pos + 1
                break
    if end is None:
        raise RuntimeError("unclosed method: " + signature)
    return text[:start] + replacement + text[end:]


def method_bounds(text: str, signature: str):
    """Return the half-open range of a Java method identified by signature."""
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 0
    for pos in range(brace, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return start, pos + 1
    raise RuntimeError("unclosed method: " + signature)


LAYER_COMPATIBLE_METHOD = r'''    /**
     * Returns true only when this scan row matches an existing configured
     * network by its explicit quoted SSID and canonical security class.  Do
     * not use findConfiguredNetwork() here: an unmerged scan row can still
     * carry NETWORK_ID_NOT_SET or a different BSSID.  The configuration's
     * secret is never copied into AccessPointState or logged.
     */
    public boolean hasCompatibleConfiguredNetwork(AccessPointState state) {
         /* N3DS_SETTINGS_REMEMBERED_PROFILE_MATCH_GUARD: compatibility is
         * N3DS_SETTINGS_REMEMBERED_PROFILE_V2 and is deliberately
         * independent of network ID/BSSID so a scan row that
         * has not merged into the saved row can still reuse its profile. */
        // A protected saved row can be marked primary while supplicant is
        // ASSOCIATING. That transient UI state must not hide its persisted
        // profile and force a bogus password prompt.
        if (state == null || !state.seen ||
                TextUtils.isEmpty(state.ssid) ||
                TextUtils.isEmpty(state.security) ||
                AccessPointState.UNKNOWN.equals(state.security)) {
            Log.w(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_MISS");
            return false;
        }

        final List<WifiConfiguration> wifiConfigs = getConfiguredNetworks();
        for (int i = wifiConfigs.size() - 1; i >= 0; i--) {
            final WifiConfiguration config = wifiConfigs.get(i);
            if (config == null || !state.ssid.equals(config.SSID)) {
                continue;
            }
            final String configuredSecurity =
                    AccessPointState.getWifiConfigurationSecurity(config);
            if (!state.security.equals(configuredSecurity)) {
                continue;
            }

            /* Populate only non-secret profile metadata so the dialog renders
             * the row as configured.  The existing connectToNetwork() path
             * then updates/enables/saves this same config without replacing
             * its key. */
            state.updateFromWifiConfiguration(config);
            Log.i(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_REUSE security=" +
                    state.security);
            return true;
        }

        Log.w(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_MISS");
        return false;
    }

'''

LAYER_SSID_METHOD = r'''    /**
     * Detects a saved profile with the same SSID but a different security
     * class.  This is only a change/confirmation signal; it never authorizes
     * copying that profile's protected key into the selected state.
     */
    public boolean hasConfiguredNetworkForSsid(AccessPointState state) {
        if (state == null || TextUtils.isEmpty(state.ssid)) {
            return false;
        }
        final List<WifiConfiguration> wifiConfigs = getConfiguredNetworks();
        for (int i = wifiConfigs.size() - 1; i >= 0; i--) {
            final WifiConfiguration wifiConfig = wifiConfigs.get(i);
            if (wifiConfig != null && state.ssid.equals(wifiConfig.SSID)) {
                return true;
            }
        }
        return false;
    }

'''

LAYER_UNKNOWN_SCAN_METHOD = r'''    /* N3DS_SETTINGS_UNKNOWN_SCAN_REMEMBERED_MERGE:
     * An UNKNOWN scan remains non-open.  When the lower layer preserved
     * explicit privacy, RSN, or WPA evidence, it may be merged with an
     * already configured protected row for the exact same quoted SSID.  The
     * existing state object retains its security/key metadata; credentials
     * are never copied or logged. */
    private static boolean isKnownProtectedSecurity(String security) {
        return !TextUtils.isEmpty(security) &&
                !AccessPointState.UNKNOWN.equals(security) &&
                !AccessPointState.OPEN.equals(security);
    }

    private static String mergeRememberedProtectedSecurityLocked(
            List<AccessPointState> list, String ssid, String candidate) {
        for (int i = list.size() - 1; i >= 0; i--) {
            final AccessPointState ap = list.get(i);
            if (ap != null && ap.configured && ssid.equals(ap.ssid) &&
                    isKnownProtectedSecurity(ap.security)) {
                if (candidate != null &&
                        !candidate.equals(ap.security)) {
                    /* UNKNOWN evidence cannot distinguish conflicting saved
                     * security classes for one SSID.  Reject the resolution;
                     * the caller suppresses this unclassified scan row. */
                    return AccessPointState.UNKNOWN;
                }
                candidate = ap.security;
            }
        }
        return candidate;
    }

    private static AccessPointState findConfiguredProtectedApLocked(
            List<AccessPointState> list, String ssid, String security) {
        for (int i = list.size() - 1; i >= 0; i--) {
            final AccessPointState ap = list.get(i);
            if (ap != null && ap.configured && ssid.equals(ap.ssid) &&
                    security.equals(ap.security)) {
                return ap;
            }
        }
        return null;
    }

    private AccessPointState findUniqueRememberedProtectedApLocked(
            List<AccessPointState> newScanList, String ssid) {
        String security = mergeRememberedProtectedSecurityLocked(
                newScanList, ssid, null);
        security = mergeRememberedProtectedSecurityLocked(
                mApScanList, ssid, security);
        if (AccessPointState.UNKNOWN.equals(security)) return null;
        security = mergeRememberedProtectedSecurityLocked(
                mApOtherList, ssid, security);
        if (TextUtils.isEmpty(security) ||
                AccessPointState.UNKNOWN.equals(security)) return null;

        AccessPointState ap = findConfiguredProtectedApLocked(
                newScanList, ssid, security);
        if (ap == null) {
            ap = findConfiguredProtectedApLocked(mApScanList, ssid, security);
        }
        if (ap == null) {
            ap = findConfiguredProtectedApLocked(mApOtherList, ssid, security);
        }
        return ap;
    }

'''

LAYER_UNKNOWN_SCAN_BLOCK_OLD = r'''                    final String ssid = AccessPointState.convertToQuotedString(scanResult.SSID);
                    String security = AccessPointState.getScanResultSecurity(scanResult);
                    
                    // See if this AP is part of a group of APs (e.g., any large
                    // wifi network has many APs, we'll only show one) that we've
                    // seen in this scan
                    AccessPointState ap = findApLocked(newScanList, AccessPointState.NETWORK_ID_ANY,
                                                 AccessPointState.BSSID_ANY, ssid, security);
'''

LAYER_UNKNOWN_SCAN_BLOCK_V4 = r'''                    final String ssid = AccessPointState.convertToQuotedString(scanResult.SSID);
                    final String security = AccessPointState.getScanResultSecurity(scanResult);
                    final boolean unknownProtectedEvidence =
                            AccessPointState.UNKNOWN.equals(security) &&
                            AccessPointState.hasProtectedCapabilityEvidence(scanResult);

                    /* Link a degraded scan only to an existing configured
                     * protected row with an exact quoted SSID.  Token-less
                     * UNKNOWN rows retain the fail-closed behavior below. */
                    AccessPointState ap = null;
                    if (unknownProtectedEvidence) {
                        ap = findUniqueRememberedProtectedApLocked(
                                newScanList, ssid);
                        if (ap != null) {
                            Log.i(TAG, "N3DS_SETTINGS_UNKNOWN_SCAN_REMEMBERED_MERGE");
                        }
                    }

                    // See if this AP is part of a group of APs (e.g., any large
                    // wifi network has many APs, we'll only show one) that we've
                    // seen in this scan
                    if (ap == null) {
                        ap = findApLocked(newScanList, AccessPointState.NETWORK_ID_ANY,
                                                 AccessPointState.BSSID_ANY, ssid, security);
                    }
'''

LAYER_UNKNOWN_SCAN_BLOCK_NEW = r'''                    final String ssid = AccessPointState.convertToQuotedString(scanResult.SSID);
                    final String reportedSecurity =
                            AccessPointState.getScanResultSecurity(scanResult);
                    final boolean unknownProtectedEvidence =
                            AccessPointState.UNKNOWN.equals(reportedSecurity) &&
                            AccessPointState.hasProtectedCapabilityEvidence(scanResult);
                    AccessPointState rememberedAp = null;
                    String security = reportedSecurity;

                    /* N3DS_SETTINGS_SCAN_ROWS_V5: an unclassified scan is
                     * never a displayable security type.  Resolve it only
                     * through one exact, unambiguous saved protected profile;
                     * otherwise suppress it before any UI callback. */
                    if (AccessPointState.UNKNOWN.equals(reportedSecurity)) {
                        if (unknownProtectedEvidence) {
                            rememberedAp = findUniqueRememberedProtectedApLocked(
                                    newScanList, ssid);
                        }
                        if (rememberedAp == null) {
                            Log.w(TAG, "N3DS_SETTINGS_UNCLASSIFIED_SCAN_SUPPRESSED");
                            continue;
                        }
                        security = rememberedAp.security;
                        Log.i(TAG,
                                "N3DS_SETTINGS_SAVED_SCAN_SECURITY_RESOLVED=" +
                                security);
                    }

                    // See if this AP is part of a group of APs (e.g., any large
                    // wifi network has many APs, we'll only show one) that we've
                    // seen in this scan.  Only rows actually inserted into
                    // newScanList count as already seen in this scan.
                    AccessPointState ap = findApLocked(newScanList,
                            AccessPointState.NETWORK_ID_ANY,
                            AccessPointState.BSSID_ANY, ssid, security);
'''

LAYER_UNKNOWN_SCAN_LOOKUP_OLD = r'''                    // Find the AP in either our old scan list, or our non-seen
                    // configured networks list
                    ap = findApLocked(AccessPointState.NETWORK_ID_ANY, AccessPointState.BSSID_ANY,
                                ssid, security);
'''

LAYER_UNKNOWN_SCAN_LOOKUP_NEW = r'''                    // Reuse the resolved saved row first.  The old implementation
                    // returned this object before it had entered newScanList,
                    // then mistook it for a duplicate and skipped seen/UI updates.
                    ap = rememberedAp;
                    if (ap == null) {
                        // Find the AP in either our old scan list, or our non-seen
                        // configured networks list.
                        ap = findApLocked(AccessPointState.NETWORK_ID_ANY,
                                AccessPointState.BSSID_ANY, ssid, security);
                    }
'''

LAYER_UNKNOWN_SCAN_UPDATE_OLD = r'''                    // Give it the latest state
                    ap.updateFromScanResult(scanResult);
'''

LAYER_UNKNOWN_SCAN_UPDATE_V4 = r'''                    // Give it the latest state.  A remembered protected
                    // class survives an UNKNOWN scan only when the evidence
                    // guard selected the row above.
                    final String rememberedSecurity =
                            (ap.configured && isKnownProtectedSecurity(ap.security))
                            ? ap.security : null;
                    ap.updateFromScanResult(scanResult);
                    if (rememberedSecurity != null && unknownProtectedEvidence &&
                            AccessPointState.UNKNOWN.equals(ap.security)) {
                        ap.setSecurity(rememberedSecurity);
                        Log.i(TAG,
                                "N3DS_SETTINGS_UNKNOWN_SCAN_REMEMBERED_SECURITY=" +
                                rememberedSecurity);
                    }
'''

LAYER_UNKNOWN_SCAN_UPDATE_NEW = r'''                    // Give it the latest state, then restore the effective class
                    // selected above.  For ordinary parsed results these are
                    // identical; for an exact saved-profile resolution this
                    // prevents the diagnostic UNKNOWN value reaching the UI.
                    ap.updateFromScanResult(scanResult);
                    if (!security.equals(ap.security)) {
                        ap.setSecurity(security);
                    }
'''


def patch_layer(text: str) -> str:
    if VERSION_MARKER in text:
        old_guard = "if (state == null || !state.isConnectable() ||\n"
        if old_guard in text:
            new_guard = (
                "// A protected saved row can be marked primary while "
                "supplicant is\n"
                "        // ASSOCIATING. That transient UI state must not "
                "hide its persisted\n"
                "        // profile and force a bogus password prompt.\n"
                "        if (state == null || !state.seen ||\n"
            )
            if text.count(old_guard) != 1:
                raise RuntimeError("remembered-profile transient guard count: " +
                                   str(text.count(old_guard)))
            text = text.replace(old_guard, new_guard, 1)
        if "if (state == null || !state.seen ||" not in text:
            raise RuntimeError("unknown remembered-profile v2 guard")
        text = patch_connect_action_guard(text)
        return patch_unknown_scan_merge(text)
    signature = "public boolean hasCompatibleConfiguredNetwork(AccessPointState state)"
    anchor = "    public boolean connectToNetwork(AccessPointState state) {\n"
    if signature in text:
        text = replace_method(text, signature, LAYER_COMPATIBLE_METHOD)
    else:
        if text.count(anchor) != 1:
            raise RuntimeError("remembered-profile layer anchor count: " +
                               str(text.count(anchor)))
        text = text.replace(anchor, LAYER_COMPATIBLE_METHOD +
                            LAYER_SSID_METHOD + anchor, 1)

    if "public boolean hasConfiguredNetworkForSsid(AccessPointState state)" not in text:
        if text.count(anchor) != 1:
            raise RuntimeError("remembered-profile SSID helper anchor count: " +
                               str(text.count(anchor)))
        text = text.replace(anchor, LAYER_SSID_METHOD + anchor, 1)
    return patch_unknown_scan_merge(patch_connect_action_guard(text))


def patch_unknown_scan_merge(text: str) -> str:
    if UNKNOWN_SCAN_CURRENT_MARKER in text:
        required = (
            "AccessPointState.hasProtectedCapabilityEvidence(scanResult)",
            UNKNOWN_SCAN_RESOLVED_MARKER,
            UNKNOWN_SCAN_SUPPRESSED_MARKER,
            "ap = rememberedAp;",
        )
        if not all(token in text for token in required):
            raise RuntimeError("scan-row v5 marker is incomplete")
        return text

    anchor = "    private void handleScanResultsAvailable() {\n"
    if text.count(anchor) != 1:
        raise RuntimeError("unknown-scan merge handler anchor changed")
    if UNKNOWN_SCAN_MERGE_MARKER not in text:
        text = text.replace(anchor, LAYER_UNKNOWN_SCAN_METHOD + anchor, 1)

    if text.count(LAYER_UNKNOWN_SCAN_BLOCK_V4) == 1:
        text = text.replace(LAYER_UNKNOWN_SCAN_BLOCK_V4,
                            LAYER_UNKNOWN_SCAN_BLOCK_NEW, 1)
    elif text.count(LAYER_UNKNOWN_SCAN_BLOCK_OLD) == 1:
        text = text.replace(LAYER_UNKNOWN_SCAN_BLOCK_OLD,
                            LAYER_UNKNOWN_SCAN_BLOCK_NEW, 1)
    else:
        raise RuntimeError("unknown-scan merge scan block changed")

    if text.count(LAYER_UNKNOWN_SCAN_LOOKUP_OLD) != 1:
        raise RuntimeError("unknown-scan remembered lookup changed")
    text = text.replace(LAYER_UNKNOWN_SCAN_LOOKUP_OLD,
                        LAYER_UNKNOWN_SCAN_LOOKUP_NEW, 1)

    if text.count(LAYER_UNKNOWN_SCAN_UPDATE_V4) == 1:
        return text.replace(LAYER_UNKNOWN_SCAN_UPDATE_V4,
                            LAYER_UNKNOWN_SCAN_UPDATE_NEW, 1)
    if text.count(LAYER_UNKNOWN_SCAN_UPDATE_OLD) == 1:
        return text.replace(LAYER_UNKNOWN_SCAN_UPDATE_OLD,
                            LAYER_UNKNOWN_SCAN_UPDATE_NEW, 1)
    raise RuntimeError("unknown-scan merge update block changed")


def patch_connect_action_guard(text: str) -> str:
    """Permit an explicit retry of a seen AP during stale ASSOCIATING state."""
    if VERSION_MARKER_V4 in text:
        return text
    signature = "    public boolean connectToNetwork(AccessPointState state)"
    start, end = method_bounds(text, signature)
    method = text[start:end]
    old = """        if (state == null || !state.isConnectable()) {
            Log.w(TAG, "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE");
            return false;
        }
"""
    new = """        /* N3DS_SETTINGS_REMEMBERED_PROFILE_V4: an explicit row
         * selection may retry a seen, classified AP while the framework still
         * labels the previous attempt primary/ASSOCIATING.  That transient
         * flag must not turn the action into a cancel-only dialog. */
        if (state == null || !state.seen || TextUtils.isEmpty(state.security) ||
                AccessPointState.UNKNOWN.equals(state.security)) {
            Log.w(TAG, "N3DS_SETTINGS_UNKNOWN_NOT_CONNECTABLE");
            return false;
        }
"""
    if old not in method:
        raise RuntimeError("remembered-profile connect guard shape changed")
    method = method.replace(old, new, 1)
    return text[:start] + method + text[end:]


SETTINGS_CONNECT = r'''    /* N3DS_SETTINGS_REMEMBERED_PROFILE_V2: resolve saved profiles through
     * WifiLayer before deciding whether a credential dialog is needed. */
    private void connectToNetwork(AccessPointState state) {
        if (state == null) {
            return;
        }
        final boolean compatible =
                mWifiLayer.hasCompatibleConfiguredNetwork(state);
        final boolean changedSecurity = !compatible &&
                mWifiLayer.hasConfiguredNetworkForSsid(state);
        if ((state.hasSecurity() && !compatible) || changedSecurity) {
            Log.i(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_PROMPT");
            showAccessPointDialog(state, AccessPointDialog.MODE_INFO);
        } else {
            Log.i(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_CONNECT");
            mWifiLayer.connectToNetwork(state);
        }
    }'''


def patch_settings(text: str) -> str:
    # A complete v2 source is an idempotent no-op.  The older broad markers
    # are deliberately not treated as final: the v1 helper can still depend
    # on network-id/BSSID merging and must be upgraded below.
    if VERSION_MARKER_V4 in text:
        return patch_row_click_action(text)

    if VERSION_MARKER not in text:
        signature = "    private void connectToNetwork(AccessPointState state)"
        if signature not in text:
            raise RuntimeError("remembered-profile Settings connect method missing")
        text = replace_method(text, signature, SETTINGS_CONNECT)

    # A normal row click opens MODE_INFO.  Resolve the exact saved profile
    # before constructing that dialog so its password field is hidden even
    # when the scan row arrived without the masked key/configured bit.
    if ROW_MARKER not in text:
        text = patch_row_click(text)

    if SETTINGS_PROMPT_MARKER not in text:
        raise RuntimeError("remembered-profile Settings prompt marker missing")
    return patch_row_click_action(text)


def patch_row_click_action(text: str) -> str:
    """Make row selection perform the requested connection action.

    Preserve the legacy information dialog only for an actually CONNECTED AP;
    a stale primary/ASSOCIATING row must be retryable and a saved protected
    row must reuse its configuration without opening a password-less dialog.
    """
    if VERSION_MARKER_V4 in text and ROW_CONNECT_MARKER in text:
        return text
    start, end = method_bounds(text, "onPreferenceTreeClick(")
    method = text[start:end]
    if VERSION_MARKER_V4 in text:
        old = "        connectToNetwork(state);"
        new = ("        Log.i(TAG, \"" + ROW_CONNECT_MARKER + "\");\n" + old)
        if method.count(old) != 1:
            raise RuntimeError("remembered-profile V4 row connect shape changed")
        method = method.replace(old, new, 1)
        return text[:start] + method + text[end:]
    pattern = re.compile(
        r"(?P<indent>[ \t]*)/\* N3DS_SETTINGS_REMEMBERED_PROFILE_ROW_RESOLVE:.*?"
        r"showAccessPointDialog\s*\(\s*state\s*,\s*AccessPointDialog\.MODE_INFO\s*\)\s*;",
        re.S,
    )
    match = pattern.search(method)
    if match is None:
        raise RuntimeError("remembered-profile row action block missing")
    indent = match.group("indent")
    replacement = (
        indent + "/* N3DS_SETTINGS_REMEMBERED_PROFILE_V4: selecting a row is a\n" +
        indent + " * connection action unless it is already fully connected. */\n" +
        indent + "if (state != null && state.primary &&\n" +
        indent + "        state.status == android.net.NetworkInfo.DetailedState.CONNECTED) {\n" +
        indent + "    showAccessPointDialog(state, AccessPointDialog.MODE_INFO);\n" +
        indent + "} else {\n" +
        indent + "    Log.i(TAG, \"" + ROW_CONNECT_MARKER + "\");\n" +
        indent + "    connectToNetwork(state);\n" +
        indent + "}"
    )
    method = method[:match.start()] + replacement + method[match.end():]
    return text[:start] + method + text[end:]


def patch_row_click(text: str) -> str:
    """Resolve a saved row before MODE_INFO, tolerating generated formatting.

    The first implementation matched one exact two-line string.  Buildroot's
    Java source may wrap the cast/getter or nest the callback at a different
    indentation level, so the migration is scoped to onPreferenceTreeClick()
    and matches the Java tokens instead of whitespace.  An existing v1
    resolve block is replaced rather than duplicated.
    """
    signature = "onPreferenceTreeClick("
    try:
        method_start, method_end = method_bounds(text, signature)
    except ValueError:
        raise RuntimeError("remembered-profile row-click method missing")

    method = text[method_start:method_end]
    declaration = re.search(
        r"(?m)^(?P<indent>[ \t]*)AccessPointState\s+state\s*=\s*"
        r"(?:\(\s*\(\s*AccessPointPreference\s*\)\s*preference\s*\)\s*"
        r"\.\s*getAccessPointState\s*\(\s*\)|"
        r"[^;\n]*AccessPointPreference[^;\n]*getAccessPointState\s*\(\s*\))\s*;",
        method,
    )
    if declaration is None:
        raise RuntimeError("remembered-profile row-click state anchor missing")

    dialog = re.search(
        r"(?m)^(?P<indent>[ \t]*)showAccessPointDialog\s*\(\s*state\s*,\s*"
        r"AccessPointDialog\.MODE_INFO\s*\)\s*;",
        method[declaration.end():],
    )
    if dialog is None:
        raise RuntimeError("remembered-profile row-click dialog anchor missing")

    dialog_start = declaration.end() + dialog.start()
    indent = declaration.group("indent")
    newline = "\r\n" if "\r\n" in text else "\n"
    insertion = (
        newline + indent + "/* N3DS_SETTINGS_REMEMBERED_PROFILE_ROW_RESOLVE: "
        "make an exact saved" + newline +
        indent + " * profile render as configured before MODE_INFO builds its fields. */" +
        newline + indent + "if (state != null && state.hasSecurity()) {" + newline +
        indent + "    mWifiLayer.hasCompatibleConfiguredNetwork(state);" + newline +
        indent + "}" + newline
    )

    between = method[declaration.end():dialog_start]
    # v1 already inserted this lookup, but without the row marker and often
    # with a wrapped/indented shape.  Replace only that known block; preserve
    # any unexpected statements by inserting the v2 block before them.
    v1_block = re.compile(
        r"\s*if\s*\(\s*state\s*!=\s*null\s*&&\s*state\.hasSecurity\s*\(\s*\)\s*\)\s*\{\s*"
        r"mWifiLayer\.hasCompatibleConfiguredNetwork\s*\(\s*state\s*\)\s*;\s*\}\s*",
        re.S,
    )
    if not between.strip() or v1_block.fullmatch(between):
        replacement = insertion + method[dialog_start:]
        local = method[:declaration.end()] + replacement
    else:
        local = method[:declaration.end()] + insertion + method[declaration.end():]

    return text[:method_start] + local + text[method_end:]


def patch_dialog(text: str) -> str:
    # V2 only marked the source/comment.  The compiled verifier needs the
    # executable marker, so comment-only V2 must migrate to V3.  Only V3 plus
    # the actual Log.i call is a final no-op state.
    if VERSION_MARKER_V3 in text and NO_REPROMPT_LOG in text:
        return text
    signature = "    private void updatePasswordField()"
    if signature not in text:
        raise RuntimeError("remembered-profile dialog password method missing")

    # Keep MODE_RETRY_PASSWORD strict: it is emitted after an authentication
    # failure and must let the user replace a bad key.  MODE_INFO may reuse an
    # exact saved profile even if the supplicant masked its key.
    old = "    private void updatePasswordField() {\n"
    new = """    private void updatePasswordField() {
        /* N3DS_SETTINGS_REMEMBERED_PROFILE_V2: an exact saved
         * profile is resolved before empty-password validation.
         * N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT: an exact saved
         * profile supplies its own protected key.  Never suppress the retry
         * prompt after an authentication failure.
         * N3DS_SETTINGS_REMEMBERED_PROFILE_V3: executable marker follows. */
        final boolean reuseRemembered = mMode != AccessPointDialog.MODE_RETRY_PASSWORD &&
                mState != null && mWifiLayer.hasCompatibleConfiguredNetwork(mState);
        if (reuseRemembered) {
            Log.i(TAG, "N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT");
        }
"""
    if "final boolean reuseRemembered" not in text:
        if text.count(old) != 1:
            raise RuntimeError("remembered-profile dialog method anchor count: " +
                               str(text.count(old)))
        text = text.replace(old, new, 1)
    elif DIALOG_MARKER in text and VERSION_MARKER not in text:
        text = text.replace(
            "/* N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT:",
            "/* N3DS_SETTINGS_REMEMBERED_PROFILE_V2: an exact saved\n"
            "         * profile is resolved before empty-password validation.\n"
            "         * N3DS_SETTINGS_REMEMBERED_PROFILE_NO_REPROMPT:",
            1,
        )

    if VERSION_MARKER_V3 not in text:
        # Preserve the v2 source marker for source/verifier provenance while
        # recording that the executable marker is now installed.
        anchor = "final boolean reuseRemembered"
        start = text.index(anchor)
        line_start = text.rfind("\n", 0, start) + 1
        indent = re.match(r"[ \t]*", text[line_start:]).group(0)
        newline = "\r\n" if "\r\n" in text else "\n"
        text = (text[:line_start] + indent +
                "/* N3DS_SETTINGS_REMEMBERED_PROFILE_V3: executable marker installed. */" +
                newline + text[line_start:])

    # The verifier inspects classes.dex, where comments are discarded.  Keep
    # the marker as a bounded, credential-free runtime log only when an exact
    # saved profile was reused.  MODE_RETRY_PASSWORD leaves reuseRemembered
    # false and therefore never emits this marker.
    if NO_REPROMPT_LOG not in text:
        start = text.index("final boolean reuseRemembered")
        semi = text.index(";", start)
        line_start = text.rfind("\n", 0, start) + 1
        indent = re.match(r"[ \t]*", text[line_start:]).group(0)
        marker = (
            "\n" + indent + "if (reuseRemembered) {\n" +
            indent + "    " + NO_REPROMPT_LOG + "\n" +
            indent + "}"
        )
        text = text[:semi + 1] + marker + text[semi + 1:]

    # Accept either the clean pre-v1 guard or the v1 guard (which already
    # added !reuseRemembered).  Normalize both to the strict form where
    # MODE_RETRY_PASSWORD can never be suppressed by remembered reuse.
    condition = re.compile(
        r"if\s*\(\s*passwordIsEmpty\s*&&\s*"
        r"(?:!reuseRemembered\s*&&\s*)?"
        r"\(\s*!mState\.hasPassword\(\)\s*\|\|\s*"
        r"mMode\s*==\s*MODE_RETRY_PASSWORD\s*\)")
    matches = condition.findall(text)
    if len(matches) != 1:
        raise RuntimeError("remembered-profile dialog password guard count: " +
                           str(len(matches)))
    text = condition.sub(
        "if (passwordIsEmpty && !reuseRemembered &&\n"
        "                (!mState.hasPassword() || mMode == MODE_RETRY_PASSWORD)",
        text,
        count=1,
    )
    if VERSION_MARKER not in text or DIALOG_MARKER not in text:
        raise RuntimeError("remembered-profile dialog v2 marker missing")
    return text


def patch_sources(layer: str, settings: str, dialog: str):
    return patch_layer(layer), patch_settings(settings), patch_dialog(dialog)


def main() -> None:
    missing = [name for name, path in PATHS.items() if not path.is_file()]
    if missing:
        raise SystemExit("missing canonical Settings source(s): " +
                         ", ".join(missing))
    originals = {name: path.read_text(encoding="utf-8")
                 for name, path in PATHS.items()}
    updated = {
        "layer": patch_layer(originals["layer"]),
        "settings": patch_settings(originals["settings"]),
        "dialog": patch_dialog(originals["dialog"]),
    }
    changed = False
    for name, path in PATHS.items():
        if updated[name] != originals[name]:
            path.write_text(updated[name], encoding="utf-8")
            changed = True
            print("patch_settings_wifi_remembered_profile: updated " + str(path))
    if not changed:
        print("patch_settings_wifi_remembered_profile: already applied")


if __name__ == "__main__":
    main()
