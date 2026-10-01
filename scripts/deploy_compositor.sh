#!/bin/bash
# Strip and deploy the compositor-era binaries into the rootfs overlay.
#
# app_process/app_process_debug are relinked with libui + gralloc + libagl +
# libpixelflinger (see patch_app_process_compositor_libs.py); surfaceflinger
# and logcat are new. None of the build scripts deploy app_process itself, by
# long-standing convention in this tree.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"
BUILD="${ANDROID3DS_ROOT}"/build
DEST="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin

"$STRIP" -o "$DEST/app_process"       "$BUILD/app_process/app_process"
"$STRIP" -o "$DEST/app_process_debug" "$BUILD/app_process_debug/app_process_debug"

chmod 755 "$DEST/app_process" "$DEST/app_process_debug" \
          "$DEST/surfaceflinger" "$DEST/logcat"

ls -la "$DEST/app_process" "$DEST/app_process_debug" \
       "$DEST/surfaceflinger" "$DEST/logcat"
