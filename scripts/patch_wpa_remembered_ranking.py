"""Prefer protected remembered networks, then the best sorted scan result.

Buildroot applies the generated package patch to clean wpa_supplicant trees.
For incremental developer builds, this script also updates the already
extracted source tree.  It intentionally keeps next_ssid (SELECT_NETWORK)
ahead of automatic selection so an explicit Settings choice still wins.
"""
from a3ds_paths import A3DS_ROOT

from difflib import unified_diff
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
WSL_ROOT = Path(A3DS_ROOT)
ROOT = WSL_ROOT if (WSL_ROOT / "third_party").exists() else HERE
BUILDROOT = ROOT / "third_party/buildroot"
PACKAGE_PATCH = (
    BUILDROOT
    / "package/wpa_supplicant/0003-n3ds-remembered-network-ranking.patch"
)
EVENTS = BUILDROOT / "output/build/wpa_supplicant-2.10/wpa_supplicant/events.c"
MARKER = "N3DS_REMEMBERED_NETWORK_RANKING"

HELPER_ANCHOR = "\n\nstruct wpa_bss * wpa_supplicant_pick_network("
OLD_PROTECTION = r'''static int n3ds_saved_network_is_protected(const struct wpa_ssid *ssid)
{
	return !(ssid->key_mgmt & WPA_KEY_MGMT_NONE) ||
		ssid->wep_key_len[0] || ssid->wep_key_len[1] ||
		ssid->wep_key_len[2] || ssid->wep_key_len[3];
}
'''
PROTECTION = r'''static int n3ds_saved_network_is_protected(const struct wpa_ssid *ssid)
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
'''
HELPER = r'''

/* N3DS_REMEMBERED_NETWORK_RANKING: Android's Settings increments profile
 * priority when a network is selected.  That makes recency override radio
 * quality forever.  Automatic selection instead considers all enabled saved
 * profiles together: protected profiles first, then the scan-result order
 * (which wpa_supplicant already sorts by signal/throughput). */
static int n3ds_saved_network_is_protected(const struct wpa_ssid *ssid)
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


static struct wpa_bss *
n3ds_select_remembered_bss(struct wpa_supplicant *wpa_s,
			   struct wpa_ssid **selected_ssid)
{
	unsigned int i;
	int protected_pass;
	struct wpa_ssid *ssid;

	for (protected_pass = 1; protected_pass >= 0; protected_pass--) {
		for (i = 0; i < wpa_s->last_scan_res_used; i++) {
			struct wpa_bss *bss = wpa_s->last_scan_res[i];

			for (ssid = wpa_s->conf->ssid; ssid; ssid = ssid->next) {
				if (n3ds_saved_network_is_protected(ssid) !=
				    protected_pass)
					continue;
				wpa_s->owe_transition_select = 1;
				*selected_ssid = wpa_scan_res_match(
					wpa_s, i, bss, ssid, 1, 1);
				wpa_s->owe_transition_select = 0;
				if (!*selected_ssid)
					continue;
				wpa_dbg(wpa_s, MSG_DEBUG,
					"N3DS: selected %s remembered BSS " MACSTR
					" level=%d ssid='%s'",
					protected_pass ? "protected" : "open",
					MAC2STR(bss->bssid), bss->level,
					wpa_ssid_txt(bss->ssid, bss->ssid_len));
				return bss;
			}
		}
	}

	return NULL;
}
'''

OLD_PICK = r'''while (selected == NULL) {
		for (prio = 0; prio < wpa_s->conf->num_prio; prio++) {
			if (next_ssid && next_ssid->priority ==
			    wpa_s->conf->pssid[prio]->priority) {
				selected = wpa_supplicant_select_bss(
					wpa_s, next_ssid, selected_ssid, 1);
				if (selected)
					break;
			}
			selected = wpa_supplicant_select_bss(
				wpa_s, wpa_s->conf->pssid[prio],
				selected_ssid, 0);
			if (selected)
				break;
		}
'''

NEW_PICK = r'''while (selected == NULL) {
		/* An explicit SELECT_NETWORK request remains authoritative. */
		if (next_ssid) {
			selected = wpa_supplicant_select_bss(
				wpa_s, next_ssid, selected_ssid, 1);
			next_ssid = NULL;
		}
		if (!selected)
			selected = n3ds_select_remembered_bss(
				wpa_s, selected_ssid);
'''


def transformed(original: str) -> str:
    if MARKER in original:
        if OLD_PROTECTION in original:
            return original.replace(OLD_PROTECTION, PROTECTION, 1)
        if PROTECTION not in original:
            raise RuntimeError("existing ranking helper has an unknown classifier")
        return original
    if original.count(HELPER_ANCHOR) != 1:
        raise RuntimeError("pick-network helper anchor changed")
    if original.count(OLD_PICK) != 1:
        raise RuntimeError("pick-network body changed")
    text = original.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR, 1)
    text = text.replace("\tsize_t prio;\n", "", 1)
    return text.replace(OLD_PICK, NEW_PICK, 1)


def main() -> None:
    if not EVENTS.is_file():
        # Clean-tree path: source removed so Buildroot will re-extract and
        # reapply package patches 0001–0004 including this one.
        if not PACKAGE_PATCH.is_file():
            raise SystemExit(
                f"missing package patch {PACKAGE_PATCH} and source "
                "tree not yet extracted; cannot ensure patch will be applied"
            )
        print(
            "patch_wpa_remembered_ranking: source not yet extracted; "
            "package patch present and will be applied by Buildroot"
        )
        return
    original = EVENTS.read_text()
    updated = transformed(original)

    # Refresh an earlier generated patch when the incremental tree contains
    # the compile-invalid unconditional WEP field access. CONFIG_WEP is off
    # in this target, so those struct members do not exist.
    if MARKER in original and original != updated:
        if not PACKAGE_PATCH.is_file():
            raise SystemExit("source is patched but package patch is missing")
        package_text = PACKAGE_PATCH.read_text()

        def added(block: str) -> str:
            return "".join("+" + line for line in block.splitlines(keepends=True))

        old_added = added(OLD_PROTECTION)
        if package_text.count(old_added) != 1:
            raise RuntimeError("generated package patch has an unknown classifier")
        PACKAGE_PATCH.write_text(
            package_text.replace(old_added, added(PROTECTION), 1)
        )
        EVENTS.write_text(updated)
        print(f"patch_wpa_remembered_ranking: refreshed {PACKAGE_PATCH}")
        print(f"patch_wpa_remembered_ranking: updated {EVENTS}")
        return

    # If the incremental tree was already changed, require its persistent
    # package patch to exist. Never emit a no-op patch.
    if original == updated:
        if not PACKAGE_PATCH.is_file():
            raise SystemExit("source is patched but package patch is missing")
        print("patch_wpa_remembered_ranking: already applied")
        return

    diff = "".join(
        unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile="a/wpa_supplicant/events.c",
            tofile="b/wpa_supplicant/events.c",
        )
    )
    PACKAGE_PATCH.parent.mkdir(parents=True, exist_ok=True)
    PACKAGE_PATCH.write_text(diff)
    EVENTS.write_text(updated)
    print(f"patch_wpa_remembered_ranking: wrote {PACKAGE_PATCH}")
    print(f"patch_wpa_remembered_ranking: updated {EVENTS}")


if __name__ == "__main__":
    main()
