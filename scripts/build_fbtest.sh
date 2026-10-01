#!/bin/bash
# Build /system/bin/fbtest -- the fb1 orientation probe.
#
# Same flags and link line as build_bootanimation.sh, and deliberately reuses
# that binary's DisplayTarget.cpp unmodified: the whole point is to exercise
# the exact code path the animation uses, so whatever the photo shows is
# directly attributable to present().
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL=$BIONIC/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
SRC=$FWBASE/cmds/bootanimation
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib

BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/fbtest
LIBGCC="$("$GCC" -print-libgcc-file-name)"

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
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
-I $SYSCORE/include \
-I $ZLIB \
-I $SRC"

for f in fbtest.cpp DisplayTarget.cpp; do
    echo "  CXX $f"
    "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$OUT/obj/${f%.cpp}.o"
done

echo "  LD  fbtest"
"$GXX" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" \
    "$OUT"/obj/*.o \
    -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE \
    -Wl,--start-group \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog_fake/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        "$BUILD/libm/libm.a" \
        "$BIONIC_OUT/libc.a" \
        "$LIBGCC" \
    -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/fbtest" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0

ls -la "$OUT/fbtest"
