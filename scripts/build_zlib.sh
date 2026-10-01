#!/bin/bash
# libz for the bionic target. Dalvik's libdex (ZipArchive.c, the .dex/.jar
# reader) and the deferred libutils Zip*/Asset* files all need it, so it has
# to exist before any of the Dalvik work can link.
#
# Source is AOSP external/zlib at the android-2.0_r1 tag -- the genuine
# Eclair copy, not a modern upstream zlib, so its API/ABI matches what the
# 2009 callers in dalvik/ and frameworks/base/ expect.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib
OUT="${ANDROID3DS_ROOT}"/build/zlib
mkdir -p "$OUT/obj"

# Same -nostdinc + bionic-headers discipline as every other target lib here;
# see docs/HANDOFF.md "Critical C++ build gotchas" (the AndroidConfig.h and
# include-order points apply to C too).
CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O3 -DUSE_MMAP -fno-stack-protector -fno-pic \
-Wno-attributes -Wno-implicit-function-declaration \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $ZLIB"

# Exactly the zlib_files list from external/zlib/Android.mk.
SRCS="adler32.c compress.c crc32.c gzio.c uncompr.c deflate.c trees.c \
zutil.c inflate.c infback.c inftrees.c inffast.c"

for f in $SRCS; do
    "$GCC" $CFLAGS -c "$ZLIB/$f" -o "$OUT/obj/${f%.c}.o"
done
"$AR" rcs "$OUT/libz.a" "$OUT"/obj/*.o
echo "libz.a built: $("$AR" t "$OUT/libz.a" | wc -l) objects"
