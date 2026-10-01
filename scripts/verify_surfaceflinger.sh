#!/bin/bash
# Sanity-check that the pieces we expect actually landed in the linked
# surfaceflinger binary, rather than trusting "the link succeeded".
#
# This exists because of the lesson on record in docs/HANDOFF.md: editing a
# .cpp that lives inside an already-built .a and relinking can produce a
# clean link with zero undefined references and none of the new code present,
# because nothing referenced the new symbols by name. A clean link is not
# proof.
#
# Matched against the *demangled* table: gralloc.cpp and framebuffer.cpp are
# C++ (that is how upstream builds them), so fb_device_open and friends have
# mangled names in the object file even though they read like C functions.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
NM="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-nm
SF="${ANDROID3DS_ROOT}"/build/surfaceflinger/surfaceflinger

DEMANGLED=$("$NM" -C --defined-only "$SF" 2>/dev/null)

check() {
    if printf '%s\n' "$DEMANGLED" | grep -qF "$1"; then
        printf '  OK      %s\n' "$1"
    else
        printf '  MISSING %s\n' "$1"
        fail=1
    fi
}

fail=0
# the static HAL lookup and the module it resolves to
check 'hw_get_module'
check 'n3ds_gralloc_module'
# the gralloc HAL itself
check 'fb_device_open'
check 'mapFrameBufferLocked'
check 'gralloc_lock('
check 'gralloc_alloc('
# libagl providing EGL/GLES directly, with no dispatch layer
check 'eglCreateWindowSurface'
check 'eglSwapBuffers'
check 'eglInitialize'
check 'glClear'
# the compositor
check 'android::SurfaceFlinger::readyToRun()'
check 'android::SurfaceFlinger::threadLoop()'
check 'android::FramebufferNativeWindow::FramebufferNativeWindow()'
check 'android::DisplayHardware::init(unsigned int)'

echo
echo "dlopen must not be reachable from a static binary:"
if "$NM" --undefined-only "$SF" 2>/dev/null | grep -qE ' dlopen| dlsym'; then
    echo "  FAIL: dlopen/dlsym is an undefined reference"
    fail=1
else
    echo "  OK      (no undefined dlopen/dlsym)"
fi

exit $fail
