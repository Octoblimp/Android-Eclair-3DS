"""Actively probe enabled remembered SSIDs before wildcard discovery.

Buildroot applies the generated package patch to clean wpa_supplicant trees.
For incremental developer builds, this script updates the extracted 2.10
source as well.  Explicit SELECT_NETWORK remains first, followed by protected
remembered profiles and then open remembered profiles.
"""
from a3ds_paths import A3DS_ROOT

from difflib import unified_diff
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
WSL_ROOT = Path(A3DS_ROOT)
ROOT = WSL_ROOT if (WSL_ROOT / "third_party").exists() else HERE
BUILDROOT = ROOT / "third_party/buildroot"
SCAN = BUILDROOT / "output/build/wpa_supplicant-2.10/wpa_supplicant/scan.c"
PACKAGE_PATCH = (
    BUILDROOT
    / "package/wpa_supplicant/0004-n3ds-remembered-first-discovery.patch"
)
MARKER = "N3DS_REMEMBERED_FIRST_DISCOVERY"

HELPER_ANCHOR = "\n\nstatic void wpa_supplicant_scan(void *eloop_ctx, void *timeout_ctx)"
HELPER = r'''

/* N3DS_REMEMBERED_FIRST_DISCOVERY: the legacy 32-entry host harvest cache can
 * omit an ordinary remembered AP from a wildcard-only scan. Put enabled
 * saved SSIDs into the active-probe slots before the final wildcard entry.
 * An explicit SELECT_NETWORK is first, followed by protected profiles and
 * then open profiles.  This preserves broad discovery while making the APs
 * the user actually saved the first directed discovery targets. */
static int n3ds_saved_network_is_protected_for_scan(const struct wpa_ssid *ssid)
{
	if (!(ssid->key_mgmt & WPA_KEY_MGMT_NONE))
		return 1;
#ifdef CONFIG_WEP
	return ssid->wep_key_len[0] || ssid->wep_key_len[1] ||
		ssid->wep_key_len[2] || ssid->wep_key_len[3];
#else
	return 0;
#endif
}


static int n3ds_scan_has_ssid(const struct wpa_driver_scan_params *params,
			      const u8 *ssid, size_t ssid_len)
{
	unsigned int i;

	for (i = 0; i < params->num_ssids; i++) {
		if (params->ssids[i].ssid_len == ssid_len &&
		    params->ssids[i].ssid &&
		    os_memcmp(params->ssids[i].ssid, ssid, ssid_len) == 0)
			return 1;
	}
	return 0;
}


static void n3ds_add_one_remembered_scan_ssid(
	struct wpa_driver_scan_params *params, size_t max_ssids,
	struct wpa_ssid *ssid)
{
	if (!ssid || !ssid->ssid || !ssid->ssid_len ||
	    params->num_ssids >= max_ssids ||
	    n3ds_scan_has_ssid(params, ssid->ssid, ssid->ssid_len))
		return;
	params->ssids[params->num_ssids].ssid = ssid->ssid;
	params->ssids[params->num_ssids].ssid_len = ssid->ssid_len;
	params->num_ssids++;
}


static void n3ds_add_remembered_scan_ssids(
	struct wpa_supplicant *wpa_s, struct wpa_driver_scan_params *params,
	size_t max_ssids)
{
	struct wpa_ssid *ssid;
	int protected_pass;

	/* Keep one driver slot for unrestricted discovery. */
	if (max_ssids > 1)
		max_ssids--;

	/* A Settings SELECT_NETWORK request is authoritative, even when open. */
	for (ssid = wpa_s->conf->ssid; ssid; ssid = ssid->next) {
		if (ssid == wpa_s->next_ssid &&
		    !wpas_network_disabled(wpa_s, ssid)) {
			n3ds_add_one_remembered_scan_ssid(params, max_ssids,
							ssid);
			break;
		}
	}

	for (protected_pass = 1; protected_pass >= 0; protected_pass--) {
		for (ssid = wpa_s->conf->ssid; ssid; ssid = ssid->next) {
			if (wpas_network_disabled(wpa_s, ssid) ||
			    n3ds_saved_network_is_protected_for_scan(ssid) !=
			    protected_pass)
				continue;
			n3ds_add_one_remembered_scan_ssid(params, max_ssids,
							ssid);
		}
	}
}
'''

