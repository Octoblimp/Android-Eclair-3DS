#!/bin/bash
# Build libgralloc_n3ds.a -- the graphics HAL for the bottom screen.
#
# Contents:
#   gralloc.cpp     upstream AOSP reference allocator (unmodified)
#   mapper.cpp      upstream (unmodified) -- cross-process buffer mapping
#   allocator.cpp   upstream (unmodified) -- the best-fit sub-allocator
#   framebuffer.cpp REWRITTEN for the 3DS panel (rotation, scanout offset,
#                   RGB565 -> 24bpp) -- read its header comment
#   hw_get_module_static.cpp
#                   replaces libhardware's dlopen-based module lookup, which
#                   cannot work in a statically linked binary
#
# N3DS_BUILTIN_COPYBIT: copybit_n3ds.cpp is a CPU-backed HAL linked
# into the same static module registry as gralloc.
# HAL_MODULE_INFO_SYM is redefined so the module struct has a unique, linkable
# name instead of the generic "HMI" a .so would export.
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
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
SRC=$LIBHW/modules/gralloc

OUT="${ANDROID3DS_ROOT}"/build/libgralloc
mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/libgralloc_n3ds.a "$OUT"/build.log

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-write-strings -Wno-narrowing -Wno-invalid-offsetof \
-Wno-unused-but-set-variable -Wno-deprecated \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
`# -DNDEBUG: allocator.cpp's "#ifndef NDEBUG" branch calls dump_l(), which
 # this vendored AOSP drop never declares anywhere -- an upstream bug that
 # only surfaces in a debug build. A release AOSP build defines NDEBUG, so
 # this is the configuration the file was actually compiled in.` \
-DNDEBUG \
`# Rename the module struct so it has a unique, linkable symbol instead of
 # the generic "HMI" a .so would export. It has to be spelled -DHMI, not
 # -DHAL_MODULE_INFO_SYM: hardware.h does an unconditional
 # "#define HAL_MODULE_INFO_SYM HMI", which silently overrides a
 # command-line definition of that name the moment the header is included.
 # Defining what it expands *to* survives.` \
-DHMI=n3ds_gralloc_module \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $LIBHW/include \
-I $SYSCORE/include \
-I $SRC"

# hw_get_module_static.cpp must NOT get the HAL_MODULE_INFO_SYM redefinition
# baked into a struct of its own -- it only references the symbol by name.
SRCS="gralloc.cpp mapper.cpp allocator.cpp framebuffer.cpp copybit_n3ds.cpp"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    if "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$OUT/obj/${f%.cpp}.o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

if "$GXX" $CXXFLAGS -c "$SRC/hw_get_module_static.cpp" \
        -o "$OUT/obj/hw_get_module_static.o" 2>>"$OUT/build.log"; then
    OK=$((OK+1))
else
    FAIL=$((FAIL+1)); FAILED="$FAILED hw_get_module_static.cpp"
fi

echo "libgralloc_n3ds: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "--- see $OUT/build.log ---"
    exit 1
fi

"$AR" rcs "$OUT/libgralloc_n3ds.a" "$OUT"/obj/*.o
ls -la "$OUT/libgralloc_n3ds.a"
