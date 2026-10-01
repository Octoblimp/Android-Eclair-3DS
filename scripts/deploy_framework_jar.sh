#!/bin/bash
# Deploy framework.jar to both rootfs_overlay and output/target (buildroot's
# output/target is additive, not regenerated from the overlay -- both need
# every change, see docs/HANDOFF.md [[feedback_buildroot_target_is_additive]]),
# add it to BOOTCLASSPATH in both init.rc copies, rebuild rootfs.cpio.gz, and
# copy the result to sdcard/linux/initramfs.cpio.gz.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

FW_JAR="${ANDROID3DS_ROOT}"/build/framework_jar/framework.jar
BUILDROOT="${ANDROID3DS_ROOT}"/third_party/buildroot
OVERLAY="$BUILDROOT/board/nintendo3ds/rootfs_overlay"
TARGET="$BUILDROOT/output/target"

test -s "$FW_JAR" || { echo "framework.jar missing, run build_framework_jar.sh first"; exit 1; }

echo "=== deploying framework.jar to both overlay copies ==="
cp -v "$FW_JAR" "$OVERLAY/system/framework/framework.jar"
cp -v "$FW_JAR" "$TARGET/system/framework/framework.jar"

echo "=== updating BOOTCLASSPATH in both init.rc copies (idempotent) ==="
for RC in "$OVERLAY/init.rc" "$TARGET/init.rc"; do
    if ! grep -q 'BOOTCLASSPATH.*framework\.jar' "$RC"; then
        sed -i 's#export BOOTCLASSPATH /system/framework/core.jar#export BOOTCLASSPATH /system/framework/core.jar:/system/framework/framework.jar#' "$RC"
    fi
    grep -n "BOOTCLASSPATH" "$RC" | head -1
done

echo "=== rebuilding rootfs.cpio.gz ==="
bash "${ANDROID3DS_ROOT}"/scripts/rebuild_rootfs.sh

ROOTFS="${ANDROID3DS_ROOT}"/third_party/buildroot/output/images/rootfs.cpio.gz
ls -la "$ROOTFS"

echo "=== verifying framework.jar + BOOTCLASSPATH present in the freshly built cpio ==="
V="${ANDROID3DS_ROOT}"/build/framework_jar/verify_cpio
rm -rf "$V"
mkdir -p "$V"
# Verification only needs these two regular files.  Extracting the complete
# rootfs as root left device-owned files under build/framework_jar, causing
# the next build's `rm -rf "$OUT"` to fail with hundreds of permission
# errors.  A selective, unprivileged extraction is sufficient and leaves a
# repeatably clean build directory.
( cd "$V" && zcat "$ROOTFS" | cpio -idm --no-absolute-filenames \
    init.rc system/framework/framework.jar )
ls -la "$V/system/framework/framework.jar"
grep "BOOTCLASSPATH" "$V/init.rc"
md5sum "$V/system/framework/framework.jar" "$FW_JAR"
