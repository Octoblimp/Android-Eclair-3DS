#!/bin/bash
# Build and stage the root-owned Mobile Data secret bridge.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
WIN_ROOT="${ANDROID3DS_WIN}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
SRC="$WIN_ROOT/native/mobiledata_ipc.c"
OUT="$ROOT/build/mobiledata_ipc"
TARGET="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin"
CARD="$ROOT/sdcard/linux/android/system/bin"
WIN_CARD="$WIN_ROOT/sdcard/linux/android/system/bin"

test -x "$GCC" || { echo "build_mobiledata_ipc: missing ARM compiler $GCC" >&2; exit 1; }
test -f "$SRC" || { echo "build_mobiledata_ipc: missing source $SRC" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT" "$TARGET"
CFLAGS=( -std=c99 -D_GNU_SOURCE -O2 -Wall -Wextra -Werror )
"$GCC" "${CFLAGS[@]}" -static "$SRC" -o "$OUT/mobiledata_ipc"
chmod 755 "$OUT/mobiledata_ipc"
cp "$OUT/mobiledata_ipc" "$TARGET/mobiledata_ipc"
if [ -d "$CARD" ]; then
    cp "$OUT/mobiledata_ipc" "$CARD/mobiledata_ipc"
    chmod 755 "$CARD/mobiledata_ipc"
fi
if [ -d "$WIN_CARD" ]; then
    cp "$OUT/mobiledata_ipc" "$WIN_CARD/mobiledata_ipc"
    chmod 755 "$WIN_CARD/mobiledata_ipc"
fi
file "$TARGET/mobiledata_ipc" | grep -q 'ARM'
echo '=== build_mobiledata_ipc: ALL OK ==='
ls -l "$TARGET/mobiledata_ipc"
