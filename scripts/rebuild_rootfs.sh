#!/bin/bash
# Full rebuild + deploy pipeline. As of the "everything off the
# initramfs" migration (see docs/HANDOFF.md), buildroot's own
# output/images/rootfs.cpio.gz is no longer what boots the device --
# it's still built (buildroot is still how busybox/wpa_supplicant/our
# rootfs_overlay content gets assembled), but only as a source tree that
# gets synced onto the SD card and a tiny hand-built initramfs.
#
# This is the one command that leaves initramfs.cpio.gz AND the SD-card
# android/ tree correct and in sync -- see
# scripts/sync_android_to_sdcard.sh's header for why splitting this into
# two manually-run steps would be a mistake.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ROOT="$ANDROID3DS_ROOT"
SCRIPTS_WIN="$ANDROID3DS_WIN/scripts"
SDCARD_WIN="$ANDROID3DS_WIN/sdcard"

echo "=== [1/4] buildroot make (produces output/target/{system,etc,usr}) ==="
cd "$ROOT/third_party/buildroot"
make -j8 2>&1 | tail -40

echo "=== [2/4] syncing system/etc/usr onto sd:/linux/android/ ==="
bash "$SCRIPTS_WIN/sync_android_to_sdcard.sh"

echo "=== [3/4] building the minimal initramfs (init + init.rc + busybox symlink forest) ==="
bash "$SCRIPTS_WIN/build_minimal_initramfs.sh"

echo "=== [4/4] deploying initramfs.cpio.gz ==="
cp "$ROOT/build/minimal_initramfs/initramfs.cpio.gz" "$SDCARD_WIN/linux/initramfs.cpio.gz"
ls -la "$SDCARD_WIN/linux/initramfs.cpio.gz"
md5sum "$ROOT/build/minimal_initramfs/initramfs.cpio.gz" "$SDCARD_WIN/linux/initramfs.cpio.gz"

echo "=== done ==="
