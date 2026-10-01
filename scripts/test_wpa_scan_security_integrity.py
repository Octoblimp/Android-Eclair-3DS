#!/usr/bin/env python3
"""Regression cases for raw privacy/IE evidence at the supplicant boundary."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/patch_wpa_scan_security_integrity.py"

SYNTHETIC_CTRL = r'''#include "bss.h"
static int wpa_supplicant_ctrl_iface_scan_result(
        struct wpa_supplicant *wpa_s, const struct wpa_bss *bss,
        char *buf, size_t buflen)
{
        char *pos = buf, *end = buf + buflen;
        int ret;
        const u8 *ie = NULL, *ie2 = NULL, *osen_ie = NULL;
        pos = wpa_supplicant_wps_ie_txt(wpa_s, pos, end, bss);
        if (!ie && !ie2 && !osen_ie && (bss->caps & IEEE80211_CAP_PRIVACY)) {
                ret = os_snprintf(pos, end - pos, "[WEP]");
                if (os_snprintf_error(end - pos, ret))
                        return -1;
                pos += ret;
        }
        return (int)(pos - buf);
}
'''


def load_patch_module():
    spec = importlib.util.spec_from_file_location("wpa_scan_security_patch", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify(flags: str) -> str:
    upper = flags.upper()
    if "N3DS-SECURITY-UNKNOWN" in upper:
        return "Unknown"
    if "IEEE8021X" in upper or "-EAP" in upper:
        return "EAP"
    if "RSN" in upper or "WPA" in upper or "PSK" in upper:
        return "PSK"
    if "WEP" in upper or "PRIVACY" in upper:
        return "WEP"
    if upper == "[ESS]":
        return "Open"
    return "Unknown"


def render_flags(privacy: bool, ies):
    """Small model of the bounded raw-IE walk used by the C patch."""
    flags = "[N3DS-PRIVACY]" if privacy else ""
    malformed = False
    has_security = False
    for kind, declared_len, available_len, parse_ok in ies:
        if kind == "RSN":
            flags += "[N3DS-RSN-RAW]"
            has_security = True
        elif kind == "WPA":
            flags += "[N3DS-WPA-RAW]"
            has_security = True
        if declared_len > available_len or not parse_ok:
            malformed = True
    if has_security and not privacy:
        malformed = True
    if malformed:
        flags += "[N3DS-SECURITY-UNKNOWN]"
    return flags + "[ESS]"


def main():
    module = load_patch_module()
    original = (module.CTRL.read_text(encoding="utf-8")
                if module.CTRL.is_file() else SYNTHETIC_CTRL)
    patched = module.transformed(original)
    assert module.MARKER in patched
    assert module.CURRENT_MARKER in patched
    assert "n3ds_scan_security_evidence" in patched
    assert "N3DS-PRIVACY" in patched
    assert "N3DS-WPA-RAW" in patched
    assert "N3DS-RSN-RAW" in patched
    assert "N3DS-SECURITY-UNKNOWN" in patched
    assert "wpa_parse_wpa_ie(ie, ie_len, &data)" in patched
    assert "bss->caps & IEEE80211_CAP_PRIVACY" in patched
    assert patched == module.transformed(patched)

    legacy = patched.replace(module.CURRENT_MARKER, "legacy-v1", 1)
    migrated = module.transformed(legacy)
    assert module.CURRENT_MARKER in migrated
    assert migrated.count("n3ds_scan_security_evidence") == 2
    assert migrated == module.transformed(migrated)

    cases = [
        (render_flags(False, []), "Open"),  # genuine open
        (render_flags(True, []), "WEP"),  # WEP/privacy-only
        (render_flags(True, [("RSN", 20, 20, True)]), "PSK"),  # valid RSN
        (render_flags(True, [("WPA", 6, 6, True)]), "PSK"),  # valid WPA
        (render_flags(True, [("RSN", 20, 20, False)]), "Unknown"),
        # tlc6efe7: outer RSN length is present, but inner key-mgmt parsing fails.
        (render_flags(True, [("RSN", 20, 8, True)]), "Unknown"),
        (render_flags(False, [("RSN", 20, 20, True)]), "Unknown"),
        (render_flags(False, [("WPA", 6, 6, True)]), "Unknown"),
    ]
    for flags, expected in cases:
        assert classify(flags) == expected, (flags, expected)

    # The formatter must not make a genuine open result look protected merely
    # because the privacy marker exists in the source implementation.
    open_case = "[ESS]"
    assert "N3DS-PRIVACY" not in open_case
    assert classify(open_case) == "Open"
    print("wpa_scan_security_integrity: PASS")


if __name__ == "__main__":
    main()
