#!/usr/bin/env python3
"""Keep boot output quiet and retire the fictional /dev/eac sysinit hook.

The real DSP experiment is /system/bin/dsp_chime from bootanim.sh. It is
bounded by a three-second watchdog and remains explicitly hardware-unverified.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path


OVERLAY = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay")
INITTAB = OVERLAY / "etc/inittab"

dead_paths = (
    OVERLAY / "etc/boot_sound.sh",
    OVERLAY / "usr/share/sounds/boot.wav",
    Path(f"{A3DS_ROOT}/third_party/buildroot/output/target/etc/boot_sound.sh"),
    Path(f"{A3DS_ROOT}/third_party/buildroot/output/target/usr/share/sounds/boot.wav"),
    Path(f"{A3DS_ROOT}/sdcard/linux/android/etc/boot_sound.sh"),
    Path(f"{A3DS_ROOT}/sdcard/linux/android/usr/share/sounds/boot.wav"),
    Path(f"{A3DS_WIN}/sdcard/linux/android/etc/boot_sound.sh"),
    Path(f"{A3DS_WIN}/sdcard/linux/android/usr/share/sounds/boot.wav"),
)

for dead_path in dead_paths:
    if dead_path.exists():
        dead_path.unlink()
        print("removed dead boot-sound artifact: " + str(dead_path))

inittab = INITTAB.read_text(encoding="utf-8")
inittab = inittab.replace("::sysinit:/etc/init.d/rcS\n",
                          "::sysinit:/etc/init.d/rcS >/dev/null 2>&1\n")
inittab = inittab.replace("::sysinit:/etc/boot_sound.sh\n", "")
assert "::sysinit:/etc/boot_sound.sh" not in inittab
assert inittab.count("::sysinit:/etc/init.d/rcS >/dev/null 2>&1") == 1
INITTAB.write_text(inittab, encoding="utf-8")

print("boot sequence cleanup: OK")
