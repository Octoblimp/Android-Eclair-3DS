#!/usr/bin/env python3
"""Stop build_hello_dex.sh installing its smoketest artifact into the ship tree.

The jar itself is harmless; where it lands is not.  /system/framework/hello.jar
has no pre-baked odex, so PackageManagerService dexopts it on every boot (it
walks /system/framework and dexopts every .apk/.jar that lacks one), installd
fails to open the output, and PMS -- which sets didDexOpt = true whether or not
mInstaller.dexopt() succeeded -- then deletes every data@app@* and
data@app-private@* entry from /data/dalvik-cache.  The failure never heals, so
that happens every boot, forever.

The three real framework jars are pre-baked in
sdcard/linux/android/data/dalvik-cache/ and are skipped.  hello.jar is the only
jar in that directory without one, and nothing in init.rc or any .rc/.xml/.sh
references it.  The smoketest proved what it was written to prove on
2026-08-03; the artifact now lands in its own fakeroot instead.

Both copies of the script are patched: find_script() prefers the Windows one,
so a WSL-only fix is a fix that never runs.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN
import io
import sys

PATHS = [
    f"{A3DS_ROOT}/scripts/build_hello_dex.sh",
    f"{A3DS_WIN}"
    "/scripts/build_hello_dex.sh",
]

OLD = f'OV={A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay\n'

NEW = """# Deliberately NOT the shipping rootfs_overlay.  This smoketest did its job on
# 2026-08-03 -- it proved Dalvik executes real bytecode on hardware -- but the
# artifact it left in /system/framework has no pre-baked odex, so
# PackageManagerService dexopts it on every boot, installd fails to open the
# output, and PMS then prunes the whole app half of /data/dalvik-cache because
# it believes a dexopt happened.  That cost is paid on every boot forever and
# buys nothing: nothing in init.rc or any .rc/.xml/.sh references hello.jar.
# The jar lands in its own fakeroot now.  To run the smoketest again, copy it
# onto the card by hand and take the dexopt cost deliberately.
OV="$OUT/fakeroot"
"""

changed = 0
for path in PATHS:
    src = io.open(path, encoding="utf-8").read()
    if 'OV="$OUT/fakeroot"' in src:
        print("already patched: " + path)
        continue
    if OLD not in src:
        sys.stderr.write("anchor missing in " + path + "\n")
        sys.exit(1)
    src = src.replace(OLD, NEW, 1)
    io.open(path, "w", encoding="utf-8", newline="\n").write(src)
    print("patched " + path)
    changed += 1

if not changed:
    sys.stderr.write("nothing changed\n")
    sys.exit(1)
