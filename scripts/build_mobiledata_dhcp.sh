#!/bin/bash
# Build and stage the bounded 3DS Telco DHCPv4 server.
#
# The source is kept in the Windows workspace; the canonical ARM build and
# deploy trees are in WSL.  This binary is static and is installed in both the
# Buildroot overlay and the staged SD tree when that tree is available.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
WIN_ROOT="${ANDROID3DS_WIN}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"
SRC="$WIN_ROOT/native/mobiledata/mobiledata_dhcp.c"
OUT="$ROOT/build/mobiledata_dhcp"
TARGET="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin"
CARD="$ROOT/sdcard/linux/android/system/bin"
WIN_CARD="$WIN_ROOT/sdcard/linux/android/system/bin"

test -x "$GCC" || { echo "build_mobiledata_dhcp: missing ARM compiler $GCC" >&2; exit 1; }
test -f "$SRC" || { echo "build_mobiledata_dhcp: missing source $SRC" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT" "$TARGET"
CFLAGS=( -std=c99 -D_DEFAULT_SOURCE -O2 -Wall -Wextra -Werror )
"$GCC" "${CFLAGS[@]}" -static "$SRC" -o "$OUT/mobiledata_dhcp"
"$STRIP" "$OUT/mobiledata_dhcp"
chmod 755 "$OUT/mobiledata_dhcp"
cp "$OUT/mobiledata_dhcp" "$TARGET/mobiledata_dhcp"
if [ -d "$CARD" ]; then
    cp "$OUT/mobiledata_dhcp" "$CARD/mobiledata_dhcp"
    chmod 755 "$CARD/mobiledata_dhcp"
fi
if [ -d "$WIN_CARD" ]; then
    cp "$OUT/mobiledata_dhcp" "$WIN_CARD/mobiledata_dhcp"
    chmod 755 "$WIN_CARD/mobiledata_dhcp"
fi

file "$TARGET/mobiledata_dhcp" | grep -q 'ARM'
echo '=== build_mobiledata_dhcp: ALL OK ==='
sha256sum "$OUT/mobiledata_dhcp" "$TARGET/mobiledata_dhcp"
