#!/usr/bin/env python3
"""Regression for #245's zero-BSS discovery/connect state conflation."""

import importlib.util
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = Path(__file__).with_name("patch_ar6014_discovery_connect_split.py")
OLD_PATCH_PATH = Path(__file__).with_name("patch_ar6014_nwm_connection_scan.py")
CORPUS = ROOT / "scratch/nwm-full-corpus"
CAPTURE = ROOT / "evidence/kernel245-zero-bss-20260831T232330Z"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def assert_nwm_and_capture_evidence() -> None:
    prepare = (CORPUS / "disassembly/0012ad70_FUN_0012ad70.txt").read_text()
    # Empty profiles select WMI/NWM flag 2 (ANY_SSID), while a nonempty
    # selected profile uses flag 1. These are distinct protocol states.
    assert "0222  movs r2, #0x2" in prepare
    assert "0122  movs r2, #0x1" in prepare
    calls = [
        prepare.index("bl 0x0011a330"),
        prepare.index("bl 0x0011a2b8"),
        prepare.index("bl 0x0011aa2c"),
        prepare.index("bl 0x0011a390"),
        prepare.index("bl 0x00133030"),
    ]
    assert calls == sorted(calls)

    trace = (CAPTURE / "wifi_trace.txt").read_text(errors="replace")
    supplicant = (CAPTURE / "wpa_supplicant.log").read_text(errors="replace")
    assert "flags=0x5 dwell=20 channel_table=14 start_list=0" in trace
    assert "direct BSS accepted=0; no RAM harvest" in trace
    # A probe for the remembered network (any nonempty SSID; the capture is
    # local-only, so its network name is not repeated here) ...
    assert re.search(r"Scan probed for SSID '[^']+'", supplicant)
    # ... and a wildcard probe.
    assert "Scan probed for SSID ''" in supplicant
    # The circular log retains scan updates 22..89: 68 consecutive failures.
    assert supplicant.count("Received scan results (0 BSSes)") >= 60


def main() -> None:
    # The evidence half reads a Ghidra corpus of Nintendo's NWM module and a
    # local Wi-Fi capture. Neither is in the repository, so a fresh clone
    # checks only the patch model.
    if CORPUS.is_dir() and CAPTURE.is_dir():
        assert_nwm_and_capture_evidence()
    else:
        print("ar6014_discovery_connect_split: NWM/capture evidence skipped (not present locally)")
    patcher = load(PATCH_PATH, "discovery_connect_split")
    old = load(OLD_PATCH_PATH, "nwm_connection_scan_baseline")
    model = (
        patcher.TOP_ANCHOR
        + patcher.CONNECT_CHANNEL_OLD
        + patcher.CONNECT_FILTER_OLD
        + patcher.CONNECT_FILTER_END
        + patcher.CONNECT_SLOT_OLD
        + patcher.CONNECT_SEND_OLD
        + old.HELPER_NEW
        + patcher.SCAN_VARS_OLD
        + old.PREP_NEW
        + old.START_NEW
        + old.COMPLETE_NEW
    )
    patched = patcher.patch_cfg(model)
    assert patcher.MARKER in patched
    assert old.MARKER in patched
    assert "ANY_SSID_FLAG" in patched
    assert "i + 1, flag" in patched
    assert "n3ds_ar6014_clear_discovery_ssids(ar, request)" in patched

    connect = patcher.CONNECT_SETUP_NEW + patcher.CONNECT_SEND_NEW
    connect_order = [
        connect.index("wmi_probedSsid_cmd(ar->arWmi, 0, SPECIFIC_SSID_FLAG"),
        connect.index("wmi_scanparams_cmd(ar->arWmi"),
        connect.index("n3ds_ar6014_set_search_channel"),
        connect.index("wmi_bssfilter_cmd(ar->arWmi"),
        connect.index("wmi_connect_cmd(ar->arWmi"),
    ]
    assert connect_order == sorted(connect_order)
    assert "N3DS_NWM_CONNECT_SCAN_DWELL_MS 20" in patched

    scan = patched.split("ar6k_cfg80211_scan(struct", 1)[1].split(
        "ar6k_cfg80211_scanComplete_event", 1
    )[0]
    assert "wmi_scanparams_cmd" not in scan
    assert "0, 0, num_channels, channel_list" in scan
    assert "discovery explicit channels=%d wildcard=%u" in scan
    assert "channel_table=%d start_list=0" not in scan
    assert patcher.patch_cfg(patched) == patched
    print("ar6014_discovery_connect_split: PASS")


if __name__ == "__main__":
    main()
