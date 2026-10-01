#!/bin/bash
# Disassemble the NWM function that populates the host-interest struct.
# 3DS sysmodules load at 0x00100000, which the surrounding literals corroborate
# (file offset 0x0322D8 holds 0x0015D168 -- a .data/.bss pointer under that base).
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
OBJDUMP="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-objdump
BIN="${ANDROID3DS_WIN}/content/code_decompressed.bin"

# Thumb, covering the stores at 0x0322A0..0x0322CC and enough before them to
# see where the stored register gets its value.
$OBJDUMP -D -b binary -m arm -M force-thumb \
    --adjust-vma=0x00100000 \
    --start-address=$((0x00100000 + 0x032180)) \
    --stop-address=$((0x00100000 + 0x0322F0)) \
    "$BIN"
