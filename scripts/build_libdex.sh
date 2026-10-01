#!/bin/bash
# dalvik/libdex -- the .dex file reader/verifier. First piece of the Dalvik
# stack; libdvm, dexopt, dexdump and dexlist all link against it.
#
# Deps that had to exist first: libz (scripts/build_zlib.sh, for
# ZipArchive.c) and external/safe-iop (header-only, used by DexSwapVerify.c).
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
DALVIK="${ANDROID3DS_ROOT}"/third_party/dalvik
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib
SAFEIOP="${ANDROID3DS_ROOT}"/third_party/safe-iop/include
OUT="${ANDROID3DS_ROOT}"/build/libdex
mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-stack-protector -fno-pic \
-Wno-attributes -Wno-implicit-function-declaration -Wno-pointer-sign \
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
-I $DALVIK/libnativehelper/include/nativehelper \
-I $ZLIB \
-I $SAFEIOP"

# Exactly the dex_src_files list from dalvik/libdex/Android.mk.
SRCS="CmdUtils.c DexCatch.c DexClass.c DexDataMap.c DexFile.c DexInlines.c \
DexProto.c DexSwapVerify.c InstrUtils.c Leb128.c OptInvocation.c sha1.c \
SysUtil.c ZipArchive.c"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    if "$GCC" $CFLAGS -c "$DALVIK/libdex/$f" -o "$OUT/obj/${f%.c}.o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done
echo "libdex: OK=$OK FAIL=$FAIL"
[ -n "$FAILED" ] && { echo "failed:$FAILED"; echo "see $OUT/build.log"; exit 1; }
"$AR" rcs "$OUT/libdex.a" "$OUT"/obj/*.o
echo "libdex.a built: $("$AR" t "$OUT/libdex.a" | wc -l) objects"
