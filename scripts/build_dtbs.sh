#!/bin/bash
# Build both device trees and deploy them to the SD-card mirrors.
#
# Split out of build_kernel.sh because the DTS carries the initrd window
# (/chosen/linux,initrd-start,-end), which changes independently of the kernel
# image itself.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -o pipefail
K="${ANDROID3DS_ROOT}"/third_party/linux
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-
LOG="${ANDROID3DS_ROOT}"/build_dtbs.log

cd "$K" || exit 1
make ARCH=arm CROSS_COMPILE="$TC" -j"$(nproc)" \
    nintendo3ds_ctr.dtb nintendo3ds_ktr.dtb > "$LOG" 2>&1
RC=$?
echo "EXIT_CODE=$RC"
if [ $RC -ne 0 ]; then
    echo "--- last 40 lines of $LOG ---"
    tail -40 "$LOG"
    exit $RC
fi

WSL_SD="${ANDROID3DS_ROOT}"/sdcard/linux
WIN_SD="${ANDROID3DS_WIN}/sdcard/linux"
for dtb in nintendo3ds_ctr.dtb nintendo3ds_ktr.dtb; do
    cp "$K/arch/arm/boot/dts/$dtb" "$WSL_SD/$dtb" || exit 1
    cp "$K/arch/arm/boot/dts/$dtb" "$WIN_SD/$dtb" || exit 1
done
echo "DEPLOYED"
ls -la "$WIN_SD"/*.dtb

# Read the values back out of the built blob rather than trusting the source.
echo "--- /chosen in nintendo3ds_ktr.dtb ---"
if command -v fdtdump > /dev/null 2>&1; then
    fdtdump "$K/arch/arm/boot/dts/nintendo3ds_ktr.dtb" 2>/dev/null \
        | grep -A6 "chosen {"
fi
