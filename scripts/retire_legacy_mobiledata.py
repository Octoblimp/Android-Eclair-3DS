#!/usr/bin/env python3
"""Remove the retired local-AP Mobile Data runtime from canonical staging.

The HTTPS 3DSTelco client lives in the original Android apps and does not need
an init service, AP firmware mode, DHCP server, or privileged local socket.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay")
MANAGED_ROOTS = (
    ROOT,
    Path(f"{A3DS_ROOT}/third_party/buildroot/output/target"),
    Path(f"{A3DS_WIN}/sdcard/linux/android"),
    Path(f"{A3DS_ROOT}/sdcard/linux/android"),
)

INIT_OLD = """# N3DS_MOBILE_DATA_LIFECYCLE: 3DS Telco is a local AP, not a station-mode
# Wi-Fi connection. The controller owns AP qualification, static addressing,
# DHCP, client state, and rollback to station mode. It is disabled by default.
service mobiledata_ipc /system/bin/mobiledata_ipc
    class default
    user root
    group root system
    socket mobiledata stream 0600 system system

service md_dispatch /etc/mobiledata.sh dispatch
    class default
    user root
    group root wifi inet

service mobiledata /etc/mobiledata.sh daemon
    class default
    disabled
    oneshot
    user root
    group root wifi inet

on property:service.mobiledata.enable=1
    setprop sys.mobiledata.dispatch enable_requested
    setprop sys.mobiledata.state starting
    setprop sys.mobiledata.backend active
    setprop sys.mobiledata.error none
    start md_dispatch
    start mobiledata

on property:service.mobiledata.enable=0
    setprop sys.mobiledata.dispatch disable_requested
    start md_dispatch
    setprop service.mobiledata.adb 0
    setprop service.adb.tcp.port 0
    setprop sys.mobiledata.state disabled
    setprop sys.mobiledata.client_count 0
    setprop sys.mobiledata.rssi unknown
    setprop sys.mobiledata.ap_ipv4 ""
    setprop sys.mobiledata.adb_address ""
    setprop sys.mobiledata.backend ready
    setprop sys.mobiledata.error none

on property:sys.powerctl=*
    stop md_dispatch
    stop mobiledata
"""

PROP_OLD = """# N3DS_MOBILE_DATA_DEFAULTS: mutable request properties are consumed by the
# root-owned controller. Secrets are never represented as Android properties.
service.mobiledata.enable=0
service.mobiledata.security=open
service.mobiledata.adb=0
sys.mobiledata.backend=ready
service.mobiledata.ssid=3DS
sys.mobiledata.stage=booting
sys.mobiledata.result=none
sys.mobiledata.module=unknown
sys.mobiledata.rebind=none
sys.mobiledata.primary_error=none
sys.mobiledata.rollback=none
sys.mobiledata.boundary=none
sys.mobiledata.dispatch=booting
sys.mobiledata.dispatch_seq=0
sys.mobiledata.error=none
sys.mobiledata.state=disabled
sys.mobiledata.client_count=0
sys.mobiledata.rssi=unknown
sys.mobiledata.ap_ipv4=
sys.mobiledata.adb_address=
"""

BOOT_PROGRESS_OLD = """\t\techo "=== Mobile Data properties ==="
\t\tfor prop in backend state error stage result module rebind primary_error rollback boundary dispatch dispatch_seq; do
\t\t\techo "sys.mobiledata.$prop=$(getprop sys.mobiledata.$prop 2>/dev/null)"
\t\tdone
\t\techo "init.svc.mobiledata=$(getprop init.svc.mobiledata 2>/dev/null)"
"""


def remove_block(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    if block in text:
        path.write_text(text.replace(block, ""), encoding="utf-8", newline="\n")
    elif any(marker in text for marker in ("N3DS_MOBILE_DATA_LIFECYCLE", "N3DS_MOBILE_DATA_DEFAULTS")):
        raise RuntimeError(f"retired Mobile Data block changed unexpectedly: {path}")


def remove_marker_range(path: Path, marker: str, end_marker: str) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if marker not in text:
        return
    start = text.index(marker)
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"retired Mobile Data end marker missing: {path}")
    end += len(end_marker)
    while end < len(text) and text[end] in "\r\n":
        end += 1
    path.write_text(text[:start] + text[end:], encoding="utf-8", newline="\n")


def main() -> None:
    for managed_root in MANAGED_ROOTS:
        if not managed_root.is_dir():
            continue
        init_rc = managed_root / "etc/init.rc"
        build_prop = managed_root / "system/build.prop"
        # Antigravity extended and reordered both legacy blocks.  Remove the
        # complete marker-bounded sections without weakening fail-closed
        # validation or matching unrelated station-mode Wi-Fi settings.
        remove_marker_range(
            init_rc,
            "# N3DS_MOBILE_DATA_LIFECYCLE:",
            "on property:sys.powerctl=*\n    stop md_dispatch\n    stop mobiledata",
        )
        remove_marker_range(
            build_prop,
            "# N3DS_MOBILE_DATA_DEFAULTS:",
            "sys.mobiledata.adb_address=",
        )
    boot_progress = ROOT / "etc/boot_progress.sh"
    boot_text = boot_progress.read_text(encoding="utf-8")
    boot_text = boot_text.replace("|mobiledata:|mobiledata_apctl:", "")
    boot_text = boot_text.replace(BOOT_PROGRESS_OLD, "")
    if "sys.mobiledata" in boot_text or "mobiledata_apctl" in boot_text:
        raise SystemExit(f"retired Mobile Data diagnostics changed unexpectedly: {boot_progress}")
    boot_progress.write_text(boot_text, encoding="utf-8", newline="\n")
    retired = (
        "etc/mobiledata.sh",
        "system/bin/mobiledata_ipc",
        "system/bin/mobiledata_apctl",
        "system/bin/mobiledata_dhcp",
        "system/bin/mobiledata_status",
    )
    for managed_root in MANAGED_ROOTS:
        if not managed_root.is_dir():
            continue
        for relative in retired:
            path = managed_root / relative
            if path.exists() or path.is_symlink():
                path.unlink()
    print("legacy_mobiledata_retirement: AP/DHCP/socket runtime removed")


if __name__ == "__main__":
    main()
