#!/bin/bash
# Prove the compositor really is inside app_process, not merely on its link
# line. See docs/HANDOFF.md: a clean link with zero undefined references is
# not evidence that an archive member was pulled in -- if nothing references
# a symbol by name, its .o silently stays out of the binary.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
NM="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-nm
BIN=${1:-"${ANDROID3DS_ROOT}"/build/app_process/app_process}

DEMANGLED=$("$NM" -C --defined-only "$BIN" 2>/dev/null)

fail=0
check() {
    if printf '%s\n' "$DEMANGLED" | grep -qF "$1"; then
        printf '  OK      %s\n' "$1"
    else
        printf '  MISSING %s\n' "$1"
        fail=1
    fi
}

echo "=== $BIN ==="
# The three registrations restored to gRegJNI[] -- WindowManagerService's
# constructor binds to all three.
check 'register_android_view_Surface'
check 'register_android_view_Display'
check 'register_android_graphics_PixelFormat'
# libui behind them
check 'android::SurfaceComposerClient::SurfaceComposerClient()'
check 'android::Surface::lock('
check 'android::Region::'
# the static HAL lookup (dlopen cannot work here)
check 'hw_get_module'
check 'n3ds_gralloc_module'

echo
echo "dlopen must not be reachable from a static binary:"
if "$NM" --undefined-only "$BIN" 2>/dev/null | grep -qE ' dlopen| dlsym'; then
    echo "  FAIL: dlopen/dlsym is an undefined reference"
    fail=1
else
    echo "  OK      (no undefined dlopen/dlsym)"
fi

exit $fail
