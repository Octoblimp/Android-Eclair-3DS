#!/usr/bin/env python3
"""Host regression for the bounded 3DS Telco legacy AP control path."""

from __future__ import annotations
from a3ds_paths import A3DS_ROOT

import importlib.util
from pathlib import Path
import struct


ROOT = Path(__file__).resolve().parents[1]
PATCH_PATH = ROOT / "scripts/patch_ar6014_mobiledata_ap.py"
SOURCE = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")


def load_patcher():
    spec = importlib.util.spec_from_file_location("mobile_data_ap", PATCH_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    patcher = load_patcher()
    driver = (SOURCE / "os/linux/ar6000_drv.c").read_text(encoding="utf-8")
    ioctl = (SOURCE / "os/linux/ioctl.c").read_text(encoding="utf-8")
    header = (SOURCE / "os/linux/include/athdrv_linux.h").read_text(encoding="utf-8")
    filt = (SOURCE / "os/linux/include/wmi_filter_linux.h").read_text(encoding="utf-8")
    wext = (SOURCE / "os/linux/wireless_ext.c").read_text(encoding="utf-8")

    driver = patcher.patch_fwmode(driver)
    driver = patcher.patch_ap_commit(driver)
    driver = patcher.patch_ap_failure_cleanup(driver)
    driver = patcher.patch_station_bounds(driver)
    driver = patcher.patch_ap_ready_event(driver)
    ioctl = patcher.patch_ap_stats(ioctl)
    header = patcher.patch_mobile_data_ioctl_header(header)
    filt = patcher.patch_mobile_data_filter(filt)
    ioctl = patcher.patch_mobile_data_ioctl(ioctl)
    ioctl = patcher.patch_mobile_data_ioctl_upgrade(ioctl)
    wext = patcher.patch_private_ioctl_reachability(wext)
    driver, ioctl = patcher.patch_direct_ioctl_reachability(driver, ioctl)

    for marker in (
        "N3DS_AR6014_FW_MODE_GUARD",
        "N3DS_AR6014_MOBILE_DATA_AP_GUARD",
        "N3DS_AR6014_AP_STA_BOUNDS",
        "N3DS_AR6014_AP_READY_EVENT",
        "N3DS_AR6014_AP_COMMIT_ACCEPTED_READY",
        "N3DS_AR6014_AP_ROLLBACK",
        "N3DS_AR6014_AP_STATS_GUARD",
        "status = wmi_ap_profile_commit(ar->arWmi, &p);",
        "rolling back STA",
        "ar->arConnected = true;",
        "WMI_AP_MODE_STAT payload",
    ):
        assert marker in driver or marker in ioctl, marker

    # Nintendo AP firmware does not produce the station self-connect event.
    # Preserve the original vendor readiness contract after a successful,
    # checked AP_CONFIG_COMMIT enqueue; association is a later client gate.
    commit_start = driver.index("N3DS_AR6014_MOBILE_DATA_AP_GUARD")
    commit_end = driver.index("int\nar6000_connect_to_ap", commit_start)
    commit = driver[commit_start:commit_end]
    assert "status = wmi_ap_profile_commit" in commit
    assert "N3DS_AR6014_AP_COMMIT_ACCEPTED_READY" in commit
    assert "netif_carrier_on(ar->arNetDev)" in commit
    assert "ar->arConnected = true;" in commit
    ready_start = driver.index("N3DS_AR6014_AP_READY_EVENT")
    ready_end = driver.index("void\nar6000_disconnect_event", ready_start)
    ready = driver[ready_start:ready_end]
    assert "netif_carrier_on(ar->arNetDev)" in ready

    for marker in (
        "AR6000_XIOCTL_N3DS_MOBILE_DATA_AP             162",
        "AR6000_IOCTL_N3DS_MOBILE_DATA",
        "N3DS_MOBILE_DATA_AP_START_OPEN",
        "N3DS_MOBILE_DATA_AP_START_WPA2",
        "N3DS_MOBILE_DATA_AP_STOP",
        "N3DS_MOBILE_DATA_AP_MIN_CHANNEL",
        "N3DS_MOBILE_DATA_AP_MAX_CHANNEL",
        "N3DS_MOBILE_DATA_AP_MAX_SSID",
        "N3DS_MOBILE_DATA_AP_CONTROL",
        "no passphrase",
    ):
        assert marker.lower() in header.lower(), marker
    assert "N3DS_AR6014_MOBILE_DATA_IOCTL" in ioctl
    assert "N3DS_AR6014_MOBILE_DATA_DIRECT_IOCTL" in driver
    assert "N3DS_AR6014_MOBILE_DATA_DIRECT_IOCTL" in ioctl
    assert ".ndo_do_ioctl           = ar6000_ioctl," in driver
    assert "cmd == AR6000_IOCTL_N3DS_MOBILE_DATA" in ioctl
    assert "copy_from_user(&control, userdata, sizeof(control))" in ioctl
    assert "if (control.reserved != 0)" in ioctl
    assert "control.channel < N3DS_MOBILE_DATA_AP_MIN_CHANNEL" in ioctl
    assert "control.channel > N3DS_MOBILE_DATA_AP_MAX_CHANNEL" in ioctl
    assert "ar->ap_mode_bkey.ik_keylen == 0" in ioctl
    assert "wmi_disconnect_cmd(ar->arWmi)" in ioctl
    assert "ar6000_TxDataCleanup(ar)" in ioctl
    assert "A_MEMZERO(ar->sta_list, sizeof(ar->sta_list))" in ioctl
    assert "A_MEMZERO(&ar->arAPStats, sizeof(ar->arAPStats))" in ioctl
    assert "(INFRA_NETWORK | AP_NETWORK)" in filt[filt.index("AR6000_XIOCTL_N3DS_MOBILE_DATA_AP") - 80:]
    assert "N3DS_AR6014_PRIVATE_IOCTL_REACHABLE" in wext
    assert "request.ifr_data = wrqu->data.pointer" in wext
    assert ".private          = (iw_handler *)ath_private_handlers" in wext
    assert "AR6000_IOCTL_EXTENDED - SIOCIWFIRSTPRIV" in wext
    assert struct.calcsize("<IIHBB32s") == 44

    # Every patch stage is idempotent on the generated result.
    assert patcher.patch_ap_commit(driver) == driver
    assert patcher.patch_ap_failure_cleanup(driver) == driver
    assert patcher.patch_mobile_data_ioctl(ioctl) == ioctl
    assert patcher.patch_mobile_data_ioctl_upgrade(ioctl) == ioctl
    assert patcher.patch_mobile_data_ioctl_header(header) == header
    assert patcher.patch_mobile_data_filter(filt) == filt
    assert patcher.patch_private_ioctl_reachability(wext) == wext
    direct_driver, direct_ioctl = patcher.patch_direct_ioctl_reachability(
        driver, ioctl)
    assert direct_driver == driver
    assert direct_ioctl == ioctl
    print("ar6014_mobiledata_ap: PASS (bounded AP ioctl; RSSI remains unknown)")


if __name__ == "__main__":
    main()
