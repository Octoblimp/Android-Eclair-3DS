#!/bin/bash
# liblog built with FAKE_LOG_DEVICE=1 -- a host/debug variant that writes log
# output to stderr instead of /dev/log/*.
#
# Why this exists: on real hardware liblog talks to the kernel logger driver
# (ported in Phase 3), so LOGE/LOGI from Dalvik land in logcat. Under
# qemu-arm-static there is no /dev/log/main, logd_write.c's open() fails, and
# every log call is silently dropped -- which is how "Dalvik VM init failed
# (check log file)" ends up with no log file to check. Linking a test binary
# against THIS archive instead of build/liblog/liblog.a makes the VM's own
# diagnostics visible in the qemu terminal.
#
# Do NOT ship this variant on the device image; it is a debugging aid only.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
OUT="${ANDROID3DS_ROOT}"/build/liblog_fake
mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -fno-builtin \
-DFAKE_LOG_DEVICE=1 \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $KERNEL/include/uapi"

for f in logd_write.c fake_log_device.c logprint.c; do
    "$GCC" $CFLAGS -c "$SYSCORE/liblog/$f" -o "$OUT/obj/${f%.c}.o"
done
"$AR" rcs "$OUT/liblog.a" "$OUT"/obj/*.o
echo "liblog_fake/liblog.a built (logs to stderr -- host/qemu debugging only)"
