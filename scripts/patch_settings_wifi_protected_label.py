#!/usr/bin/env python3
"""Keep the compact Wi-Fi row title limited to the SSID.

Security remains available through the normal preference icon/summary.  It
must not be concatenated onto the SSID: UNKNOWN (and localized security text)
is diagnostic state, not part of the network name, and title mutation also
breaks exact saved-profile matching in the small Settings layout.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PATH = Path(f"{A3DS_ROOT}/third_party/settings/src/com/android/settings/wifi/AccessPointPreference.java")
MARKER = "N3DS_SETTINGS_WIFI_PROTECTED_LABEL"
VERSION_MARKER = "N3DS_SETTINGS_WIFI_PROTECTED_LABEL_V2"

OLD = """    public void refresh() {
        setTitle(mState.getHumanReadableSsid());
        setSummary(mState.getSummarizedStatus());

        notifyChanged();
    }"""

NEW = """    public void refresh() {
        /* N3DS_SETTINGS_WIFI_PROTECTED_LABEL: N3DS_SETTINGS_WIFI_PROTECTED_LABEL_V2
         * Keep the SSID title stable.  Security is conveyed by the normal
         * preference icon and summary, never by mutating the network name. */
        setTitle(mState.getHumanReadableSsid());
        setSummary(mState.getSummarizedStatus());

        notifyChanged();
    }"""


def patch(text: str) -> str:
    if VERSION_MARKER in text:
        if 'setTitle(mState.getHumanReadableSsid());' not in text:
            raise RuntimeError("marked protected-label V2 source is incomplete")
        if 'title += " [' in text:
            raise RuntimeError("protected-label V2 source still mutates the SSID")
        return text

    # Migrate the earlier implementation, which appended localized security
    # text to the SSID title.  Keep this exact anchor so old staged sources are
    # repaired deterministically and a second application is a no-op.
    if MARKER in text:
        old_marked = """    public void refresh() {
        String title = mState.getHumanReadableSsid();
        /* N3DS_SETTINGS_WIFI_PROTECTED_LABEL: the 3DS compact Preference
         * layout can omit the summary line.  Keep the lock icon and also put
         * the canonical security class in the always-visible title. */
        if (mState.hasSecurity()) {
            title += " [" + mState.getHumanReadableSecurity() + "]";
        }
        setTitle(title);
        setSummary(mState.getSummarizedStatus());

        notifyChanged();
    }"""
        if text.count(old_marked) != 1:
            raise RuntimeError("marked protected-label source has unknown layout")
        return text.replace(old_marked, NEW, 1)

    if text.count(OLD) != 1:
        raise RuntimeError("protected-label refresh anchor changed")
    return text.replace(OLD, NEW, 1)


def main() -> None:
    if not PATH.is_file():
        raise SystemExit("missing canonical AccessPointPreference.java")
    original = PATH.read_text(encoding="utf-8")
    updated = patch(original)
    if updated != original:
        PATH.write_text(updated, encoding="utf-8")
        print("patch_settings_wifi_protected_label: updated " + str(PATH))
    else:
        print("patch_settings_wifi_protected_label: already applied")


if __name__ == "__main__":
    main()
