#!/bin/bash
# Build /system/bin/logcat.
#
# Why this matters more than it looks: the real /system/bin/app_process links
# the real liblog, which writes every ALOG*/Log.i/Slog call to /dev/log/main
# -- the kernel logger char device Phase 3 ported. Nothing in this image ever
# read that device, so the framework's entire log was write-only. That is the
# whole reason every boot so far had to run app_process_debug (liblog_fake,
# FAKE_LOG_DEVICE=1, log -> stderr) and redirect stderr into a file, which on
# a 256 MB no-swap device meant an unbounded tmpfs file. logcat replaces that
# arrangement with the mechanism Android actually uses.
#
# Upstream Android.mk is trivial: logcat.cpp + liblog. It uses <cutils/logd.h>
# and <cutils/logprint.h>, so libcutils' log_prints/logprint.c comes along.
#
# Built statically, like every other binary in this image.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL=$BIONIC/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
SRC=$SYSCORE/logcat

BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/logcat
LIBGCC="$("$GCC" -print-libgcc-file-name)"

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o

# Same flag set as every other C++ target here -- see docs/HANDOFF.md's
# "Critical C++ build gotchas": -std=gnu++98 (GCC 14 makes char16_t a
# keyword, colliding with Eclair's own typedef) and the forced
# AndroidConfig.h include (HAVE_PTHREADS/HAVE_ANDROID_OS/... are otherwise
# silently undefined).
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings -Wno-narrowing \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include"

echo "  CXX logcat.cpp"
"$GXX" $CXXFLAGS -c "$SRC/logcat.cpp" -o "$OUT/obj/logcat.o"

echo "  LD  logcat"
"$GXX" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" \
    "$OUT"/obj/*.o \
    -Wl,--start-group \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/libm/libm.a" \
        "$BIONIC_OUT/libc.a" \
        "$LIBGCC" \
    -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/logcat" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0

ls -la "$OUT/logcat"
file "$OUT/logcat"

# Deploy (stripped) into the rootfs overlay's /system/bin, same as every
# other framework binary.
DEST="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin
"$TC/arm-buildroot-linux-gnueabihf-strip" -o "$DEST/logcat" "$OUT/logcat"
chmod 755 "$DEST/logcat"
echo "deployed: $DEST/logcat"
ls -la "$DEST/logcat"
