#!/usr/bin/env python3
"""Preserve raw 802.11 security evidence in wpa_supplicant scan flags.

The legacy driver supplies privacy in the beacon capability field and the
raw WPA/RSN IEs.  Settings only receives the text flags emitted by
ctrl_iface.c, so a parser failure must never turn a protected BSS into an
empty-capability/open result.
"""
from a3ds_paths import A3DS_ROOT

from difflib import unified_diff
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
WSL_ROOT = Path(A3DS_ROOT)
ROOT = WSL_ROOT if (WSL_ROOT / "third_party").exists() else HERE
BUILDROOT = ROOT / "third_party/buildroot"
CTRL = BUILDROOT / "output/build/wpa_supplicant-2.10/wpa_supplicant/ctrl_iface.c"
PACKAGE_PATCH = BUILDROOT / "package/wpa_supplicant/0005-n3ds-scan-security-integrity.patch"

MARKER = "N3DS_WPA_SCAN_SECURITY_INTEGRITY"
CURRENT_MARKER = "N3DS_WPA_SCAN_SECURITY_INTEGRITY_V2"
SCAN_SIGNATURE = "static int wpa_supplicant_ctrl_iface_scan_result("
WPS_CALL = "wpa_supplicant_wps_ie_txt(wpa_s, pos, end, bss);"

HELPER = r'''/* N3DS_WPA_SCAN_SECURITY_INTEGRITY: retain security evidence even when
 * N3DS_WPA_SCAN_SECURITY_INTEGRITY_V2: validate inner WPA/RSN structure and
 * enforce privacy/security consistency before emitting scan flags.
 * a malformed IE is rejected by wpa_bss_get_ie().  The driver already
 * provided the capability privacy bit and the raw IE blob; this bounded walk
 * never dereferences beyond bss->ie_len + bss->beacon_ie_len.  An outer-valid
 * but internally malformed RSN/WPA IE is still UNKNOWN, not OPEN. */
static void n3ds_scan_security_evidence(const struct wpa_bss *bss,
                                        int *raw_wpa, int *raw_rsn,
                                        int *malformed)
{
	const u8 *ie = (const u8 *) (bss + 1);
	size_t left = bss->ie_len + bss->beacon_ie_len;
	struct wpa_ie_data data;

	*raw_wpa = 0;
	*raw_rsn = 0;
	*malformed = 0;
	while (left >= 2) {
		size_t ie_len = (size_t) ie[1] + 2;
		int security_ie = 0;

		if (ie[0] == WLAN_EID_RSN) {
			*raw_rsn = 1;
			security_ie = 1;
		} else if (ie[0] == WLAN_EID_VENDOR_SPECIFIC) {
			if (left >= 6 && ie[1] >= 4 && ie[2] == 0x00 &&
				ie[3] == 0x50 && ie[4] == 0xf2 && ie[5] == 0x01) {
				*raw_wpa = 1;
				security_ie = 1;
			}
		}

		if (ie_len > left) {
			/* The element header names bytes outside the BSS blob. */
			if (ie[0] == WLAN_EID_RSN ||
				ie[0] == WLAN_EID_VENDOR_SPECIFIC)
				*malformed = 1;
			break;
		}
		if (security_ie && wpa_parse_wpa_ie(ie, ie_len, &data) < 0)
			*malformed = 1;
		ie += ie_len;
		left -= ie_len;
	}
	if (left != 0)
		*malformed = 1;
	/* WPA/RSN without the 802.11 privacy bit is contradictory evidence. */
	if ((*raw_wpa || *raw_rsn) &&
		!(bss->caps & IEEE80211_CAP_PRIVACY))
		*malformed = 1;
}'''

