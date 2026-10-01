#!/usr/bin/env python3
"""Stop locking WMI_CONNECT to a host-chosen BSSID against mesh/AP-steering SSIDs.

The #248 physical capture (HomeWifi, a two-radio same-SSID mesh AP) shows
cfg80211's connect request alternates sme->bssid between the mesh's two real
BSSIDs (8c:dd:0b:00:53:c8 and 8c:dd:0b:00:53:48) from one attempt to the next,
while NWM's own connect-time internal re-scan (already dwell-corrected to the
disassembly-verified 20 ms) reports NO_NETWORK_AVAIL against whichever one was
requested, on every single attempt, even though the host's own discovery scan
(ALL_BSS_FILTER) sees both BSSes moments earlier. NWM firmware predates
consumer mesh/band-steering hardware; its connect-time BSSID lock was never
exercised against a topology where two live radios answer one SSID.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"
MARKER = "N3DS_AR6014_MESH_BSSID_WILDCARD"

OLD = '''    A_MEMZERO(ar->arReqBssid, sizeof(ar->arReqBssid));
    if(sme->bssid){
        if(memcmp(&sme->bssid, bcast_mac, AR6000_ETH_ADDR_LEN)) {
            memcpy(ar->arReqBssid, sme->bssid, sizeof(ar->arReqBssid));
        }
    }
'''

NEW = '''    /* N3DS_AR6014_MESH_BSSID_WILDCARD: physical capture against a two-radio
     * same-SSID mesh AP shows cfg80211's chosen sme->bssid alternates between
     * the mesh's two real BSSIDs from one connect attempt to the next, and
     * NWM's own connect-time internal re-scan (distinct from the host
     * discovery scan that already sees both BSSes via ALL_BSS_FILTER above)
     * reports NO_NETWORK_AVAIL against whichever one was requested, every
     * single time. NWM firmware predates mesh/band-steering gear entirely,
     * so its connect-time BSSID lock was never exercised against a topology
     * where two live radios answer one SSID. Leave arReqBssid wildcard
     * (all-zero) and let NWM's own re-scan settle on whichever BSS answers
     * the requested SSID, exactly as the ALL_BSS_FILTER discovery scan
     * already does. */
    A_MEMZERO(ar->arReqBssid, sizeof(ar->arReqBssid));
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_cfg(text: str) -> str:
    if MARKER in text:
        return text
    return replace_once(text, OLD, NEW, "connect BSSID wildcard")


def main() -> None:
    if not CFG.is_file():
        raise SystemExit(f"missing canonical source: {CFG}")
    CFG.write_text(patch_cfg(CFG.read_text()))
    print("patch_ar6014_mesh_bssid_wildcard: WMI_CONNECT no longer locks to a host-chosen BSSID")


if __name__ == "__main__":
    main()
