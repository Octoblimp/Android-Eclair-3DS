#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-gcc-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
OUT="${ANDROID3DS_ROOT}"/build/init
LOG="$OUT/build.log"

mkdir -p "$OUT/obj"
: > "$LOG"

GCC_INCLUDE="$("$GCC" -print-file-name=include)"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -fno-builtin \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $SYSCORE/init"

echo "=== compiling init sources ==="
OK=0
FAIL=0
FAILED=""
for f in "$SYSCORE"/init/*.c; do
    base="$(basename "$f")"
    [ "$base" = "bootchart.c" ] && continue
    out="$OUT/obj/init__${base%.c}.o"
    if "$GCC" $CFLAGS -c "$f" -o "$out" >>"$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1))
        FAILED="$FAILED $base"
    fi
done

echo "init sources OK=$OK FAIL=$FAIL"
[ -n "$FAILED" ] && echo "failed:$FAILED"

echo "=== compiling needed libcutils sources ==="
for f in memory.c ashmem-dev.c; do
    src="$SYSCORE/libcutils/$f"
    out="$OUT/obj/cutils__${f%.c}.o"
    if "$GCC" $CFLAGS -c "$src" -o "$out" >>"$LOG" 2>&1; then
        echo "OK: $f"
    else
        echo "FAIL: $f"
    fi
done