NORMAL_ANCHOR = r'''	} else {
		struct wpa_ssid *start = ssid, *tssid;
		int freqs_set = 0;
'''
NORMAL_REPLACEMENT = r'''	} else {
		struct wpa_ssid *start = ssid, *tssid;
		int freqs_set = 0;

		if (wpa_s->last_scan_req != MANUAL_SCAN_REQ) {
			unsigned int before = params.num_ssids;

			n3ds_add_remembered_scan_ssids(wpa_s, &params,
							 max_ssids);
			if (params.num_ssids != before)
				wpa_dbg(wpa_s, MSG_DEBUG,
					"N3DS: remembered-first directed scan: %u saved SSID(s) before wildcard discovery",
					params.num_ssids - before);
		}
'''

OLD_SCAN_SSID = r'''			if (!wpas_network_disabled(wpa_s, ssid) &&
			    ssid->scan_ssid) {
'''
NEW_SCAN_SSID = r'''			if (!wpas_network_disabled(wpa_s, ssid) &&
			    ssid->scan_ssid &&
			    !n3ds_scan_has_ssid(&params, ssid->ssid,
						 ssid->ssid_len)) {
'''


def transformed(original: str) -> str:
    if MARKER in original:
        return original.replace(
            "AR6014's private 32-entry target table can\n"
            " * omit an ordinary remembered AP from a wildcard-only scan.  Put enabled",
            "the legacy 32-entry host harvest cache can\n"
            " * omit an ordinary remembered AP from a wildcard-only scan. Put enabled",
            1,
        )
    if original.count(HELPER_ANCHOR) != 1:
        raise RuntimeError("scan function anchor changed")
    if original.count(NORMAL_ANCHOR) != 1:
        raise RuntimeError("normal scan block changed")
    if original.count(OLD_SCAN_SSID) != 1:
        raise RuntimeError("saved SSID scan block changed")
    text = original.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)
    text = text.replace(NORMAL_ANCHOR, NORMAL_REPLACEMENT, 1)
    return text.replace(OLD_SCAN_SSID, NEW_SCAN_SSID, 1)


def main() -> None:
    if not SCAN.is_file():
        # Clean-tree path: the source was removed so Buildroot will re-extract
        # and reapply all package patches including 0004.  Succeed as long as
        # the package patch file exists.
        if not PACKAGE_PATCH.is_file():
            raise SystemExit(
                f"missing package patch {PACKAGE_PATCH} and source "
                f"tree not yet extracted; cannot ensure patch will be applied"
            )
        print(
            "patch_wpa_remembered_discovery: source not yet extracted; "
            "package patch present and will be applied by Buildroot"
        )
        return
    original = SCAN.read_text()
    updated = transformed(original)
    if MARKER in original and original != updated:
        if not PACKAGE_PATCH.is_file():
            raise SystemExit("source is patched but package patch is missing")
        package_text = PACKAGE_PATCH.read_text().replace(
            "AR6014's private 32-entry target table can\n"
            "+ * omit an ordinary remembered AP from a wildcard-only scan.  Put enabled",
            "the legacy 32-entry host harvest cache can\n"
            "+ * omit an ordinary remembered AP from a wildcard-only scan. Put enabled",
            1,
        )
        PACKAGE_PATCH.write_text(package_text)
        SCAN.write_text(updated)
        print(f"patch_wpa_remembered_discovery: refreshed {PACKAGE_PATCH}")
        print(f"patch_wpa_remembered_discovery: updated {SCAN}")
        return
    if original == updated:
        if not PACKAGE_PATCH.is_file():
            raise SystemExit("source is patched but package patch is missing")
        print("patch_wpa_remembered_discovery: already applied")
        return
    diff = "".join(
        unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/wpa_supplicant/scan.c",
            tofile="b/wpa_supplicant/scan.c",
        )
    )
    PACKAGE_PATCH.parent.mkdir(parents=True, exist_ok=True)
    PACKAGE_PATCH.write_text(diff)
    SCAN.write_text(updated)
    print(f"patch_wpa_remembered_discovery: wrote {PACKAGE_PATCH}")
    print(f"patch_wpa_remembered_discovery: updated {SCAN}")


if __name__ == "__main__":
    main()
