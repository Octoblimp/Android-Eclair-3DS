#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
QEMU="$ROOT/toolchain/qemu/qemu-arm-static"
INSTALLD="$PROJECT/sdcard/linux/android/system/bin/installd"
HELPER="$PROJECT/scripts/test_installd_qemu.py"
FAKEROOT="$(mktemp -d /tmp/android3ds-installd-test.XXXXXX)"
trap 'rm -rf "$FAKEROOT"' EXIT

test -x "$QEMU"
test -x "$INSTALLD"
mkdir -p "$FAKEROOT/data/data"
a3ds_sudo unshare --mount -- \
    python3 "$HELPER" "$QEMU" "$INSTALLD" \
    "$FAKEROOT/installd.sock" "$FAKEROOT/data"
