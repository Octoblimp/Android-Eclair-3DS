#!/bin/bash
# Deploy services.jar (android.policy + SystemServer + am/ + status/, see
# build_services_jar.sh) to both rootfs_overlay and output/target (buildroot's
# output/target is additive -- see docs/HANDOFF.md
# [[feedback_buildroot_target_is_additive]]) and extend BOOTCLASSPATH in both
# init.rc copies. Real AOSP puts services.jar on BOOTCLASSPATH too (not some
# separate system_server-only classpath) because ZygoteInit.startSystemServer()
# forks the already-running zygote process (Zygote.forkSystemServer(), a raw
# native fork()) rather than exec'ing a new process with a different
# classpath -- com.android.server.SystemServer has to already be resolvable
# by the zygote's own bootstrap classloader before the fork ever happens.
#
# Does NOT rebuild rootfs.cpio.gz or touch sdcard/ -- that happens once at the
# end after every Phase 6 change for this session lands (see
# docs/HANDOFF.md "Immediate next steps").
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

SVC_JAR="${ANDROID3DS_ROOT}"/build/services_jar/services.jar
BUILDROOT="${ANDROID3DS_ROOT}"/third_party/buildroot
OVERLAY="$BUILDROOT/board/nintendo3ds/rootfs_overlay"
TARGET="$BUILDROOT/output/target"

test -s "$SVC_JAR" || { echo "services.jar missing, run build_services_jar.sh first"; exit 1; }

echo "=== deploying services.jar to both overlay copies ==="
cp -v "$SVC_JAR" "$OVERLAY/system/framework/services.jar"
cp -v "$SVC_JAR" "$TARGET/system/framework/services.jar"

echo "=== extending BOOTCLASSPATH in both init.rc copies (idempotent) ==="
for RC in "$OVERLAY/init.rc" "$TARGET/init.rc"; do
    if ! grep -q 'BOOTCLASSPATH.*services\.jar' "$RC"; then
        sed -i 's#export BOOTCLASSPATH /system/framework/core.jar:/system/framework/framework.jar#export BOOTCLASSPATH /system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar#' "$RC"
    fi
    grep -n "BOOTCLASSPATH" "$RC" | head -1
done
