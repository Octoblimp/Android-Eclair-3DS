#!/bin/bash
# Build/deploy Eclair's default binary key-character map. ViewRoot asks for it
# whenever a physical key may leave touch mode.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
TP="$ROOT/third_party"
OUT="$ROOT/build/keychars"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$TP/buildroot/output/target"
KCM_SRC="$TP/build_system/target/board/generic/tuttle2.kcm"

rm -rf "$OUT"
mkdir -p "$OUT" "$OVERLAY/system/usr/keychars" "$TARGET/system/usr/keychars"

g++ -std=gnu++98 \
    -I"$TP/frameworks/base/include" \
    -I"$TP/system_core/include" \
    "$TP/build_system/tools/kcm/kcm.cpp" -o "$OUT/kcm"

"$OUT/kcm" "$KCM_SRC" "$OUT/qwerty.kcm.bin"
test "$(stat -c %s "$OUT/qwerty.kcm.bin")" -gt 128
cp "$OUT/qwerty.kcm.bin" "$OVERLAY/system/usr/keychars/qwerty.kcm.bin"
cp "$OUT/qwerty.kcm.bin" "$TARGET/system/usr/keychars/qwerty.kcm.bin"
chmod 644 "$OVERLAY/system/usr/keychars/qwerty.kcm.bin" \
    "$TARGET/system/usr/keychars/qwerty.kcm.bin"
# #324/#325: one map per key device (hw.keyboards.N.devname), or
# KeyCharacterMap logs "Can't open keycharmap file" and falls back.
for dev in n3ds_navigation hid_buttons mcu_buttons; do
    for dir in "$OVERLAY" "$TARGET"; do
        cp "$OUT/qwerty.kcm.bin" "$dir/system/usr/keychars/$dev.kcm.bin"
        chmod 644 "$dir/system/usr/keychars/$dev.kcm.bin"
    done
done
echo '=== build_keychars: ALL OK ==='
ls -la "$OVERLAY/system/usr/keychars/qwerty.kcm.bin"
