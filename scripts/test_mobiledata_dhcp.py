#!/usr/bin/env python3
"""Host-side contract checks for the bounded 3DS Telco DHCP server."""

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "native/mobiledata/mobiledata_dhcp.c"
RUNTIME = ROOT / (
    "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/mobiledata.sh"
)
BUILD = ROOT / "scripts/build_mobiledata_dhcp.sh"


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")

    for marker in (
        '"wlan0"',
        "192.168.43.1",
        "LEASE_FIRST 100u",
        "LEASE_LAST 150u",
        "SO_BINDTODEVICE",
        "DHCP_MAGIC",
        "DHCP_MAX_PACKET 1500u",
        "option_length > length - offset",
        "flock(fd, LOCK_EX | LOCK_NB)",
        "signal(SIGTERM",
        "signal(SIGINT",
        "signal(SIGHUP",
        "expire_leases",
        "DHCP_NAK",
    ):
        assert marker in source, f"DHCP source missing {marker!r}"
    assert "persist.sys" not in source.lower()
    assert "/mnt/sd" not in source
    assert "udhcpd" not in runtime
    assert "mobiledata_dhcp" in runtime
    assert "DHCP_CONF" not in runtime
    assert "static" in build and "-static" in build
    assert "mobiledata_dhcp" in build

    result = subprocess.run(["sh", "-n", str(RUNTIME)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    result = subprocess.run(["bash", "-n", str(BUILD)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    print("mobiledata_dhcp: PASS (bounded DHCP contract)")


if __name__ == "__main__":
    main()
