#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AS="$TC/arm-buildroot-linux-gnueabihf-as"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic

OUT=/tmp/bionic_test2
mkdir -p "$OUT"

echo "=== assembling crtbegin_static.S ==="
"$GCC" \
    -nostdinc \
    -I "$BIONIC/libc/arch-arm/include" \
    -I "$BIONIC/libc/include" \
    -I "$BIONIC/libc/kernel/common" \
    -I "$BIONIC/libc/kernel/arch-arm" \
    -c "$BIONIC/libc/arch-arm/bionic/crtbegin_static.S" \
    -o "$OUT/crtbegin_static.o"
echo "exit=$?"

echo "=== compiling bionic/fork.c ==="
"$GCC" \
    -nostdinc -nostdlib \
    -std=gnu89 -fgnu89-inline \
    -fno-stack-protector -fno-pic \
    -Wno-implicit-function-declaration \
    -isystem "$($GCC -print-file-name=include)" \
    -I "$BIONIC/libc/include" \
    -I "$BIONIC/libc/kernel/common" \
    -I "$BIONIC/libc/kernel/arch-arm" \
    -I "$BIONIC/libc/arch-arm/include" \
    -I "$BIONIC/libc/private" \
    -c "$BIONIC/libc/bionic/fork.c" \
    -o "$OUT/fork.o" > "$OUT/fork.log" 2>&1
echo "exit=$?"
cat "$OUT/fork.log"

echo "=== done ==="
ls -la "$OUT"