EVIDENCE = r'''
	{
		int n3ds_raw_wpa, n3ds_raw_rsn, n3ds_security_malformed;

		n3ds_scan_security_evidence(bss, &n3ds_raw_wpa,
					    &n3ds_raw_rsn,
					    &n3ds_security_malformed);
		if (bss->caps & IEEE80211_CAP_PRIVACY) {
			ret = os_snprintf(pos, end - pos, "[N3DS-PRIVACY]");
			if (os_snprintf_error(end - pos, ret))
				return -1;
			pos += ret;
		}
		if (n3ds_raw_wpa) {
			ret = os_snprintf(pos, end - pos, "[N3DS-WPA-RAW]");
			if (os_snprintf_error(end - pos, ret))
				return -1;
			pos += ret;
		}
		if (n3ds_raw_rsn) {
			ret = os_snprintf(pos, end - pos, "[N3DS-RSN-RAW]");
			if (os_snprintf_error(end - pos, ret))
				return -1;
			pos += ret;
		}
		if (n3ds_security_malformed) {
			/* Settings treats this marker as UNKNOWN before other evidence. */
			ret = os_snprintf(pos, end - pos,
					  "[N3DS-SECURITY-UNKNOWN]");
			if (os_snprintf_error(end - pos, ret))
				return -1;
			pos += ret;
		}
	}
'''


def remove_previous_version(text: str) -> str:
    """Remove the first marker-bearing helper/evidence block for migration."""
    if MARKER not in text or CURRENT_MARKER in text:
        return text
    signature = text.index(SCAN_SIGNATURE)
    helper = text.find("/* N3DS_WPA_SCAN_SECURITY_INTEGRITY:")
    if helper >= 0 and helper < signature:
        text = text[:helper] + text[signature:]
    scan_start = text.index(SCAN_SIGNATURE)
    evidence = text.find("\n\t{\n\t\tint n3ds_raw_wpa", scan_start)
    if evidence >= 0:
        end = text.index("\n\t}\n", evidence) + len("\n\t}\n")
        text = text[:evidence] + text[end:]
    return text


def transformed(original: str) -> str:
    if (CURRENT_MARKER in original and
            "wpa_parse_wpa_ie(ie, ie_len, &data)" in original):
        return original
    original = remove_previous_version(original)
    if original.count(SCAN_SIGNATURE) != 1:
        raise RuntimeError("scan-result formatter anchor changed")
    if original.count(WPS_CALL) < 1:
        raise RuntimeError("scan-result WPS formatter anchor missing")
    text = original.replace(SCAN_SIGNATURE, HELPER + "\n\n" + SCAN_SIGNATURE, 1)
    scan_start = text.index(SCAN_SIGNATURE)
    wps = text.index(WPS_CALL, scan_start)
    insert_at = text.index(";", wps) + 1
    return text[:insert_at] + EVIDENCE + text[insert_at:]


def main() -> None:
    if not CTRL.is_file():
        if PACKAGE_PATCH.is_file():
            print("patch_wpa_scan_security_integrity: source not extracted; package patch present")
            return
        raise SystemExit(
            f"missing {CTRL}; cannot generate {PACKAGE_PATCH} from the canonical source"
        )

    original = CTRL.read_text(encoding="utf-8")
    updated = transformed(original)
    if original == updated:
        if not PACKAGE_PATCH.is_file():
            raise SystemExit("wpa source is patched but package patch is missing")
        print("patch_wpa_scan_security_integrity: already applied")
        return

    diff = "".join(unified_diff(
        original.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile="a/wpa_supplicant/ctrl_iface.c",
        tofile="b/wpa_supplicant/ctrl_iface.c",
    ))
    PACKAGE_PATCH.parent.mkdir(parents=True, exist_ok=True)
    PACKAGE_PATCH.write_text(diff, encoding="utf-8")
    CTRL.write_text(updated, encoding="utf-8")
    print(f"patch_wpa_scan_security_integrity: wrote {PACKAGE_PATCH}")
    print(f"patch_wpa_scan_security_integrity: updated {CTRL}")


if __name__ == "__main__":
    main()
