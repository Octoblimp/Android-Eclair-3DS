#!/bin/bash
# Build the ARM9 companion firmware used after firm_linux_loader has loaded
# Linux into FCRAM, then deploy the exact result to both SD mirrors.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
SRC="$ROOT/third_party/arm9linuxfw"
WSL_SD="$ROOT/sdcard/linux/arm9linuxfw.bin"
WIN_SD="${ANDROID3DS_WIN}/sdcard/linux/arm9linuxfw.bin"
LOG="$ROOT/build_arm9linuxfw.log"

command -v arm-none-eabi-gcc >/dev/null || {
    echo "FATAL: arm-none-eabi-gcc is not installed" >&2
    exit 1
}

make -C "$SRC" clean > "$LOG" 2>&1
make -C "$SRC" >> "$LOG" 2>&1 || {
    echo "FATAL: arm9linuxfw build failed" >&2
    tail -60 "$LOG"
    exit 1
}

test -s "$SRC/arm9linuxfw.bin" || {
    echo "FATAL: build produced no arm9linuxfw.bin" >&2
    exit 1
}

mkdir -p "$(dirname "$WSL_SD")" "$(dirname "$WIN_SD")"
cp "$SRC/arm9linuxfw.bin" "$WSL_SD"
cp "$SRC/arm9linuxfw.bin" "$WIN_SD"
chmod 644 "$WSL_SD" "$WIN_SD"

echo "=== deployed ARM9 firmware copies ==="
sha256sum "$SRC/arm9linuxfw.bin" "$WSL_SD" "$WIN_SD"
cmp -s "$SRC/arm9linuxfw.bin" "$WSL_SD"
cmp -s "$SRC/arm9linuxfw.bin" "$WIN_SD"
