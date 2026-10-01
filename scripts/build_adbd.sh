#!/bin/bash
# Build Eclair's device-side ADB daemon as a static, TCP-only ARM executable.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
TC="$ROOT/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
BIONIC="$ROOT/third_party/bionic"
SYSCORE="$ROOT/third_party/system_core"
KERNEL="$ROOT/third_party/linux"
SRC="$SYSCORE/adb"
OUT="$ROOT/build/adbd"
BIONIC_OUT="$ROOT/build/bionic"
LIBCUTILS="$ROOT/build/libcutils/libcutils.a"
LIBLOG="$ROOT/build/liblog/liblog.a"
LIBGCC="$("$GCC" -print-libgcc-file-name)"
GCC_INCLUDE="$("$GCC" -print-file-name=include)"
TARGET="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin"

for f in "$BIONIC_OUT/crtbegin.o" "$BIONIC_OUT/libc.a" \
         "$BIONIC_OUT/crtend.o" "$LIBCUTILS" "$LIBLOG" \
         "$ROOT/native/adbd_tcp_usb_stub.c"; do
    test -f "$f" || { echo "build_adbd: missing prerequisite $f" >&2; exit 1; }
done

grep -Fq 'N3DS_ADBD_ROOTFS_SHELL' "$SRC/services.c"
grep -Fq '#define SHELL_COMMAND "/bin/sh"' "$SRC/services.c"
grep -Fq 'N3DS_ADBD_NO_DEVICE_HOST_LISTENER' "$SRC/adb.c"
grep -Fq 'N3DS_ADBD_TCP_FAIL_CLOSED' "$SRC/adb.c"
grep -Fq 'N3DS_ADBD_TCP_READY' "$SRC/transport_local.c"

rm -rf "$OUT"
mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fcommon -fno-stack-protector -fno-pic -fno-builtin \
-Wno-implicit-function-declaration -Wno-int-conversion -Wno-return-type -Wno-attributes \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DADB_HOST=0 \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $GCC_INCLUDE \
-I $BIONIC/libc/include -I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm -I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include -I $SRC -I $KERNEL/include/uapi"

sources=(
    adb.c fdevent.c transport.c transport_local.c transport_usb.c sockets.c
    services.c file_sync_service.c jdwp_service.c framebuffer_service.c
    remount_service.c log_service.c utils.c
)
for name in "${sources[@]}"; do
    "$GCC" $CFLAGS -c "$SRC/$name" -o "$OUT/obj/${name%.c}.o"
done
"$GCC" $CFLAGS -c "$ROOT/native/adbd_tcp_usb_stub.c" \
    -o "$OUT/obj/adbd_tcp_usb_stub.o"

"$GCC" -nostdlib -static "$BIONIC_OUT/crtbegin.o" "$OUT"/obj/*.o \
    -Wl,--start-group "$LIBCUTILS" "$LIBLOG" "$BIONIC_OUT/libc.a" "$LIBGCC" -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" -o "$OUT/adbd" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0

mkdir -p "$TARGET"
cp "$OUT/adbd" "$TARGET/adbd"
chmod 755 "$TARGET/adbd"
file "$TARGET/adbd" | grep -q 'ARM'
echo '=== build_adbd: ALL OK ==='
ls -la "$TARGET/adbd"
