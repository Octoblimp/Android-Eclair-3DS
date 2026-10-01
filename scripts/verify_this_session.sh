#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
ROOTFS="${ANDROID3DS_ROOT}"/third_party/buildroot/output/images/rootfs.cpio.gz
V="${ANDROID3DS_ROOT}"/build/services_jar/verify_cpio
a3ds_sudo rm -rf "$V"
mkdir -p "$V"
zcat "$ROOTFS" > "$V/rootfs.cpio"
( cd "$V" && a3ds_sudo cpio -idm < rootfs.cpio > /dev/null 2>&1 )
echo '--- services.jar present + md5 match ---'
ls -la "$V/system/framework/services.jar"
md5sum "$V/system/framework/services.jar" "${ANDROID3DS_ROOT}"/build/services_jar/services.jar
echo '--- BOOTCLASSPATH + socket line ---'
grep -n 'BOOTCLASSPATH\|socket zygote' "$V/init.rc"
echo '--- app_process_debug_smoketest.sh mode + flag ---'
ls -la "$V/etc/app_process_debug_smoketest.sh"
grep -n 'start-system-server\|TIMEOUT=' "$V/etc/app_process_debug_smoketest.sh"
echo '--- bootlog_late.sh mode + sleep ---'
ls -la "$V/etc/bootlog_late.sh"
grep -n '^sleep' "$V/etc/bootlog_late.sh"
