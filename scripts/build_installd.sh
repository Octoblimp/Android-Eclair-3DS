#!/bin/bash
# Build Eclair's installd against the same static bionic/libcutils stack as
# the rest of this port. PackageManager needs it to assign application UIDs.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
BIONIC="$ROOT/third_party/bionic"
SYSCORE="$ROOT/third_party/system_core"
KERNEL="$ROOT/third_party/linux"
SRC="$ROOT/third_party/frameworks/base/cmds/installd"
OUT="$ROOT/build/installd"
BIONIC_OUT="$ROOT/build/bionic"
LIBCUTILS="$ROOT/build/libcutils/libcutils.a"
LIBLOG="$ROOT/build/liblog/liblog.a"
LIBGCC="$("$GCC" -print-libgcc-file-name)"
GCC_INCLUDE="$("$GCC" -print-file-name=include)"

for f in "$BIONIC_OUT/crtbegin.o" "$BIONIC_OUT/libc.a" \
         "$BIONIC_OUT/crtend.o" "$LIBCUTILS" "$LIBLOG"; do
    test -f "$f" || { echo "build_installd: missing prerequisite $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -fno-builtin \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/include -I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm -I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include -I $SRC -I $KERNEL/include/uapi"

for name in installd commands utils; do
    "$GCC" $CFLAGS -c "$SRC/$name.c" -o "$OUT/obj/$name.o"
done

"$GCC" -nostdlib -static "$BIONIC_OUT/crtbegin.o" "$OUT"/obj/*.o \
    -Wl,--start-group "$LIBCUTILS" "$LIBLOG" "$BIONIC_OUT/libc.a" "$LIBGCC" -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" -o "$OUT/installd" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0

test -x "$OUT/installd"
echo '=== build_installd: ALL OK ==='
ls -la "$OUT/installd"
