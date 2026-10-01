#!/usr/bin/env python3
"""Regression for stable SSID titles and separate Wi-Fi security presentation."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "scripts/patch_settings_wifi_protected_label.py"
PIPELINE = ROOT / "scripts/rebuild_everything.sh"

FIXTURE = """public class AccessPointPreference {
    public void refresh() {
        setTitle(mState.getHumanReadableSsid());
        setSummary(mState.getSummarizedStatus());

        notifyChanged();
    }
}"""

V1_FIXTURE = """public class AccessPointPreference {
    public void refresh() {
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
    }
}"""


def main() -> None:
    spec = importlib.util.spec_from_file_location("protected_label", PATCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    patched = module.patch(FIXTURE)
    assert module.MARKER in patched
    assert module.VERSION_MARKER in patched
    assert 'setTitle(mState.getHumanReadableSsid());' in patched
    assert 'title += " [' not in patched
    assert module.patch(patched) == patched

    # Migrate the currently staged V1 source as well as an unpatched fixture.
    migrated = module.patch(V1_FIXTURE)
    assert module.VERSION_MARKER in migrated
    assert 'title += " [' not in migrated
    assert module.patch(migrated) == migrated
    pipeline = PIPELINE.read_text(encoding="utf-8")
    assert "run patch_settings_wifi_protected_label.py" in pipeline
    assert "run test_settings_wifi_protected_label.py" in pipeline
    assert pipeline.index("run patch_settings_wifi_protected_label.py") < pipeline.index(
        "run build_settings_app.sh")
    print("settings_wifi_protected_label: PASS")


if __name__ == "__main__":
    main()
