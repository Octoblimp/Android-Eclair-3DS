#!/bin/bash
# Build libpixelflinger.a -- Android's software rasterizer.
#
# This is the bottom of the compositor stack. libagl (the software OpenGL ES
# 1.x implementation) is a thin GL state machine on top of it, and
# SurfaceFlinger composites through libagl. There is no GPU driver on this
# hardware and there never will be without a PICA200 driver, so this *is* the
# graphics pipeline.
#
# Source list taken from system_core/libpixelflinger/Android.mk's
# PIXELFLINGER_SRC_FILES (the LOCAL_MODULE:=libpixelflinger_static variant),
# plus the two ARM assembly files the arm branch adds.
#
# Note on codeflinger: it is a *runtime JIT* -- GGLAssembler emits ARM machine
# code for the exact scanline blend the current GL state needs, into a
# CodeCache, and calls it. That is not optional decoration; scanline.cpp's
# generic C path exists but the assembler path is what makes this usable at
# 268 MHz. It needs an executable heap: CodeCache.cpp mprotects its pages
# PROT_EXEC, which works fine here (no SELinux, no W^X enforcement).
#
# -DWITH_LIB_HARDWARE is deliberately NOT set: it pulls in
# libhardware_legacy's overlay/copybit glue, which needs HAL modules that
# don't exist on this device.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL=$BIONIC/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
SRC=$SYSCORE/libpixelflinger

OUT="${ANDROID3DS_ROOT}"/build/libpixelflinger
mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/libpixelflinger.a

COMMON="-nostdinc -fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-fstrict-aliasing -fomit-frame-pointer \
-Wno-attributes -Wno-write-strings -Wno-narrowing -Wno-unused-but-set-variable \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $SRC"

CXXFLAGS="-nostdinc++ -std=gnu++98 -fno-exceptions -fno-rtti \
-isystem $($GXX -print-file-name=include) -I $LSTL/include $COMMON"
CFLAGS="-std=gnu89 -fgnu89-inline -Wno-implicit-function-declaration \
-isystem $($GCC -print-file-name=include) $COMMON"

CXX_SRCS="
codeflinger/ARMAssemblerInterface.cpp
codeflinger/ARMAssemblerProxy.cpp
codeflinger/ARMAssembler.cpp
codeflinger/CodeCache.cpp
codeflinger/GGLAssembler.cpp
codeflinger/load_store.cpp
codeflinger/blending.cpp
codeflinger/texturing.cpp
tinyutils/SharedBuffer.cpp
tinyutils/VectorImpl.cpp
fixed.cpp
picker.cpp
pixelflinger.cpp
trap.cpp
scanline.cpp
format.cpp
clear.cpp
raster.cpp
buffer.cpp
"
C_SRCS="codeflinger/disassem.c"
# -march=armv6 per Android.mk's LOCAL_ASFLAGS for the armv6 sub-module.
ASM_SRCS="rotate90CW_4x4_16v6.S t32cb16blend.S"

OK=0; FAIL=0; FAILED=""

for f in $CXX_SRCS; do
    o="$OUT/obj/$(echo "$f" | tr / _ | sed 's/\.cpp$/.o/')"
    if "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

for f in $C_SRCS; do
    o="$OUT/obj/$(echo "$f" | tr / _ | sed 's/\.c$/.o/')"
    if "$GCC" $CFLAGS -c "$SRC/$f" -o "$o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

for f in $ASM_SRCS; do
    o="$OUT/obj/${f%.S}.o"
    if "$GCC" $CFLAGS -march=armv6 -c "$SRC/$f" -o "$o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

echo "libpixelflinger: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "--- see $OUT/build.log ---"
    exit 1
fi

"$AR" rcs "$OUT/libpixelflinger.a" "$OUT"/obj/*.o
ls -la "$OUT/libpixelflinger.a"
