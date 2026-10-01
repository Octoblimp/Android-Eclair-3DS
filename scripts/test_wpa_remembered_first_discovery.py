#!/usr/bin/env python3
"""Contract checks for Nintendo 3DS remembered-first directed-scan discovery."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/patch_wpa_remembered_first_discovery.py"
PACKAGE_PATCH = (
    ROOT
    / "third_party/buildroot/package/wpa_supplicant"
    / "0004-n3ds-remembered-first-discovery.patch"
)

MARKER = "N3DS_REMEMBERED_FIRST_DISCOVERY"


def main() -> None:
    # Patcher must exist and reference the correct marker.
    patcher_text = PATCHER.read_text()
    assert MARKER in patcher_text, f"{MARKER!r} missing from patcher"
    assert "0004-n3ds-remembered-first-discovery.patch" in patcher_text
    assert "scan.c" in patcher_text

    # Package patch must exist and contain the marker.
    if not PACKAGE_PATCH.is_file():
        raise SystemExit(f"missing package patch: {PACKAGE_PATCH}")
    patch_text = PACKAGE_PATCH.read_text()
    assert MARKER in patch_text, f"{MARKER!r} missing from package patch"

    # The patch must target scan.c.
    assert "wpa_supplicant/scan.c" in patch_text, "expected scan.c target"

    # Key structural markers from the patch diff.
    for fragment in (
        "n3ds_add_remembered_scan_ssids",
        "n3ds_saved_network_is_protected_for_scan",
        "n3ds_scan_has_ssid",
        "n3ds_add_one_remembered_scan_ssid",
        "MANUAL_SCAN_REQ",
        "remembered-first directed scan",
    ):
        assert fragment in patch_text, f"{fragment!r} missing from patch"

    # Reference logic: remembered probes cap leaves room for wildcard.
    def ssids_added(total_slots: int, saved: list) -> list:
        """Simulate the max_ssids - 1 cap applied by n3ds_add_remembered_scan_ssids."""
        cap = max(total_slots - 1, 0)
        added = []
        seen = set()
        for ssid in saved:
            if len(added) >= cap:
                break
            if ssid not in seen:
                added.append(ssid)
                seen.add(ssid)
        return added

    result = ssids_added(5, ["HomeWifi", "other", "third", "fourth", "fifth"])
    assert len(result) == 4, f"expected 4 probes in 5-slot table, got {len(result)}"
    assert "HomeWifi" in result

    result_single = ssids_added(1, ["HomeWifi"])
    assert result_single == [], "single slot must be reserved for wildcard"

    print("wpa_remembered_first_discovery: PASS")


if __name__ == "__main__":
    main()
