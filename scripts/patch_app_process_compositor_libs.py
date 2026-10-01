#!/usr/bin/env python3
"""Add the compositor libraries to app_process's link line.

android_view_Surface.cpp is now compiled into libandroid_runtime.a and
registered in gRegJNI[], so app_process references libui (Surface,
SurfaceComposerClient, ISurfaceComposer, Region, ...), which in turn pulls in
the gralloc HAL, libagl and libpixelflinger.

libgralloc_n3ds.a must come *before* libhardware.a: it defines the static
hw_get_module() that replaces libhardware's dlopen-based lookup, which cannot
work in a statically linked binary. Whichever archive the linker reaches
first wins, and once hw_get_module is resolved nothing pulls libhardware's
hardware.o in at all.

Idempotent; patches both build_app_process.sh and build_app_process_debug.sh.
"""
from a3ds_paths import A3DS_WIN
import sys

SCRIPTS = [
    f"{A3DS_WIN}/"
    "scripts/build_app_process.sh",
    f"{A3DS_WIN}/"
    "scripts/build_app_process_debug.sh",
]

ANCHOR = """        "$BUILD/bionic_compat/libbionic_compat.a" \\
        "$BUILD/libhardware/libhardware.a" \\
"""

REPLACEMENT = """        "$BUILD/bionic_compat/libbionic_compat.a" \\
        `# The compositor. android_view_Surface.cpp (now in
         # libandroid_runtime.a, now in gRegJNI[]) is what binds
         # android.view.Surface/SurfaceSession, which WindowManagerService
         # cannot construct without. libui pulls gralloc/libagl/
         # libpixelflinger in behind it.
         #
         # libgralloc_n3ds.a MUST precede libhardware.a -- it defines the
         # static hw_get_module() that replaces libhardware's dlopen-based
         # module lookup, and dlopen() unconditionally returns NULL in a
         # static binary.` \\
        "$BUILD/libui/libui.a" \\
        "$BUILD/libgralloc/libgralloc_n3ds.a" \\
        "$BUILD/libagl/libagl.a" \\
        "$BUILD/libpixelflinger/libpixelflinger.a" \\
        "$BUILD/libhardware/libhardware.a" \\
"""


def main():
    rc = 0
    for path in SCRIPTS:
        try:
            src = open(path).read()
        except IOError as e:
            print("MISSING %s: %s" % (path, e))
            rc = 1
            continue

        if "libgralloc_n3ds.a" in src:
            print("%s: already patched" % path.split("/")[-1])
            continue
        if ANCHOR not in src:
            print("FAIL %s: link-group anchor not found" % path.split("/")[-1])
            rc = 1
            continue

        open(path, "w").write(src.replace(ANCHOR, REPLACEMENT, 1))
        print("%s: compositor libraries added" % path.split("/")[-1])
    return rc


if __name__ == "__main__":
    sys.exit(main())
