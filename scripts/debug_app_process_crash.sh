#!/bin/bash
# One-shot: launch app_process --zygote under qemu-arm-static's gdbserver,
# attach GDB, print a backtrace at the crash and quit. Scratch debugging
# script, not part of the deploy chain.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
QEMU="${ANDROID3DS_ROOT}"/toolchain/qemu/qemu-arm-static
GDB="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin/arm-buildroot-linux-gnueabihf-gdb
BIN="${ANDROID3DS_ROOT}"/build/app_process/app_process

cd "${ANDROID3DS_ROOT}"/build/app_process
"$QEMU" -g 1234 "$BIN" /system/bin --zygote >/tmp/qemu_app_process.log 2>&1 &
QPID=$!
sleep 1

"$GDB" -q -batch \
  -ex "target remote localhost:1234" \
  -ex "continue" \
  -ex "bt" \
  -ex "info registers pc lr sp" \
  -ex "x/8i \$pc" \
  "$BIN"

kill "$QPID" 2>/dev/null || true
