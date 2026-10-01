#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
SVCMGR="${ANDROID3DS_ROOT}"/third_party/frameworks/base/cmds/servicemanager
OUT="${ANDROID3DS_ROOT}"/build/servicemanager
LOG="$OUT/build.log"

mkdir -p "$OUT/obj"
: > "$LOG"

GCC_INCLUDE="$("$GCC" -print-file-name=include)"

# $KERNEL/include/uapi comes LAST, after all of bionic's own kernel headers,
# not before. Raw kernel uapi headers aren't meant to be consumed directly
# by userspace (e.g. uapi/linux/stddef.h pulls in linux/compiler_types.h,
# which only exists inside a real kernel build tree) -- bionic ships its own
# pre-sanitized copies of the common ones (posix_types.h, types.h, etc) and
# those need to win. The only thing we actually need from the real kernel
# tree is linux/android/binder.h, which bionic doesn't have at all, so it's
# safe to fall through to the kernel copy (built with -DBINDER_IPC_32BIT,
# see drivers/android/Makefile) only for that one header.
CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -fno-builtin \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DBINDER_IPC_32BIT \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include \
-I $SVCMGR \
-I $KERNEL/include/uapi"

echo "=== compiling servicemanager sources ==="
OK=0
FAIL=0
FAILED=""
for f in binder.c service_manager.c; do
    src="$SVCMGR/$f"
    out="$OUT/obj/svcmgr__${f%.c}.o"
    if "$GCC" $CFLAGS -c "$src" -o "$out" >>"$LOG" 2>&1; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1))
        FAILED="$FAILED $f"
    fi
done
echo "servicemanager sources OK=$OK FAIL=$FAIL"
[ -n "$FAILED" ] && echo "failed:$FAILED"

echo "=== compiling needed liblog sources ==="
for f in logd_write.c; do
    src="$SYSCORE/liblog/$f"
    out="$OUT/obj/liblog__${f%.c}.o"
    if "$GCC" $CFLAGS -c "$src" -o "$out" >>"$LOG" 2>&1; then
        echo "OK: $f"
    else
        echo "FAIL: $f"
    fi
done

echo "=== compiling needed libcutils sources ==="
for f in memory.c ashmem-dev.c; do
    src="$SYSCORE/libcutils/$f"
    out="$OUT/obj/cutils__${f%.c}.o"
    if "$GCC" $CFLAGS -c "$src" -o "$out" >>"$LOG" 2>&1; then
        echo "OK: $f"
    else
        echo "FAIL: $f"
    fi
done
