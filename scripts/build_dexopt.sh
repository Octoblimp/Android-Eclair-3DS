#!/bin/bash
# Build /system/bin/dexopt.
#
# Dalvik does not optimize a DEX in-process: dvmContinueOptimization() forks
# and execs /system/bin/dexopt to do it in a separate process. With that binary
# missing, every bootclasspath entry fails to prepare and the VM gives up with
#
#   execv '/system/bin/dexopt' failed: No such file or directory
#   Unable to extract+optimize DEX from '/system/framework/core.jar'
#   ERROR: no valid entries found in bootclasspath '/system/framework/core.jar'
#
# which is exactly what the 2026-08-03 boot log showed once core.jar existed.
#
# Upstream links it against libdvm as a shared library ("fully integrated with
# the VM"); here it is static, like everything else in this initramfs.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
DALVIK="${ANDROID3DS_ROOT}"/third_party/dalvik
BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/dexopt
LIBGCC="$("$GCC" -print-libgcc-file-name)"

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-delete-null-pointer-checks -fno-stack-protector -fno-pic \
-Wno-attributes -Wno-implicit-function-declaration \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $DALVIK \
-I $DALVIK/vm \
-I $DALVIK/libdex \
-I $DALVIK/include \
-I $DALVIK/libnativehelper/include/nativehelper"

echo "  CC  OptMain.c"
"$GCC" $CFLAGS -c "$DALVIK/dexopt/OptMain.c" -o "$OUT/obj/OptMain.o"

echo "  LD  dexopt"
# g++ drives the link: libdvm is C++ and pulls in libstdc++/libutils.
"$GXX" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" \
    "$OUT/obj/OptMain.o" \
    `# see link_dalvikvm.sh -- libutils' Static.o must be forced in or every
     # empty String8 dereferences NULL` \
    -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE \
    -Wl,--start-group \
        "$BUILD/libdvm/libdvm.a" \
        "$BUILD/libdex/libdex.a" \
        "$BUILD/libnativehelper/libnativehelper.a" \
        `# Real Register.c + libjavacore, same as dalvikvm -- dexopt runs the
         # VM in optimization mode and registers the same core natives.` \
        "$BUILD/libnativehelper/libnativehelper_register.a" \
        "$BUILD/libjavacore/libjavacore.a" \
        "$BUILD/icu4c/libicui18n.a" \
        "$BUILD/icu4c/libicuuc.a" \
        "$BUILD/icu4c/libicudata.a" \
        "$BUILD/openssl/libssl.a" \
        "$BUILD/openssl/libcrypto.a" \
        "$BUILD/sqlite/libsqlite.a" \
        "$BUILD/expat/libexpat.a" \
        "$BUILD/fdlibm/libfdlibm.a" \
        "$BUILD/bionic_compat/libbionic_compat.a" \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog_fake/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        "$BUILD/libm/libm.a" \
        "$BUILD/libdl/libdl.a" \
        "$BIONIC_OUT/libc.a" \
        "$LIBGCC" \
    -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/dexopt" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>&1 | grep -v "GNU-stack\|deprecated" || true

if [ ! -f "$OUT/dexopt" ]; then
    echo "LINK FAILED"
    exit 1
fi
ls -la "$OUT/dexopt"
file "$OUT/dexopt"
