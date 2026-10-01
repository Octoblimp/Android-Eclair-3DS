#!/bin/bash
# dalvik/libnativehelper -- the tiny JNI convenience layer (jniRegisterNative-
# Methods, jniThrowException, ...) that libdvm and everything JNI-facing above
# it call into.
#
# Register.c is built too, but note it only *declares* the registration entry
# point; the register_java_lang_* functions it calls live in libjavacore (the
# core Java library's native half), which doesn't exist yet -- so anything
# linking Register.c in will have undefined references until libcore is
# ported. It's archived separately so a link can pick JNIHelp.o alone.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
DALVIK="${ANDROID3DS_ROOT}"/third_party/dalvik
NH=$DALVIK/libnativehelper
OUT="${ANDROID3DS_ROOT}"/build/libnativehelper
mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -O2 -fno-stack-protector -fno-pic \
-Wno-attributes -Wno-implicit-function-declaration -Wno-pointer-sign \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $NH/include/nativehelper \
-I $NH/include"

"$GCC" $CFLAGS -c "$NH/JNIHelp.c" -o "$OUT/obj/JNIHelp.o"
"$AR" rcs "$OUT/libnativehelper.a" "$OUT/obj/JNIHelp.o"
echo "libnativehelper.a built (JNIHelp only)"

# Stand-in for Register.c until libjavacore exists -- see the file's own
# comment. Archived separately so a link picks exactly one of the two.
"$GCC" $CFLAGS -c "$NH/android3ds_register_stub.c" -o "$OUT/obj/register_stub.o"
"$AR" rcs "$OUT/libnativehelper_register_stub.a" "$OUT/obj/register_stub.o"
echo "libnativehelper_register_stub.a built (jniRegisterSystemMethods fails loudly)"

if "$GCC" $CFLAGS -c "$NH/Register.c" -o "$OUT/obj/Register.o" 2>"$OUT/register.log"; then
    "$AR" rcs "$OUT/libnativehelper_register.a" "$OUT/obj/Register.o"
    echo "libnativehelper_register.a built (needs libjavacore at link time)"
else
    echo "Register.c did not compile -- see $OUT/register.log (expected until libcore exists)"
fi
