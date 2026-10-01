#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

ROOT="${ANDROID3DS_ROOT}"
TC=$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
CC=$TC/arm-buildroot-linux-gnueabihf-gcc
SRC="${ANDROID3DS_WIN}/native/pica200_smoketest.c"
BOOTLOG="${ANDROID3DS_WIN}/scripts/dump_bootlog.sh"
OUT=$ROOT/build/pica200_smoketest
OVERLAY=$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay

mkdir -p "$OUT" "$OVERLAY/system/bin"
"$CC" -static -Os -Wall -Wextra \
    -I "$ROOT/third_party/linux/include/uapi" \
    -I "$ROOT/third_party/linux/include" \
    "$SRC" -o "$OUT/pica200_smoketest"
cp "$OUT/pica200_smoketest" "$OVERLAY/system/bin/pica200_smoketest"
chmod 0755 "$OVERLAY/system/bin/pica200_smoketest"
cp "$BOOTLOG" "$OVERLAY/etc/dump_bootlog.sh"
chmod 0755 "$OVERLAY/etc/dump_bootlog.sh"
file "$OUT/pica200_smoketest"
echo "build_pica200_smoketest: deployed"
