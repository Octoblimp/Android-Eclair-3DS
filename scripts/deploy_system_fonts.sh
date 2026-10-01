#!/bin/bash
# Install the AOSP Eclair system fonts SkFontHost_android.cpp hard-codes.
# Without DroidSans.ttf the first Typeface initialization leaves
# gDefaultFamily null and crashes zygote in find_best_face().
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
SRC="$ROOT/third_party/frameworks/base/data/fonts"
BUILDROOT="$ROOT/third_party/buildroot"
OVERLAY="$BUILDROOT/board/nintendo3ds/rootfs_overlay/system/fonts"
TARGET="$BUILDROOT/output/target/system/fonts"

required=(
    DroidSans.ttf
    DroidSans-Bold.ttf
    DroidSerif-Regular.ttf
    DroidSerif-Bold.ttf
    DroidSerif-Italic.ttf
    DroidSerif-BoldItalic.ttf
    DroidSansMono.ttf
)

for font in "${required[@]}"; do
    test -s "$SRC/$font" || {
        echo "missing required AOSP font: $SRC/$font" >&2
        exit 1
    }
done

mkdir -p "$OVERLAY" "$TARGET"

# Include optional Japanese/fallback faces as well.  The port's Skia backend
# probes these exact Droid*.ttf names and simply skips any optional face that
# is absent, so installing the source set is deterministic and complete.
for font in "$SRC"/Droid*.ttf; do
    cp -f "$font" "$OVERLAY/$(basename "$font")"
    cp -f "$font" "$TARGET/$(basename "$font")"
done
chmod 644 "$OVERLAY"/*.ttf "$TARGET"/*.ttf

echo "=== deployed AOSP system fonts ==="
ls -l "$OVERLAY"/*.ttf
