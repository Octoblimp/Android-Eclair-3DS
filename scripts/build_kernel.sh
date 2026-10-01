#!/bin/bash
# Build the 3DS kernel and deploy zImage to both SD-card mirrors.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -o pipefail
K="${ANDROID3DS_ROOT}"/third_party/linux
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-
LOG="${ANDROID3DS_ROOT}"/build_kernel.log

# Reproducible public identity. Never leak the local account or machine name
# into /proc/version, dmesg, bug reports, or release artifacts.
export KBUILD_BUILD_USER=Octoblimp
export KBUILD_BUILD_HOST=Android3DS

cd "$K" || exit 1

# CONFIG DRIFT GUARD.
#
# This script builds whatever is in .config and has never regenerated it from
# arch/arm/configs/nintendo3ds_defconfig. That is deliberate -- regenerating
# would discard the live config -- but it meant defconfig edits silently did
# nothing, which is how CONFIG_PM_AUTOSLEEP stayed on through a change that
# turned it off, and how the defconfig drifted so far that using it would have
# built a kernel with no binder, no ashmem and no Wi-Fi.
#
# So: compare, do not overwrite. `savedefconfig` reduces the live .config to
# its minimal form, which is exactly what the tracked defconfig should be.
if [ -f .config ]; then
    make ARCH=arm CROSS_COMPILE="$TC" savedefconfig > /dev/null 2>&1
    # Compare the symbols only. savedefconfig emits no comments, and the
    # tracked file carries a header explaining itself, so a raw cmp would
    # report drift that is not drift.
    _strip() { grep -v "^#" "$1" | grep -v "^[[:space:]]*$"; }
    if [ -f defconfig ] && ! diff -q <(_strip arch/arm/configs/nintendo3ds_defconfig) <(_strip defconfig) > /dev/null; then
        echo "CONFIG DRIFT: .config and nintendo3ds_defconfig disagree." >&2
        echo "  tracked defconfig  <  |  >  live .config" >&2
        diff <(_strip arch/arm/configs/nintendo3ds_defconfig) <(_strip defconfig) >&2
        echo "" >&2
        echo "Reconcile before building. To adopt the live .config:" >&2
        echo "  cp $K/defconfig $K/arch/arm/configs/nintendo3ds_defconfig" >&2
        echo "To adopt the tracked defconfig (DESTROYS the live .config):" >&2
        echo "  make ARCH=arm nintendo3ds_defconfig" >&2
        rm -f defconfig
        exit 1
    fi
    rm -f defconfig
fi
make ARCH=arm CROSS_COMPILE="$TC" -j"$(nproc)" zImage modules > "$LOG" 2>&1
RC=$?
echo "EXIT_CODE=$RC"
if [ $RC -ne 0 ]; then
    echo "--- last 60 lines of $LOG ---"
    tail -60 "$LOG"
    exit $RC
fi

WSL_SD="${ANDROID3DS_ROOT}"/sdcard/linux
WIN_SD="${ANDROID3DS_WIN}/sdcard/linux"
cp "$K/arch/arm/boot/zImage" "$WSL_SD/zImage" || exit 1
cp "$K/arch/arm/boot/zImage" "$WIN_SD/zImage" || exit 1
# System.map has to travel WITH the zImage. It did not, and the two silently
# drifted a kernel apart (deployed #51 zImage vs a #50 System.map, 2026-08-05):
# every address in every photographed backtrace since then would have decoded
# to the wrong symbol. Since reading those backtraces is the main way this port
# is debugged, a stale map is worse than no map.
cp "$K/System.map" "$WSL_SD/System.map" || exit 1
cp "$K/System.map" "$WIN_SD/System.map" || exit 1

# AR6002 firmware mode is consumed during BMI boot. Stage the same reloadable
# module everywhere Android and Mobile Data may load it with fwmode=1 or 2.
MODULE="$K/drivers/staging/ath6k_legacy/ath6kl.ko"
OVERLAY="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay
TARGET="${ANDROID3DS_ROOT}"/third_party/buildroot/output/target
for module_dir in \
    "$OVERLAY/system/lib/modules" \
    "$TARGET/system/lib/modules" \
    "$WSL_SD/android/system/lib/modules" \
    "$WIN_SD/android/system/lib/modules"; do
    mkdir -p "$module_dir" || exit 1
    # Preserve the one authoritative module timestamp in every mirror. The
    # release verifier intentionally treats metadata drift as staging drift.
    cp -p "$MODULE" "$module_dir/ath6kl.ko" || exit 1
    chmod 644 "$module_dir/ath6kl.ko" || exit 1
done
# N3DS_KERNEL_INITRAMFS_MODULE_PAIRING.
#
# The four copies above are the ones Android and Mobile Data load from. There
# is a fifth, and until 2026-09-12 nothing updated it: initramfs.cpio.gz bakes
# its own ath6kl.ko at /n3ds/modules/ath6kl.ko, and that is the copy loaded
# first, before /system is even mounted.
#
# A module is bound to the kernel it was built against by vermagic and build
# ID. Leave the baked copy behind and the next boot insmods a module built for
# the previous kernel, which fails -- and this board has no USB gadget, so
# Wi-Fi ADB on port 5555 is the only shell into it. A kernel rebuild that
# silently removes the way in is the worst failure this script can produce,
# and it is exactly what happened to #301 until the release verifier caught
# the mismatch.
#
# Rebuilding here rather than warning, because a warning in a 600K build log
# is not a guard. build_minimal_initramfs.sh is non-interactive (it pipes the
# sudo password itself) and does not depend on anything the kernel produces
# except this module, so it is safe to chain.
INITRAMFS_BUILD="${ANDROID3DS_ROOT}"/scripts/build_minimal_initramfs.sh
if [ -x "$INITRAMFS_BUILD" ] || [ -f "$INITRAMFS_BUILD" ]; then
    echo "--- refreshing initramfs so its baked ath6kl.ko matches this kernel ---"
    if bash "$INITRAMFS_BUILD" > /tmp/build_kernel_initramfs.log 2>&1; then
        tail -4 /tmp/build_kernel_initramfs.log
    else
        echo "WARNING: initramfs rebuild FAILED -- see /tmp/build_kernel_initramfs.log" >&2
        echo "WARNING: the deployed initramfs still carries the PREVIOUS kernel's Wi-Fi module" >&2
    fi
else
    echo "WARNING: $INITRAMFS_BUILD missing; initramfs ath6kl.ko may be stale" >&2
fi

echo "DEPLOYED"
ls -la "$WSL_SD/zImage" "$WIN_SD/zImage" "$WIN_SD/System.map" \
    "$WIN_SD/android/system/lib/modules/ath6kl.ko"
echo "--- zImage/System.map pairing check ---"
if [ "$(md5sum < "$K/System.map")" = "$(md5sum < "$WIN_SD/System.map")" ]; then
    echo "System.map matches the just-built kernel"
else
    echo "WARNING: System.map deploy did not take"
fi
