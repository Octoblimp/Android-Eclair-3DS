#!/usr/bin/env python3
"""Regression contract for NWM's keepalive-zero-before-connect sequence."""

from pathlib import Path


PATCH = Path(__file__).with_name("patch_ar6014_nwm_keepalive.py").read_text()


def main() -> None:
    for marker in (
        "N3DS_AR6014_NWM_PRECONNECT_KEEPALIVE",
        "wmi_set_keepalive_cmd(wmip, 0)",
        "A_NETBUF_FREE(osbuf)",
        "AR6002 connect: NWM pre-connect keepalive=0 submitted",
        "WMI_CONNECT_CMDID",
    ):
        assert marker in PATCH, marker

    new = PATCH.split("NEW = '''", 1)[1].split("'''", 1)[0]
    keepalive = new.index("wmi_set_keepalive_cmd(wmip, 0)")
    connect = new.index("wmi_cmd_send(wmip, osbuf, WMI_CONNECT_CMDID")
    assert keepalive < connect
    failure = new[keepalive:connect]
    assert failure.index("A_NETBUF_FREE(osbuf)") < failure.index("return A_ERROR")
    assert "WLAN_CONFIG_KEEP_ALIVE_INTERVAL" not in new
    print("ar6014_nwm_keepalive: PASS")


if __name__ == "__main__":
    main()
