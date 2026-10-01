#!/bin/bash
# bionic/libdl -- dlopen/dlsym/dlerror/dlclose.
#
# IMPORTANT: these are genuinely stubs that return 0. In a normal Android
# build libdl.so exists only so callers have something to link against; the
# real implementations live in the dynamic linker and are hijacked at
# runtime. Our userspace is statically linked and has no dynamic linker
# yet, so dlopen() really will always fail here -- meaning Dalvik can start,
# but System.loadLibrary()/JNI shared libraries will not work until the
# bionic linker is ported. Everything the VM does internally is unaffected.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
OUT="${ANDROID3DS_ROOT}"/build/libdl
mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-stack-protector -fno-pic \
-Wno-attributes -Wno-implicit-function-declaration \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include"

"$GCC" $CFLAGS -c "$BIONIC/libdl/libdl.c" -o "$OUT/obj/libdl.o"
"$AR" rcs "$OUT/libdl.a" "$OUT/obj/libdl.o"
echo "libdl.a built (stubs -- dlopen always returns NULL, see comment above)"
