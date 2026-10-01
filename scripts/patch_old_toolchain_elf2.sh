#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -x
PATCHELF="${ANDROID3DS_ROOT}"/toolchain/patchelf/bin/patchelf
INTERP="${ANDROID3DS_ROOT}"/toolchain/i386-compat/usr/lib/i386-linux-gnu/ld-linux.so.2
LIBDIR="${ANDROID3DS_ROOT}"/toolchain/i386-compat/usr/lib/i386-linux-gnu
TC="${ANDROID3DS_ROOT}"/third_party/prebuilt/linux-x86/toolchain/arm-eabi-4.4.0

for f in \
    "$TC/bin/arm-eabi-gcc-4.4.0" \
    "$TC/bin/arm-eabi-as" \
    "$TC/bin/arm-eabi-ld" \
    "$TC/bin/arm-eabi-ar" \
    "$TC/bin/arm-eabi-ranlib" \
    "$TC/bin/arm-eabi-objcopy" \
    "$TC/bin/arm-eabi-nm" \
    "$TC/bin/arm-eabi-strip" \
    "$TC/bin/arm-eabi-readelf" \
    "$TC/libexec/gcc/arm-eabi/4.4.0/cc1" \
    "$TC/libexec/gcc/arm-eabi/4.4.0/cc1plus" \
    "$TC/libexec/gcc/arm-eabi/4.4.0/collect2" \
    ; do
    echo "patching: $f"
    "$PATCHELF" --set-interpreter "$INTERP" --set-rpath "$LIBDIR" "$f"
done

echo DONE
