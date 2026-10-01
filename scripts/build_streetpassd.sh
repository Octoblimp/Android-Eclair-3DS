#!/bin/bash
# Build and stage the target-side StreetPass daemon. This source is kept in
# the Windows workspace so it is visible to the project, while compilation and
# the deployable Buildroot overlay remain in canonical WSL storage.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
WIN_ROOT="${ANDROID3DS_WIN}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
SRC="$WIN_ROOT/native/streetpassd"
OUT="$ROOT/build/streetpassd"
TARGET="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin"
CARD="$ROOT/sdcard/linux/android/system/bin"
WIN_CARD="$WIN_ROOT/sdcard/linux/android/system/bin"

test -x "$GCC" || { echo "build_streetpassd: missing ARM compiler $GCC" >&2; exit 1; }
for source in streetpass_protocol.c streetpass_config.c streetpass_journal.c streetpass_radio.c streetpass_adb_proxy.c streetpass_session.c streetpass_led.c streetpassd.c; do
    test -f "$SRC/$source" || { echo "build_streetpassd: missing $SRC/$source" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/obj" "$TARGET"
CFLAGS=( -std=c99 -D_DEFAULT_SOURCE -O2 -Wall -Wextra -Werror -I "$SRC" )
for source in streetpass_protocol.c streetpass_config.c streetpass_journal.c streetpass_radio.c streetpass_adb_proxy.c streetpass_session.c streetpass_led.c streetpassd.c; do
    "$GCC" "${CFLAGS[@]}" -c "$SRC/$source" -o "$OUT/obj/${source%.c}.o"
done
"$GCC" -static "${CFLAGS[@]}" "$OUT"/obj/*.o -o "$OUT/streetpassd"
chmod 755 "$OUT/streetpassd"
cp "$OUT/streetpassd" "$TARGET/streetpassd"
if [ -d "$CARD" ]; then
    cp "$OUT/streetpassd" "$CARD/streetpassd"
    chmod 755 "$CARD/streetpassd"
fi
if [ -d "$WIN_CARD" ]; then
    cp "$OUT/streetpassd" "$WIN_CARD/streetpassd"
    chmod 755 "$WIN_CARD/streetpassd"
fi
file "$TARGET/streetpassd" | grep -q 'ARM'
echo '=== build_streetpassd: ALL OK ==='
ls -l "$TARGET/streetpassd"
