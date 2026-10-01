#!/bin/bash
# Runs the real init binary as root, but inside a private mount+pid+uts
# namespace (unshare) so any mount()/mknod() syscalls it makes are fully
# isolated from and invisible to the real WSL host, and vanish when the
# namespace's processes exit. Nothing here can affect the host.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
INIT="${ANDROID3DS_ROOT}"/build/init/init
QEMU="${ANDROID3DS_ROOT}"/toolchain/qemu/qemu-arm-static

a3ds_sudo timeout -s KILL 4 unshare --mount --uts --pid --fork --mount-proc -- \
    stdbuf -o0 -e0 "$QEMU" -strace "$INIT" > /tmp/init_isolated.log 2>&1
echo "exit=$?"
