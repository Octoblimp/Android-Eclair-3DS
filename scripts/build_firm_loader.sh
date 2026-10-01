#!/bin/bash
# Build firm_linux_loader and deploy it to the SD-card mirrors.
#
# This is the ARM9-side first-stage loader: it mounts the SD card with FatFs,
# copies zImage / initramfs.cpio.gz / the DTB / arm9linuxfw into FCRAM, then
# releases the ARM11 and jumps to arm9linuxfw. It is what data-aborted on
# 2026-08-03 when the initramfs outgrew its 8 MiB window.
#
# Toolchain: the loader targets an ARM946E-S (ARMv5TE) with newlib, so it uses
# the distro arm-none-eabi-gcc, NOT the buildroot armv6-eabihf toolchain the
# rest of the project uses. The Makefiles reference plain $(CC), so it has to
# be passed on the command line (which make then propagates to the sub-makes).
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -o pipefail
L="${ANDROID3DS_ROOT}"/third_party/firm_linux_loader
LOG="${ANDROID3DS_ROOT}"/build_firm_loader.log

export PATH="$HOME/.local/bin:$PATH"   # firmtool is a pip --user install
export PYTHONPATH="$HOME/.local/lib/python3.14/site-packages:${PYTHONPATH:-}"

command -v arm-none-eabi-gcc > /dev/null || { echo "no arm-none-eabi-gcc"; exit 1; }
command -v firmtool          > /dev/null || { echo "no firmtool"; exit 1; }

cd "$L" || exit 1
make CC=arm-none-eabi-gcc clean > /dev/null 2>&1
make CC=arm-none-eabi-gcc > "$LOG" 2>&1
RC=$?
echo "EXIT_CODE=$RC"
if [ $RC -ne 0 ]; then
    echo "--- last 40 lines of $LOG ---"
    tail -40 "$LOG"
    exit $RC
fi

WSL_SD="${ANDROID3DS_ROOT}"/sdcard/luma/payloads
WIN_SD="${ANDROID3DS_WIN}/sdcard/luma/payloads"
mkdir -p "$WSL_SD"
# Luma runs luma/payloads/<button>_<name>.firm when that button is held at
# boot. Exactly ONE payload ships: down_firm_linux_loader.firm (hold D-pad
# DOWN while powering on). The unprefixed firm_linux_loader.firm copy that used
# to sit next to it was the same image twice; it is deleted here on every
# build so a stale one can never come back, and build_sdcard_zip.sh refuses to
# pack a card that still has it.
for d in "$WSL_SD" "$WIN_SD"; do
    rm -f "$d/firm_linux_loader.firm"
    cp "$L/firm_linux_loader.firm" "$d/down_firm_linux_loader.firm" || exit 1
done
echo "DEPLOYED"
ls -la "$WIN_SD"
