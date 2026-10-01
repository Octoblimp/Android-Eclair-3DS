#!/bin/bash
# Rebuild the entire native (C/C++) Android stack in dependency order.
#
# Needed whenever something reaches EVERY translation unit -- in practice
# system_core/include/arch/linux-arm/AndroidConfig.h, which every
# scripts/build_*.sh -include's on every source file. The 2026-08-04 NDEBUG
# change (see that header's own comment) is exactly such a change: without a
# full rebuild the tree ends up half release-logging and half verbose, and the
# stale-.a trap on record in docs/HANDOFF.md means a clean link with zero
# undefined references proves nothing about which objects actually got rebuilt.
#
# Order is the dependency order from docs/HANDOFF.md's own build/deploy recaps.
# Anything that only produces a host tool (aapt, aidl, dx) or a Java artifact
# (core.jar, framework.jar, services.jar) is deliberately NOT here -- none of
# it is affected by a C preprocessor define.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -o pipefail

# There are TWO script directories, and neither is a superset of the other.
# The Windows-side one is the documented, load-bearing one; the compositor
# session (2026-08-04) created its scripts WSL-natively instead and they were
# never moved. Search both rather than silently skipping half the stack.
S_WIN="${ANDROID3DS_WIN}/scripts"
S_WSL="${ANDROID3DS_ROOT}/scripts"
LOG="${ANDROID3DS_ROOT}"/rebuild_native_stack.log
: > "$LOG"

find_script() {
    if [ -f "$S_WIN/$1" ]; then echo "$S_WIN/$1"
    elif [ -f "$S_WSL/$1" ]; then echo "$S_WSL/$1"
    fi
}

run() {
    local path
    path="$(find_script "$1")"
    if [ -z "$path" ]; then
        echo "FAILED: $1 not found in $S_WIN or $S_WSL" | tee -a "$LOG"
        exit 1
    fi
    echo "=== $1 ($path) ===" | tee -a "$LOG"
    if ! bash "$path" >> "$LOG" 2>&1; then
        echo "FAILED: $1 (see $LOG)" | tee -a "$LOG"
        echo "--- last 40 lines ---"
        tail -40 "$LOG"
        exit 1
    fi
}

# Eclair's ARM JNI trampoline uses the base AAPCS, while this port's glibc
# toolchain defaults to hard-float.  Make every scalar float/double JNI entry
# explicit before compiling either libjavacore or libandroid_runtime.  The
# source rewrite is audited and idempotent.
python3 "$S_WIN/apply_float_jni_abi.py" --apply \
    "${ANDROID3DS_ROOT}"/third_party/frameworks/base/core/jni \
    "${ANDROID3DS_ROOT}"/third_party/dalvik/libcore/luni/src/main/native \
    "${ANDROID3DS_ROOT}"/third_party/dalvik/libcore/icu/src/main/native \
    >> "$LOG"

# Foundations: log/cutils first, everything else references them.
run build_liblog_libcutils.sh
run build_bionic_compat.sh
run build_libstdcxx.sh
run build_libutils.sh
run build_libbinder.sh
# build_servicemanager.sh / build_init.sh only compile objects -- the final
# link is a separate script, and forgetting it leaves a *stale binary* next to
# freshly compiled .o files, which is invisible unless you check timestamps.
run build_servicemanager.sh
run link_servicemanager.sh
run build_installd.sh

# init is its own bionic binary and lives in the initramfs, not on the card.
run build_init.sh
run link_init.sh

# Dalvik + its dependencies (libdex, libdvm, libnativehelper, libm, libdl,
# dalvikvm) in one go.
run build_dalvik_stack.sh
run build_libjavacore.sh
run build_dexopt.sh

# Compositor stack, bottom-up. Each of these self-deploys.
run build_libhardware.sh
run build_libpixelflinger.sh
run build_libagl.sh
run build_gralloc.sh
run build_libui.sh
run build_surfaceflinger.sh

# The runtime and the two binaries that link everything above.
# NEVER skip build_libandroid_runtime.sh before app_process -- stale .a trap.
run build_libandroid_runtime.sh
run build_services_jni.sh
run build_app_process.sh
run build_app_process_debug.sh
run deploy_compositor.sh

# Standalone binaries.
run build_bootanimation.sh
run build_logcat.sh
run build_toolbox_props.sh
run build_dsp_chime.sh

# ---------------------------------------------------------------------------
# Deploy stage.
#
# Deployment in this tree is inconsistent: some build scripts strip+copy into
# the rootfs overlay themselves (surfaceflinger, logcat, setprop/getprop),
# deploy_compositor.sh does app_process, and several -- servicemanager,
# dexopt, bootanimation -- have never done it at all. The result on
# 2026-08-04 was an overlay holding a mix of binaries from four different
# days, where "I rebuilt everything" and "the card has everything I built"
# were quietly different statements. Everything the boot actually runs is
# deployed here, explicitly, every time.
# ---------------------------------------------------------------------------
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"
BUILD="${ANDROID3DS_ROOT}"/build
OVERLAY="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay

deploy() { # deploy <built binary> <destination>
    if [ ! -f "$1" ]; then
        echo "FAILED: nothing to deploy at $1" | tee -a "$LOG"
        exit 1
    fi
    mkdir -p "$(dirname "$2")"
    "$STRIP" -o "$2" "$1"
    chmod 755 "$2"
}

echo "=== deploying to the rootfs overlay ==="
deploy "$BUILD/bootanimation/bootanimation" "$OVERLAY/system/bin/bootanimation"
deploy "$BUILD/dexopt/dexopt"               "$OVERLAY/system/bin/dexopt"
deploy "$BUILD/installd/installd"           "$OVERLAY/system/bin/installd"
deploy "$BUILD/servicemanager/servicemanager" "$OVERLAY/usr/sbin/servicemanager"
ls -la "$OVERLAY/system/bin/" "$OVERLAY/usr/sbin/servicemanager"

echo
echo "NOTE: /init lives in the initramfs, not the overlay -- run"
echo "      scripts/build_minimal_initramfs.sh to pick up $BUILD/init/init."
echo "NOTE: scripts/sync_android_to_sdcard.sh still has to run to push the"
echo "      overlay onto sdcard/."
echo "=== rebuild_native_stack: ALL OK ==="
