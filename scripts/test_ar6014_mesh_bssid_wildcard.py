#!/usr/bin/env python3
"""Regression for the mesh-AP BSSID-lock connect failure seen in #248."""

import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_mesh_bssid_wildcard.py")
CAPTURE = ROOT / "wifi_trace.txt"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_capture_evidence() -> None:
    trace = CAPTURE.read_text(errors="replace")
    # The #248 physical capture proves the same SSID answers from two
    # distinct real BSSIDs (a mesh AP), and every connect attempt against
    # either one ends in NO_NETWORK_AVAIL (reason=1) despite the corrected
    # 20 ms connect-scan dwell.
    # (The capture is local-only; its BSSIDs are not repeated here. Two
    # distinct BSSIDs behind one vendor prefix is the mesh signature.)
    bssids = set(re.findall(r"bssid=((?:[0-9a-f]{2}:){5}[0-9a-f]{2})", trace))
    bssids.discard("00:00:00:00:00:00")
    assert len({b[:8] for b in bssids}) < len(bssids)
    assert "dwell=20" in trace
    assert "dwell=105" not in trace
    assert trace.count("reason=1 status=0 bssid=00:00:00:00:00:00 assoc=0") >= 1


def main() -> None:
    assert_capture_evidence()
    patcher = load(PATCH_PATH, "mesh_bssid_wildcard")

    model = '''    A_MEMZERO(ar->arReqBssid, sizeof(ar->arReqBssid));
    if(sme->bssid){
        if(memcmp(&sme->bssid, bcast_mac, AR6000_ETH_ADDR_LEN)) {
            memcpy(ar->arReqBssid, sme->bssid, sizeof(ar->arReqBssid));
        }
    }
'''
    patched = patcher.patch_cfg(model)
    assert patcher.MARKER in patched
    assert "memcpy(ar->arReqBssid, sme->bssid" not in patched
    assert patched.count("A_MEMZERO(ar->arReqBssid, sizeof(ar->arReqBssid));") == 1
    assert patcher.patch_cfg(patched) == patched
    print("ar6014_mesh_bssid_wildcard: PASS")


if __name__ == "__main__":
    main()
