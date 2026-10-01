#!/bin/bash
# Build and stage the root-owned 3DS Telco AP controller.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
WIN_ROOT="${ANDROID3DS_WIN}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"
SRC="$WIN_ROOT/native/mobiledata/mobiledata_apctl.c"
OUT="$ROOT/build/mobiledata_apctl"
TARGET="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin"
CARD="$ROOT/sdcard/linux/android/system/bin"
WIN_CARD="$WIN_ROOT/sdcard/linux/android/system/bin"

test -x "$GCC" || { echo "build_mobiledata_apctl: missing ARM compiler $GCC" >&2; exit 1; }
test -x "$STRIP" || { echo "build_mobiledata_apctl: missing ARM strip $STRIP" >&2; exit 1; }
test -f "$SRC" || { echo "build_mobiledata_apctl: missing source $SRC" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT" "$TARGET"
CFLAGS=( -std=c99 -D_DEFAULT_SOURCE -O2 -Wall -Wextra -Werror )
"$GCC" "${CFLAGS[@]}" -static "$SRC" -o "$OUT/mobiledata_apctl"
"$STRIP" "$OUT/mobiledata_apctl"
chmod 755 "$OUT/mobiledata_apctl"
cp "$OUT/mobiledata_apctl" "$TARGET/mobiledata_apctl"
if [ -d "$CARD" ]; then
    cp "$OUT/mobiledata_apctl" "$CARD/mobiledata_apctl"
    chmod 755 "$CARD/mobiledata_apctl"
fi
if [ -d "$WIN_CARD" ]; then
    cp "$OUT/mobiledata_apctl" "$WIN_CARD/mobiledata_apctl"
    chmod 755 "$WIN_CARD/mobiledata_apctl"
fi

file "$TARGET/mobiledata_apctl" | grep -q 'ARM'
echo '=== build_mobiledata_apctl: ALL OK ==='
sha256sum "$OUT/mobiledata_apctl" "$TARGET/mobiledata_apctl"
