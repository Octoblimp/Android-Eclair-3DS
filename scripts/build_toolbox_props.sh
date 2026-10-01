#!/bin/bash
# Build /system/bin/setprop and /system/bin/getprop from system_core/toolbox.
#
# Android's property system is not a filesystem and busybox knows nothing
# about it: properties live in a shared-memory area published by init, read
# through libcutils' property_get()/property_set(). Without these two
# binaries nothing outside a framework process can read or change a property
# -- no way to inspect ro.build.*/ro.sf.lcd_density from the console, and no
# way to send init a control message.
#
# The control message is the immediate need: writing "ctl.stop" = "bootanim"
# is how a process asks init to stop a service and *keep it stopped*
# (init.c's handle_control_message). Killing the process directly does not
# work -- init restarts it, since bootanim is not a oneshot service.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
SRC=$SYSCORE/toolbox

BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/toolbox
LIBGCC="$("$GCC" -print-libgcc-file-name)"

mkdir -p "$OUT/obj"

CFLAGS="-nostdinc -std=gnu89 -fgnu89-inline -fno-stack-protector -fno-pic -O2 \
-Wno-implicit-function-declaration -Wno-attributes -Wno-int-conversion \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include"

# Upstream builds every applet into one multi-call "toolbox" binary whose
# main() dispatches on argv[0], so each applet's entry point is named
# <name>_main. Building them standalone means renaming that back to main.
build_one() {
    name="$1"
    echo "  CC  $name"
    "$GCC" $CFLAGS -D"${name}_main"=main -c "$SRC/$name.c" \
        -o "$OUT/obj/$name.o"
    "$GCC" -nostdlib -static \
        "$BIONIC_OUT/crtbegin.o" \
        "$OUT/obj/$name.o" \
        -Wl,--start-group \
            "$BUILD/libcutils/libcutils.a" \
            "$BUILD/liblog/liblog.a" \
            "$BIONIC_OUT/libc.a" \
            "$LIBGCC" \
        -Wl,--end-group \
        "$BIONIC_OUT/crtend.o" \
        -o "$OUT/$name" \
        -Wl,-e,_start -Wl,--no-warn-mismatch \
        `# bionic's hand-written ARM assembly emits .ARM.exidx entries that
         # reference the unwind personality routines. Nothing here uses
         # exceptions, so define them away -- the same three defsyms every
         # other static link in this tree uses.` \
        -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
        -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
        -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
        2>&1 | grep -v 'missing .note.GNU-stack\|behaviour is deprecated' || true
    if [ ! -f "$OUT/$name" ]; then
        echo "LINK FAILED: $name"
        exit 1
    fi
}

build_one setprop
build_one getprop

DEST="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin
for n in setprop getprop; do
    "$STRIP" -o "$DEST/$n" "$OUT/$n"
    chmod 755 "$DEST/$n"
done
ls -la "$DEST/setprop" "$DEST/getprop"
