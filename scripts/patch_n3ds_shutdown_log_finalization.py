#!/usr/bin/env python3
"""Check the shutdown log-finalization contract.  This no longer rewrites.

The previous version of this file generated a fail-closed ctr_poweroff.sh:
every integrity check ended in "refusing unsafe poweroff; exit 1", the
acknowledgement to the kernel was only written after a plain
``umount /mnt/sd``, and ctr_pwrkey.c was rewritten so its emergency deadline
would *refuse* to cut power until that acknowledgement arrived.

On the console /mnt/sd can never be unmounted -- /system, /etc, /usr, /sdcard
and /data/dalvik-cache are bind mounts of directories inside it, and the
running script's own text is read from it -- so that umount always returned
EBUSY.  The result on hardware was the reported failure: holding SELECT
printed that the card was still held open and left the console powered on,
with no way out but pulling the battery.  Both buttons must always power the
console off, so the generated design was wrong, not merely unlucky.

ctr_poweroff.sh now keeps the observations (wait for the writers to stop,
notice storage errors, acknowledge the kernel gate) and drops every veto: a
failed check is logged and the shutdown continues.  This script's job is to
make sure that repaired contract stays in place, which is why it checks
instead of patching -- regenerating the old text is exactly what must not
happen on the next rebuild.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import sys


PROJECT = Path(__file__).resolve().parents[1]
WSL_ROOT = Path(A3DS_ROOT)
OVERLAY_REL = Path("third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/ctr_poweroff.sh")
TARGET_REL = Path("third_party/buildroot/output/target/etc/ctr_poweroff.sh")
STAGED_REL = Path("sdcard/linux/android/etc/ctr_poweroff.sh")
INIT_OVERLAY_REL = Path("third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc")
INIT_STAGED_REL = Path("sdcard/linux/android/etc/init.rc")
PWRKEY_REL = Path("third_party/linux/drivers/platform/nintendo3ds/ctr_pwrkey.c")

SCRIPT_REQUIRED = (
    "N3DS_LOG_FINALIZATION_V2",
    "wait_for_log_writers",
    "check_storage_errors",
    'POWER_READY="${N3DS_POWER_READY:-/proc/n3ds_poweroff_ready}"',
    'echo 1 > "$POWER_READY"',
    'mount -o remount,ro "$MOUNT_POINT"',
    "exit 0",
)

# Every one of these is the signature of the fail-closed generator.  A veto in
# the shutdown path is a bug by definition here.
SCRIPT_FORBIDDEN = (
    "refusing unsafe poweroff",
    "umount -l",
    "kill -TERM -1",
)

INIT_REQUIRED = (
    "N3DS_ROOT_POWER_FINALIZER",
    "service ctr_poweroff /etc/ctr_poweroff.sh",
    "on property:sys.n3ds.poweroff=1",
    "start ctr_poweroff",
)

KERNEL_REQUIRED = (
    "N3DS_POWER_OFF_LOG_GATE",
    'proc_create("n3ds_poweroff_ready"',
    "log finalizer not acknowledged",
    "ctr_mcu_emergency_poweroff());",
    "orderly_poweroff(true)",
)

KERNEL_FORBIDDEN = ("orderly_poweroff(false)",)


def check(path: Path, required, forbidden=()) -> int:
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8", errors="replace")
    bad = 0
    for token in required:
        if token not in text:
            print("MISSING %r in %s" % (token, path), file=sys.stderr)
            bad += 1
    for token in forbidden:
        if token in text:
            print("FORBIDDEN %r in %s" % (token, path), file=sys.stderr)
            bad += 1
    if not bad:
        print("OK", path)
    return bad


def main() -> None:
    bad = 0
    for rel in (OVERLAY_REL, TARGET_REL, STAGED_REL):
        for root in (WSL_ROOT, PROJECT):
            bad += check(root / rel, SCRIPT_REQUIRED, SCRIPT_FORBIDDEN)
    for rel in (INIT_OVERLAY_REL, INIT_STAGED_REL):
        for root in (WSL_ROOT, PROJECT):
            bad += check(root / rel, INIT_REQUIRED)
    for root in (WSL_ROOT, PROJECT):
        bad += check(root / PWRKEY_REL, KERNEL_REQUIRED, KERNEL_FORBIDDEN)
    if bad:
        print("FATAL: shutdown path contract violated (%d problem(s))" % bad,
              file=sys.stderr)
        raise SystemExit(1)
    print("patch_n3ds_shutdown_log_finalization: shutdown contract verified")


if __name__ == "__main__":
    main()
