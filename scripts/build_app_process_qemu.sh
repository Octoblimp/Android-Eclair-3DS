#!/bin/bash
# Link the diagnostic app_process with AOSP's host ashmem backend so the real
# ARM zygote can run under qemu-user without a /dev/ashmem device.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

test -s "${ANDROID3DS_ROOT}"/build/libcutils_qemu/libcutils.a || {
    echo "libcutils_qemu missing; run build_dexpreopt_qemu.sh first" >&2
    exit 1
}

QEMU_HOST_ASHMEM=1 bash "${ANDROID3DS_WIN}/scripts/build_app_process_debug.sh"
