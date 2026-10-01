#!/bin/bash
# Build and stage the bounded, read-only 3DS Telco status endpoint.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
WIN_ROOT="${ANDROID3DS_WIN}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"
SRC="$WIN_ROOT/native/mobiledata/mobiledata_status.c"
OUT="$ROOT/build/mobiledata_status"
TARGET="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin"
CARD="$ROOT/sdcard/linux/android/system/bin"
WIN_CARD="$WIN_ROOT/sdcard/linux/android/system/bin"

test -x "$GCC" || { echo "build_mobiledata_status: missing ARM compiler $GCC" >&2; exit 1; }
test -x "$STRIP" || { echo "build_mobiledata_status: missing ARM strip $STRIP" >&2; exit 1; }
test -f "$SRC" || { echo "build_mobiledata_status: missing source $SRC" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT" "$TARGET"
CFLAGS=( -std=c99 -D_DEFAULT_SOURCE -O2 -Wall -Wextra -Werror )
"$GCC" "${CFLAGS[@]}" -static "$SRC" -o "$OUT/mobiledata_status"
"$STRIP" "$OUT/mobiledata_status"
chmod 755 "$OUT/mobiledata_status"
cp "$OUT/mobiledata_status" "$TARGET/mobiledata_status"
if [ -d "$CARD" ]; then
    cp "$OUT/mobiledata_status" "$CARD/mobiledata_status"
    chmod 755 "$CARD/mobiledata_status"
fi
if [ -d "$WIN_CARD" ]; then
    cp "$OUT/mobiledata_status" "$WIN_CARD/mobiledata_status"
    chmod 755 "$WIN_CARD/mobiledata_status"
fi

file "$TARGET/mobiledata_status" | grep -q 'ARM'
file "$TARGET/mobiledata_status" | grep -q 'statically linked'
echo '=== build_mobiledata_status: ALL OK ==='
sha256sum "$OUT/mobiledata_status" "$TARGET/mobiledata_status"
