#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
PATCHELF=/tmp/patchelf/bin/patchelf
INTERP="${ANDROID3DS_ROOT}"/toolchain/i386-compat/usr/lib/i386-linux-gnu/ld-linux.so.2
LIBDIR="${ANDROID3DS_ROOT}"/toolchain/i386-compat/usr/lib/i386-linux-gnu
TC="${ANDROID3DS_ROOT}"/third_party/prebuilt/linux-x86/toolchain/arm-eabi-4.4.0

count=0
patched=0
while IFS= read -r -d '' f; do
    count=$((count+1))
    if file "$f" | grep -q "ELF 32-bit LSB executable\|ELF 32-bit LSB.*shared object"; then
        if "$PATCHELF" --print-interpreter "$f" >/dev/null 2>&1; then
            "$PATCHELF" --set-interpreter "$INTERP" --set-rpath "$LIBDIR" "$f" 2>/dev/null && patched=$((patched+1))
        fi
    fi
done < <(find "$TC" -type f -executable -print0)

echo "scanned=$count patched=$patched"
