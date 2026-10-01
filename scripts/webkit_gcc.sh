#!/bin/sh
. "$(dirname "$0")/a3ds_env.sh"
set -eu

# N3DS_WEBKIT_UB_FLAGS: see webkit_gxx.sh.  -fno-lifetime-dse is C++-only.
exec "${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-gcc \
    -std=gnu99 -fno-delete-null-pointer-checks -fwrapv \
    -I"${ANDROID3DS_ROOT}"/third_party/libhardware/include "$@"
