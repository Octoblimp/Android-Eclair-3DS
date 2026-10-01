"""Regression checks for directed-scan ABI limits and fresh BSS eviction."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCHER = ROOT / "scripts/patch_ar6014_scan_priority.py"
NWM_PROBED = ROOT / "scratch/nwm-full-corpus/functions/00136528_FUN_00136528.c"


def cache_insert(cache, bssid, generation, tsf, body, capacity=64):
    """Reference model for TSF tombstones and stale-slot replacement."""
    if bssid in cache:
        if cache[bssid]["tsf"] == tsf:
            return
        cache[bssid] = {"seen": generation, "tsf": tsf, "body": body}
        return
    if len(cache) >= capacity:
        stale = [name for name in cache if cache[name]["seen"] == 0]
        victim = stale[0] if stale else min(
            cache, key=lambda name: cache[name]["seen"]
        )
        del cache[victim]
    cache[bssid] = {"seen": generation, "tsf": tsf, "body": body}


def cache_prune(cache, generation, fresh_scans=2):
    for entry in cache.values():
        if entry["seen"] and generation - entry["seen"] > fresh_scans:
            entry["seen"] = 0


def main() -> None:
    text = PATCHER.read_text()
    for marker in (
        "N3DS_NWM_PROBED_SSID_SLOTS",
        "N3DS_MAX_SCAN_PROBED_SSIDS 5",
        "request->ssids[i].ssid_len",
        "first_len=%u",
        "N3DS_SCAN_START_FAILURE_CLEANUP",
        "AR6014_CACHE_MAX             64",
        "last_seen_generation",
        "ar6014_cache_generation",
        "N3DS_AR6014_CACHE_FRESHNESS",
        "AR6014_CACHE_FRESH_SCANS",
        "ar6014_cache_begin_scan",
        "ar6014_cache_prune",
        "evict stale",
        "N3DS_AR6014_FRAME_IDENTITY",
        "body[0..7]",
        "ar6014_cache_same_tsf",
        "N3DS_AR6014_CACHE_TOMBSTONE",
        "N3DS_AR6014_STALE_CACHE_SKIP",
        "unchanged RAM frame",
        "evict stale/oldest",
    ):
        assert marker in text, marker

    # Decompiled NWM validates slot index <= 5 and emits command ID 10.
    nwm = NWM_PROBED.read_text()
    assert "param_2 < 6" in nwm
    assert "FUN_00118140(param_1,iVar1,10,0)" in nwm
    assert "FUN_00123688(puVar2,0x23)" in nwm

    cache = {
        f"old-{i}": {"seen": 1, "tsf": i, "body": b"old"}
        for i in range(64)
    }
    cache_insert(cache, "HomeWifi-bssid", 2, 99, b"new")
    assert "HomeWifi-bssid" in cache
    assert len(cache) == 64
    assert sum(name.startswith("old-") for name in cache) == 63

    # Real order is prune -> sweep/cache_put -> inject.  Retain an expired
    # entry as a TSF tombstone so the same RAM frame cannot be re-added.
    stale_body = (1).to_bytes(8, "little") + b"stale-ie"
    cache = {}
    injected = []
    for generation in range(1, 8):
        cache_prune(cache, generation)
        cache_insert(cache, "stale", generation, 1, stale_body)
        injected.append(cache["stale"]["seen"] != 0)
    assert injected[:3] == [True, True, True]
    assert injected[3:] == [False, False, False, False]
    assert cache["stale"]["seen"] == 0

    # Body changes with the same TSF do not revive a tombstone; an advancing
    # TSF does and becomes injectable again.
    cache_insert(cache, "stale", 8, 1, (1).to_bytes(8, "little") + b"changed")
    assert cache["stale"]["seen"] == 0
    cache_prune(cache, 8)
    cache_insert(cache, "stale", 8, 2, (2).to_bytes(8, "little") + b"ie")
    assert cache["stale"]["seen"] == 8

    # A newer TSF refreshes, then eventually becomes stale again if it stops.
    cache = {}
    cache_insert(cache, "moving", 1, 1, (1).to_bytes(8, "little") + b"ie")
    cache_prune(cache, 2)
    cache_insert(cache, "moving", 2, 2, (2).to_bytes(8, "little") + b"ie")
    assert cache["moving"]["seen"] == 2
    cache_prune(cache, 5)
    assert cache["moving"]["seen"] == 0

    # Direct WMI authority still wins when fallback has the same BSSID, while
    # fallback-only BSSIDs remain eligible for the mixed merge.
    direct = {"direct-only": "exact", "both": "exact"}
    fallback = {"both": "guessed", "fallback-only": "guessed"}
    merged = dict(fallback)
    merged.update(direct)
    assert merged["both"] == "exact"
    assert merged["fallback-only"] == "guessed"
    print("ar6014_scan_priority: PASS")


if __name__ == "__main__":
    main()
