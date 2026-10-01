#!/bin/bash
# Build and stage dsp_chime, the best-effort DSP boot-chime helper (see
# native/dsp_chime.c for exactly what it does and does not claim).
#
# Source, compilation and the deployable Buildroot overlay all live in the
# canonical WSL tree. The source used to be read out of the Windows workspace,
# where nothing version-controlled it even though the resulting binary IS
# tracked at sdcard/linux/android/system/bin/dsp_chime; see docs/SOURCE_OF_TRUTH.md.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

ROOT="${ANDROID3DS_ROOT}"
TC=$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
CC=$TC/arm-buildroot-linux-gnueabihf-gcc
SRC="$ROOT/native/dsp_chime.c"
OUT=$ROOT/build/dsp_chime
OVERLAY=$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay

test -x "$CC" || { echo "build_dsp_chime: missing ARM compiler $CC" >&2; exit 1; }
test -f "$SRC" || { echo "build_dsp_chime: missing $SRC" >&2; exit 1; }

mkdir -p "$OUT" "$OVERLAY/system/bin"
"$CC" -static -Os -Wall -Wextra \
    -I "$ROOT/third_party/linux/include/uapi" \
    -I "$ROOT/third_party/linux/include" \
    "$SRC" -o "$OUT/dsp_chime"
cp "$OUT/dsp_chime" "$OVERLAY/system/bin/dsp_chime"
chmod 0755 "$OVERLAY/system/bin/dsp_chime"
file "$OUT/dsp_chime" | grep -q 'ARM'
echo "build_dsp_chime: deployed"
ls -l "$OVERLAY/system/bin/dsp_chime"
