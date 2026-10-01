#!/bin/sh
. "$(dirname "$0")/a3ds_env.sh"
set -eu

# Android Eclair's WebKit was written for the C++98 compiler used by the
# original platform build.  The Android3DS Buildroot cross compiler defaults
# to C++17, where several formerly-valid initializers are hard errors.
#
# N3DS_WEBKIT_UB_FLAGS: GCC 14 also optimises on assumptions the 2009 code
# never made, so give it the same safety net every other native component in
# this tree already builds with:
#   -fno-delete-null-pointer-checks  Skia's safeRef()/safeUnref() are
#       `if (this) ...`; GCC >= 6 assumes `this` is never NULL and deletes the
#       test.  On hardware, 2026-09-30 (#316), GraphicsContextPlatformPrivate::
#       State's copy constructor ran mPathEffect->safeRef() with the default
#       NULL mPathEffect and faulted at 0x00000004 in WebViewCoreThread.
#   -fno-lifetime-dse  GCC >= 6 drops stores made before a constructor runs;
#       zeroing allocators followed by constructors that rely on it break.
#   -fwrapv  JavaScriptCore relies on signed integer wraparound.
# build_webkit.py refuses to build unless all three are here.
exec "${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-g++ \
    -std=gnu++98 -Wno-narrowing \
    -fno-delete-null-pointer-checks -fno-lifetime-dse -fwrapv \
    -I"${ANDROID3DS_ROOT}"/third_party/libhardware/include "$@"
