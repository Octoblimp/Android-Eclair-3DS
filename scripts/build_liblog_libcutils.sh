#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux

GCC_INCLUDE="$("$GCC" -print-file-name=include)"
CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -fno-builtin \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $KERNEL/include/uapi"

ASFLAGS="-nostdinc -D__ARM_EABI__ -DANDROID \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include"

LOG_OUT="${ANDROID3DS_ROOT}"/build/liblog
CUTILS_OUT="${ANDROID3DS_ROOT}"/build/libcutils
mkdir -p "$LOG_OUT/obj" "$CUTILS_OUT/obj"

echo "=== liblog ==="
# logprint.c + event_tag_map.c are upstream liblog members too (see
# system_core/liblog/Android.mk). Nothing needed them until /system/bin/logcat
# existed -- it is the only consumer of android_log_format_new(),
# android_log_processLogBuffer(), android_log_filterAndPrintLogLine() and
# android_openEventTagMap(). Without them logcat fails to link with 14
# undefined references.
for f in logd_write.c logprint.c event_tag_map.c; do
    "$GCC" $CFLAGS -c "$SYSCORE/liblog/$f" -o "$LOG_OUT/obj/${f%.c}.o"
done
"$AR" rcs "$LOG_OUT/liblog.a" "$LOG_OUT"/obj/*.o

echo "=== libcutils ==="
# atomic.c only provides the 64-bit "quasiatomic" ops on ARM (mutex-based) --
# the real 32-bit android_atomic_add/inc/dec/or/cmpxchg primitives live in
# atomic-android-armv6.S (LDREX/STREX-era file, matches our ARM11/ARMv6
# target exactly; the plain atomic-android-arm.S is the older SWP-based
# fallback for pre-ARMv6 and isn't needed here).
#
# mspace.c is a wrapper that #includes bionic's dlmalloc.c with MSPACES /
# ONLY_MSPACES / USE_CONTIGUOUS_MSPACES set, producing the mspace_*() and
# create_contiguous_mspace_with_name() entry points. Dalvik's heap
# (vm/alloc/HeapSource.c) is built entirely on those -- without this file
# libdvm has ~13 undefined references and cannot link.
#
# sched_policy.c provides set_sched_policy(), used by Dalvik's thread
# creation to drop background threads into the bg_non_interactive cgroup.
# adb_networking.c: libcore's java_net_InetAddress.cpp and
# OSNetworkSystem.cpp call adb_networking_gethostbyname()/
# adb_networking_connect_fd() unconditionally (it is the "connect through the
# host over adb" path, which no-ops to a normal socket when adb networking is
# off), so libjavacore will not link without it.
#
# strdup8to16.c: provides strcpylen8to16()/strdup8to16(), which libjavacore's
# ExpatParser uses to hand UTF-8 from expat to Java as UTF-16.
#
# tztime.c: mktime_tz()/localtime_tz(), the Olson-timezone-aware time
# functions core/jni/Time.cpp (android.text.format.Time's native half) calls
# -- distinct from libcore's own java.util.TimeZone/ICU path, which is why
# dalvikvm linked clean without it but app_process didn't.
for f in atomic.c memory.c ashmem-dev.c native_handle.c process_name.c threads.c properties.c socket_local_client.c socket_local_server.c socket_loopback_client.c socket_loopback_server.c socket_network_client.c socket_inaddr_any_server.c mspace.c sched_policy.c adb_networking.c strdup8to16.c tztime.c; do
    "$GCC" $CFLAGS -c "$SYSCORE/libcutils/$f" -o "$CUTILS_OUT/obj/${f%.c}.o"
done
"$GCC" $ASFLAGS -c "$SYSCORE/libcutils/atomic-android-armv6.S" -o "$CUTILS_OUT/obj/atomic-android-armv6.o"
"$AR" rcs "$CUTILS_OUT/libcutils.a" "$CUTILS_OUT"/obj/*.o
echo "liblog.a + libcutils.a built"
