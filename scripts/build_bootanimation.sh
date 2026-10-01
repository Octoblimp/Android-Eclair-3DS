#!/bin/bash
# Build /system/bin/bootanimation.
#
# This is frameworks/base/cmds/bootanimation, with the SurfaceFlinger/EGL/
# GLES/Skia backend replaced by a direct framebuffer one (DisplayTarget.cpp)
# and a small PNG decoder (PngDecode.cpp). The animation logic, the
# bootanimation.zip format and its ZipFileRO reader are upstream's.
#
# Built statically: the dynamic linker works, but a static binary has no
# ordering dependency on /system/lib being populated, and this runs very early.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL=$BIONIC/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
SRC=$FWBASE/cmds/bootanimation
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib

BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/bootanimation
LIBGCC="$("$GCC" -print-libgcc-file-name)"

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o

# Same flags as libutils (see build_libutils.sh for why -std=gnu++98 and the
# -include AndroidConfig.h are needed).
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $ZLIB \
-I $SRC"

SRCS="bootanimation_main.cpp BootAnimation.cpp DisplayTarget.cpp PngDecode.cpp"

for f in $SRCS; do
    echo "  CXX $f"
    "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$OUT/obj/${f%.cpp}.o"
done

echo "  LD  bootanimation"
"$GXX" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" \
    "$OUT"/obj/*.o \
    `# Force libutils' Static.o into the link -- see link_dalvikvm.sh for the
     # full explanation. Without it initialize_string8() never runs and the
     # empty String8 that String8("desc.txt").getPathDir() returns crashes.` \
    -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE \
    -Wl,--start-group \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog_fake/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        "$BUILD/libm/libm.a" \
        "$BIONIC_OUT/libc.a" \
        "$LIBGCC" \
    -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/bootanimation" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0

ls -la "$OUT/bootanimation"
file "$OUT/bootanimation"
