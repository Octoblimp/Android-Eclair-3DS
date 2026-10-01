#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
SYSROOT="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/arm-buildroot-linux-gnueabihf/sysroot"
QEMU="$ROOT/toolchain/qemu/qemu-arm-static"
SOURCE="$ROOT/third_party/system_core/libcutils/atomic-android-armv6.S"
TEST="${ANDROID3DS_WIN}/scripts/testdata/armv6_atomic_stress.c"
OUT=/tmp/android3ds-armv6-atomic-stress
OBJ=/tmp/android3ds-armv6-atomic.o

test -x "$GCC"
test -x "$QEMU"
grep -Fq N3DS_ARMV6_SMP_ATOMICS "$SOURCE"

"$GCC" -c "$SOURCE" -o "$OBJ"
"$GCC" -O2 -pthread "$TEST" "$OBJ" -o "$OUT"
"$QEMU" -L "$SYSROOT" "$OUT"
