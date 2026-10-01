#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/third_party/prebuilt/linux-x86/toolchain/arm-eabi-4.4.0/bin
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic

OUT=/tmp/bionic_test
mkdir -p "$OUT"

echo "=== compiling crtbegin_static.S ==="
"$TC/arm-eabi-gcc-4.4.0" \
    -I "$BIONIC/libc/arch-arm/include" \
    -I "$BIONIC/libc/include" \
    -I "$BIONIC/libc/kernel/common" \
    -I "$BIONIC/libc/kernel/arch-arm" \
    -c "$BIONIC/libc/arch-arm/bionic/crtbegin_static.S" \
    -o "$OUT/crtbegin_static.o"
echo "OK: crtbegin_static.o"

echo "=== compiling a real libc .c file (bionic/fork.c) ==="
"$TC/arm-eabi-gcc-4.4.0" \
    -I "$BIONIC/libc/include" \
    -I "$BIONIC/libc/kernel/common" \
    -I "$BIONIC/libc/kernel/arch-arm" \
    -I "$BIONIC/libc/arch-arm/include" \
    -I "$BIONIC/libc/private" \
    -c "$BIONIC/libc/bionic/fork.c" \
    -o "$OUT/fork.o"
echo "OK: fork.o"

"$TC/arm-eabi-readelf" -h "$OUT/fork.o" | grep -E "Class|Machine|Type"
