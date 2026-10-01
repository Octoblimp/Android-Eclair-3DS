#!/bin/bash
# Build libagl.a -- Android's software OpenGL ES 1.x implementation
# (upstream module name libGLES_android), on top of libpixelflinger.
#
# This is what SurfaceFlinger composites through. Upstream ships it as a
# .so that libEGL dlopen()s out of /system/lib/egl/; here it is a static
# archive, because every binary in this image is statically linked and
# bionic's dlopen() is a hard NULL for a static executable (see
# scripts/build_libdl.sh's own header). The EGL entry points are therefore
# resolved at link time instead of through libEGL's Loader -- see
# build_libegl.sh.
#
# Source list from opengl/libagl/Android.mk. Deliberate deviations:
#
#   N3DS_BUILTIN_COPYBIT: copybit.cpp and LIBAGL_USE_GRALLOC_COPYBITS are
#   enabled against Android3DS' built-in CPU copybit HAL. Unsupported formats
#   still return an error and retain libagl's pixelflinger fallback.
#
#   -fvisibility=hidden -- dropped. It exists upstream to keep the .so's
#   exported surface to the EGL/GL entry points only. In a static archive it
#   would hide exactly the symbols we need to link against.
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
LIBHW="${ANDROID3DS_ROOT}"/third_party/libhardware
SRC=$FWBASE/opengl/libagl
# N3DS_STATIC_GLES_COMPAT: ABI normally supplied by GLES_CM.so.
COMPAT="${ANDROID3DS_WIN}/native/gles_compat.cpp"

OUT="${ANDROID3DS_ROOT}"/build/libagl
mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/libagl.a

COMMON="-nostdinc -fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks -fstrict-aliasing \
-Wno-attributes -Wno-write-strings -Wno-narrowing -Wno-invalid-offsetof \
-Wno-unused-but-set-variable -Wno-strict-aliasing \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-DLOG_TAG=\"libagl\" -DGL_GLEXT_PROTOTYPES -DEGL_EGLEXT_PROTOTYPES \
-DLIBAGL_USE_GRALLOC_COPYBITS \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/private \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $FWBASE/opengl/include \
-I $LIBHW/include \
-I $SYSCORE/include \
-I $SRC"

CXXFLAGS="-nostdinc++ -std=gnu++98 -fno-exceptions -fno-rtti \
-isystem $($GXX -print-file-name=include) -I $LSTL/include $COMMON"
CFLAGS="-std=gnu89 -fgnu89-inline -Wno-implicit-function-declaration \
-isystem $($GCC -print-file-name=include) $COMMON"

CXX_SRCS="
egl.cpp
copybit.cpp
state.cpp
texture.cpp
Tokenizer.cpp
TokenManager.cpp
TextureObjectManager.cpp
BufferObjectManager.cpp
array.cpp
fp.cpp
light.cpp
matrix.cpp
mipmap.cpp
primitives.cpp
vertex.cpp
"
ASM_SRCS="fixed_asm.S iterators.S"

OK=0; FAIL=0; FAILED=""
for f in $CXX_SRCS; do
    if "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$OUT/obj/${f%.cpp}.o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done
if "$GXX" $CXXFLAGS -c "$COMPAT" -o "$OUT/obj/gles_compat.o" 2>>"$OUT/build.log"; then
    OK=$((OK+1))
else
    FAIL=$((FAIL+1)); FAILED="$FAILED gles_compat.cpp"
fi
for f in $ASM_SRCS; do
    if "$GCC" $CFLAGS -c "$SRC/$f" -o "$OUT/obj/${f%.S}.o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

echo "libagl: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "--- see $OUT/build.log ---"
    exit 1
fi

"$AR" rcs "$OUT/libagl.a" "$OUT"/obj/*.o
ls -la "$OUT/libagl.a"
