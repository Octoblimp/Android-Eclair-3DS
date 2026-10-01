#!/usr/bin/env python3
"""Regression checks for the mixed direct-WMI/fallback scan merge."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
DRV = ROOT / "drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
WMI = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi.c"
HOST = ROOT / "drivers/staging/ath6k_legacy/wmi/wmi_host.h"
API = ROOT / "drivers/staging/ath6k_legacy/include/wmi_api.h"


def snapshot_admission_model(
    busy: int, active_snapshot: tuple[str, ...], pending_count: int,
    incoming_snapshot: tuple[str, ...],
) -> tuple[int, tuple[str, ...], int, bool]:
    """Only the admitted completion may publish; losers clear pending input."""
    if busy:
        return busy, active_snapshot, 0, False
    return 1, incoming_snapshot, 0, True


def main() -> None:
    drv = DRV.read_text()
    wmi = WMI.read_text()
    host = HOST.read_text()
    api = API.read_text()

    assert "N3DS_AR6014_MIXED_BSS_MERGE" in drv
    assert "N3DS_AR6014_HARVEST_SNAPSHOT_ADMISSION" in drv
    assert "ar6014_harvest_direct_bss" in drv
    assert "wmi_n3ds_take_direct_bss_count(ar->arWmi)" in drv
    assert "wmi_n3ds_discard_direct_bss_count(ar->arWmi)" in drv
    assert "ar6014_cache_begin_scan();" in drv
    assert "direct BSS accepted=%u; RAM harvest merge" in drv
    assert "if (ar6014_harvest_scan)" in drv
    assert "ar6014_queue_harvest(ar, status)" in drv
    assert "wmi_n3ds_direct_bss_seen(wmip, frame + 16)" in drv
    assert "direct_skipped" in drv
    assert "N3DS_AR6014_STALE_CACHE_SKIP" in drv
    assert "stale_skipped" in drv

    assert "wmi_n3ds_direct_bss_count" in host
    assert "wmi_n3ds_harvest_bss_count" in host
    assert "wmi_n3ds_direct_bss" in host
    assert "wmi_n3ds_harvest_bss" in host
    assert "wmip->wmi_n3ds_direct_bss_count = 0;" in wmi
    assert "wmi_n3ds_direct_bss_count <" in wmi
    assert "wmi_n3ds_harvest_bss_count = count" in wmi
    assert "wmi_n3ds_direct_bss_seen" in wmi
    assert "wmi_n3ds_discard_direct_bss_count" in wmi
    assert wmi.index("wlan_setup_node(&wmip->wmi_scan_table, bss, bih->bssid);") < wmi.index(
        "wmip->wmi_n3ds_direct_bss_count++"
    )
    assert "wmi_n3ds_take_direct_bss_count" in api
    assert "wmi_n3ds_direct_bss_seen" in api
    assert "wmi_n3ds_discard_direct_bss_count" in api

    scan_start = drv.index("void\nar6000_scanComplete_event(")
    scan_end = drv.index("\nvoid\nar6000_targetStats_event(", scan_start)
    scan = drv[scan_start:scan_end]
    assert scan.index("ar6014_queue_harvest(ar, status)") < scan.index(
        "wmi_n3ds_take_direct_bss_count(ar->arWmi)"
    )
    assert scan.index("wmi_n3ds_discard_direct_bss_count(ar->arWmi)") < scan.index(
        "wmi_n3ds_take_direct_bss_count(ar->arWmi)"
    )

    busy, active, pending, admitted = snapshot_admission_model(
        0, (), 2, ("first", "bssid")
    )
    assert admitted and (busy, active, pending) == (1, ("first", "bssid"), 0)
    busy, active, pending, admitted = snapshot_admission_model(
        busy, active, 1, ("loser",)
    )
    assert not admitted and (busy, active, pending) == (
        1, ("first", "bssid"), 0
    )
    busy, active, pending, admitted = snapshot_admission_model(
        0, active, 1, ("next",)
    )
    assert admitted and (busy, active, pending) == (1, ("next",), 0)

    # Reference merge model: a direct node wins for its BSSID, but fallback
    # still contributes BSSIDs absent from the direct event set.
    direct = {"direct-only": "exact", "both": "exact"}
    fallback = {"both": "guessed", "fallback-only": "guessed"}
    merged = dict(fallback)
    merged.update(direct)
    assert merged == {
        "direct-only": "exact",
        "both": "exact",
        "fallback-only": "guessed",
    }

    print("ar6014_direct_bss_preference: PASS")


if __name__ == "__main__":
    main()
