#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
BIONIC_OUT="${ANDROID3DS_ROOT}"/build/bionic
OUT="${ANDROID3DS_ROOT}"/build/servicemanager
LIBGCC="$("$GCC" -print-libgcc-file-name)"

"$GCC" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" \
    "$OUT"/obj/*.o \
    -Wl,--start-group "$BIONIC_OUT/libc.a" "$LIBGCC" -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/servicemanager" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>&1 | grep -oE "undefined reference to \`[a-zA-Z0-9_]+'" | sort -u
