#!/usr/bin/env python3
"""Defer continuous diagnostic FAT writes until Android boot completes."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
INIT_RC = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc"
FIRST_RC = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/init.rc"
INITTAB = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/inittab"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


initrc = INIT_RC.read_text()
if "N3DS_BOOT_IO_QUIET" not in initrc:
    for service in ("logcat", "bootlog", "lockupwatch", "bootprogress"):
        pos = initrc.index(f"service {service} ")
        next_service = initrc.find("\nservice ", pos + 1)
        if next_service < 0:
            next_service = len(initrc)
        block = initrc[pos:next_service]
        if "\n    disabled" not in block:
            first_nl = initrc.index("\n", pos)
            initrc = initrc[:first_nl + 1] + "    disabled\n" + initrc[first_nl + 1:]

    initrc += '''

# N3DS_BOOT_IO_QUIET: never compete with init/zygote for the single FAT-backed
# virtio queue. Heartbeat and warning-only tty logging remain active; bounded
# persistent collection begins only after Android reaches userspace.
on property:sys.boot_completed=1
    start logcat
    start bootlog
'''
INIT_RC.write_text(initrc)


firstrc = FIRST_RC.read_text()
if "N3DS_SD_NO_ATIME" not in firstrc:
    firstrc = replace_once(
        firstrc,
        "    mount vfat /dev/block/vda1 /mnt/sd rw\n",
        "    # N3DS_SD_NO_ATIME: framework reads must not create FAT metadata writes.\n"
        "    mount vfat /dev/block/vda1 /mnt/sd rw noatime nodiratime\n",
        "no-atime SD mount",
    )
FIRST_RC.write_text(firstrc)


inittab = INITTAB.read_text()
if "N3DS_NO_DUPLICATE_EARLY_BOOTLOG" not in inittab:
    inittab = replace_once(
        inittab,
        "::sysinit:/etc/dump_bootlog.sh\n",
        "# N3DS_NO_DUPLICATE_EARLY_BOOTLOG: Android init starts it post-boot.\n"
        "# ::sysinit:/etc/dump_bootlog.sh\n",
        "duplicate BusyBox bootlog",
    )
INITTAB.write_text(inittab)

print("patch_boot_io_quiet: continuous FAT diagnostics deferred until boot complete")
