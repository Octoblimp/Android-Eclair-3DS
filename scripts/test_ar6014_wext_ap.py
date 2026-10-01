#!/usr/bin/env python3
from a3ds_paths import A3DS_ROOT
from pathlib import Path

ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")


def main() -> None:
    make = (ROOT / "Makefile").read_text(encoding="utf-8")
    ioctl = (ROOT / "os/linux/ioctl.c").read_text(encoding="utf-8")
    wext = (ROOT / "os/linux/wireless_ext.c").read_text(encoding="utf-8")
    assert "N3DS_AR6014_WEXT_AP_CONTROL" in make
    assert make.count("os/linux/ioctl.o") == 1
    assert make.count("os/linux/wireless_ext.o") == 1
    for marker in ("AR6000_XIOCTL_AP_COMMIT_CONFIG", "AR6000_XIOCTL_AP_GET_STA_LIST", "ar6000_ap_mode_profile_commit"):
        assert marker in ioctl, marker
    for marker in ("IW_MODE_MASTER", "AP_NETWORK", "ar6000_ioctl_siwmode"):
        assert marker in wext, marker
    print("ar6014_wext_ap: PASS")


if __name__ == "__main__":
    main()
