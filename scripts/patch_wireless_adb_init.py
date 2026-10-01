#!/usr/bin/env python3
"""Install disabled-by-default TCP adbd service/property integration."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WSL_OVERLAY = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay")
WINDOWS_OVERLAY = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay"
WSL_TARGET = Path(f"{A3DS_ROOT}/third_party/buildroot/output/target")
WSL_STAGED = Path(f"{A3DS_ROOT}/sdcard/linux/android")
STAGED = ROOT / "sdcard/linux/android"
MARKER = "N3DS_WIRELESS_ADB_TCP_ONLY"


SERVICE = """

# N3DS_WIRELESS_ADB_TCP_ONLY: the 3DS has no USB gadget path. Settings
# publishes service.adb.tcp.port=5555 only while the user explicitly enables
# trusted-LAN debugging; init owns the root daemon's lifetime.
service adbd /system/bin/adbd
    class default
    disabled
    user root
    group shell log input inet graphics sdcard_rw

on property:service.adb.tcp.port=5555
    start adbd

on property:service.adb.tcp.port=0
    stop adbd
"""
TRIGGERS_ONLY = """
on property:service.adb.tcp.port=5555
    start adbd

on property:service.adb.tcp.port=0
    stop adbd
"""


def patch_init(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    # N3DS_ADB_ALWAYS_ROOT keeps the daemon starting at boot -- the device
    # ships pre-rooted and that is proven working, so SERVICE (which declares
    # adbd `disabled`) must not be appended over it. But the property triggers
    # are still needed on their own: Settings only writes
    # service.adb.tcp.port, adbd reads it once at startup, and without a
    # trigger nothing ever acts on the change. Add just those, idempotently.
    if "N3DS_ADB_ALWAYS_ROOT" in text:
        text = text.replace(
            "    group root shell log input inet graphics misc sdcard_rw\n",
            "    group shell log input inet graphics sdcard_rw\n",
        )
        if "on property:service.adb.tcp.port=5555" not in text:
            text = text.rstrip("\n") + "\n" + TRIGGERS_ONLY
        path.write_text(text, encoding="utf-8")
        return
    # This init generation accepts at most six supplementary groups.  The
    # service already runs as uid 0, so a redundant root group and unused misc
    # group only made the entire adbd declaration fail to parse.
    text = text.replace(
        "    group root shell log input inet graphics misc sdcard_rw\n",
        "    group shell log input inet graphics sdcard_rw\n",
    )
    if MARKER not in text:
        text = text.rstrip() + SERVICE + "\n"
    path.write_text(text, encoding="utf-8")


def patch_prop(path: Path) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "service.adb.tcp.port=5555" in text:
        # Always-on daemon: leave the published port alone.
        return
    text = text.replace("persist.service.adb.enable=1", "service.adb.tcp.port=0")
    if "service.adb.tcp.port=" not in text:
        text += "\n# N3DS_WIRELESS_ADB_TCP_ONLY: manual Settings toggle; default off.\nservice.adb.tcp.port=0\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    roots = [WINDOWS_OVERLAY, WSL_OVERLAY, WSL_TARGET, STAGED, WSL_STAGED]
    found = False
    for root in roots:
        if root.exists():
            found = True
            patch_init(root / "etc/init.rc")
            patch_prop(root / "system/build.prop")
    if not found:
        raise SystemExit("no canonical or staged Android tree found")
    print("patch_wireless_adb_init: TCP-only adbd service installed")


if __name__ == "__main__":
    main()
