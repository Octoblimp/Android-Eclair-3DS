#!/usr/bin/env python3
"""Put the compositor's JNI registrations back into gRegJNI[].

PixelFormat / Display / Surface were cut from AndroidRuntime.cpp's gRegJNI[]
table on 2026-08-03 with the reason "no GPU driver / no libui compositor".
The first half of that was and is true -- there is no GPU driver and there
will not be one without a PICA200 driver. The second half is no longer true:
libui, libagl, libpixelflinger, the gralloc HAL and SurfaceFlinger are all
built now, and everything composites in software.

These three are exactly what WindowManagerService's constructor reaches on
its way to a window: android.view.Surface (SurfaceSession, Surface, the
transaction calls), android.view.Display (getDisplayInfo), and
android.graphics.PixelFormat (getPixelFormatInfo). With them unregistered
the constructor throws UnsatisfiedLinkError, which is the direct cause of
"Window Manager failed to start" on every boot so far.

Still deliberately cut, for unchanged reasons:
  EGL/GLES java bindings, opengl_classes -- Java-side GL for apps. The
      compositor uses the C entry points directly; no app needs GL yet.
  graphics_Camera -- android.graphics.Camera is the 3D-transform helper and
      does need GL; nothing on the path to a home screen uses it.

Idempotent.
"""
from a3ds_paths import A3DS_ROOT
import sys

PATH = (f"{A3DS_ROOT}/third_party/frameworks/base/core/jni/"
        "AndroidRuntime.cpp")

OLD_COMMENT = """//   - no GPU driver / no libui compositor: PixelFormat, Display, Surface,
//     EGL/GLES, opengl_classes, graphics_Camera"""

NEW_COMMENT = """//   - no GPU driver: EGL/GLES java bindings, opengl_classes,
//     graphics_Camera (android.graphics.Camera is the 3D transform helper
//     and genuinely needs GL). PixelFormat/Display/Surface used to be cut
//     here too, for "no libui compositor" -- that is no longer true, see
//     scripts/patch_gregjni_compositor.py, and they are registered below."""

ANCHOR = """    REG_JNI(register_android_nio_utils),
    REG_JNI(register_android_graphics_Graphics),
    REG_JNI(register_android_view_ViewRoot),
"""

ADDED = """    REG_JNI(register_android_nio_utils),
    REG_JNI(register_android_graphics_Graphics),
    REG_JNI(register_android_view_ViewRoot),

    // The compositor. Software all the way down: libui -> libagl ->
    // libpixelflinger -> the gralloc HAL -> /dev/graphics/fb1.
    // WindowManagerService cannot construct without these three.
    REG_JNI(register_android_graphics_PixelFormat),
    REG_JNI(register_android_view_Display),
    REG_JNI(register_android_view_Surface),
"""


def main():
    src = open(PATH).read()
    changed = 0

    if NEW_COMMENT not in src:
        if OLD_COMMENT not in src:
            print("FAIL: comment anchor not found")
            return 1
        src = src.replace(OLD_COMMENT, NEW_COMMENT, 1)
        changed += 1

    if "REG_JNI(register_android_view_Surface)" not in src:
        if ANCHOR not in src:
            print("FAIL: gRegJNI anchor not found")
            return 1
        src = src.replace(ANCHOR, ADDED, 1)
        changed += 1

    if changed:
        open(PATH, "w").write(src)
        print("AndroidRuntime.cpp: %d edit(s) applied" % changed)
    else:
        print("AndroidRuntime.cpp: already patched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
