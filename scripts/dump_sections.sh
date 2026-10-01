#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
OD="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-objdump
BIN="${ANDROID3DS_ROOT}"/build/init/init
"$OD" -h "$BIN" | grep -E "preinit|init_array|fini_array|ctors"
echo ---
"$OD" -s -j .preinit_array "$BIN"
"$OD" -s -j .init_array "$BIN"
"$OD" -s -j .ctors "$BIN"
