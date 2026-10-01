#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
OUT="${ANDROID3DS_ROOT}"/build/bionic
GCC_INCLUDE="$("$GCC" -print-file-name=include)"
LIBGCC="$("$GCC" -print-libgcc-file-name)"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -fno-builtin \
-Wno-implicit-function-declaration \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include"

echo "=== compiling crt objects ==="
"$GCC" $CFLAGS -c "$BIONIC/libc/arch-arm/bionic/crtbegin_static.S" -o "$OUT/crtbegin.o"
"$GCC" $CFLAGS -c "$BIONIC/libc/arch-arm/bionic/crtend.S" -o "$OUT/crtend.o"
echo "OK"

echo "=== writing + compiling test.c ==="
cat > /tmp/bionic_hello.c <<'EOF'
#include <unistd.h>

int main(void) {
    write(1, "hello from real bionic on nintendo 3ds\n", 40);
    _exit(0);
    return 0;
}
EOF

"$GCC" $CFLAGS -c /tmp/bionic_hello.c -o "$OUT/hello.o"
echo "OK"

echo "=== linking static test binary ==="
"$GCC" -nostdlib -static \
    "$OUT/crtbegin.o" \
    "$OUT/hello.o" \
    -Wl,--start-group "$OUT/libc.a" "$LIBGCC" -Wl,--end-group \
    "$OUT/crtend.o" \
    -o "$OUT/hello_bionic" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0

echo "=== link result ==="
ls -la "$OUT/hello_bionic"
"$TC/arm-buildroot-linux-gnueabihf-readelf" -h "$OUT/hello_bionic" | grep -E "Class|Machine|Type|Entry"
