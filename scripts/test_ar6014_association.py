#!/usr/bin/env python3
"""Static contract for Nintendo AR6014 association recovery."""

from pathlib import Path


PATCH = Path(__file__).with_name("patch_ar6014_association.py").read_text()


def main():
    for marker in (
        "N3DS_AR6014_ASSOCIATION_COMPAT",
        "N3DS_AR6014_SHORT_DISCONNECT",
        "N3DS_AR6014_BOUNDED_RECONNECT",
        "N3DS_AR6014_CHANNEL_TABLE 0x00525548",
        "CONNECT_PROFILE_MATCH_DONE",
        "SPECIFIC_SSID_FLAG",
        "n3ds_ar6014_reconnect_used = true",
        "len > 4 ? datap[4] : NO_NETWORK_AVAIL",
    ):
        assert marker in PATCH, marker
    assert PATCH.count("wmi_reconnect_cmd") == 1
    assert "N3DS_AR6014_DIRECT_RECONNECT" in PATCH
    print("ar6014_association: PASS")


if __name__ == "__main__":
    main()
