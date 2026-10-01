#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
exec "${ANDROID3DS_ROOT}"/toolchain/i386-compat/usr/lib/i386-linux-gnu/ld-linux.so.2 \
    --library-path "${ANDROID3DS_ROOT}"/toolchain/i386-compat/usr/lib/i386-linux-gnu \
    "${ANDROID3DS_ROOT}"/third_party/prebuilt/linux-x86/toolchain/arm-eabi-4.4.0/bin/arm-eabi-gcc-4.4.0 --version
