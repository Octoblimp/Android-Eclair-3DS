#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e
TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL="${ANDROID3DS_ROOT}"/third_party/bionic/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
UTILS=$FWBASE/libs/utils
ZLIB="${ANDROID3DS_ROOT}"/third_party/zlib
OUT="${ANDROID3DS_ROOT}"/build/libutils
mkdir -p "$OUT/obj"

# -std=gnu++98: modern GCC (14.x) makes char16_t/char32_t built-in keywords
# from C++11 on, which collides with Eclair's own
# "typedef uint16_t char16_t;" in String16.h/String8.h. Building as pre-C++11
# sidesteps that entirely and matches what this 2009-era code actually
# expects.
#
# -include .../AndroidConfig.h: old Android.mk builds injected this
# platform-config header into every single TU. Without it, HAVE_PTHREADS /
# HAVE_PRCTL / HAVE_ANDROID_OS / HAVE_SYS_UIO_H / OS_PATH_SEPARATOR are all
# silently undefined, causing (respectively) Threads.cpp #error's, and a
# `struct iovec` redefinition clash between bionic's own header and
# cutils/uio.h's Win32 fallback copy (which only backs off via
# `#ifdef HAVE_SYS_UIO_H`).
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti -fno-stack-protector -fno-pic -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-invalid-offsetof \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $SYSCORE/include \
-I $ZLIB \
-I ${ANDROID3DS_ROOT}/third_party/icu4c/common"

# Core subset, plus the resource-table infrastructure. BackupData/
# BackupHelpers/ZipFileCRO stay out -- only the backup manager needs them,
# and that JNI registration is deliberately cut in AndroidRuntime.cpp for now
# (see build_libandroid_runtime.sh).
#
# FileMap/ZipUtils/ZipFileRO are in: bootanimation reads bootanimation.zip
# through ZipFileRO, which is the same reader upstream uses, so the archive
# format (including the stored-entries-only rule in movie()) is upstream's
# rather than a reimplementation. They only needed zlib on the include path.
# Unicode.cpp is in now too: it needs ICU's unicode/utf16.h, and ICU4C is
# built (see build_icu4c.sh), so the reason it was excluded no longer holds.
#
# Asset/AssetDir/AssetManager/ResourceTypes are in as of the app_process
# link: BitmapFactory, Typeface and AssetManager's own JNI glue in
# libandroid_runtime all need real APK/resource-table reading, not stubs --
# this is the Res_png_9patch / AssetManager:: / ResTable:: / ResXMLParser::
# undefined-reference block from that link.
CORE_SRCS="RefBase.cpp String8.cpp String16.cpp VectorImpl.cpp SharedBuffer.cpp \
Threads.cpp Timers.cpp SystemClock.cpp Debug.cpp CallStack.cpp \
StopWatch.cpp TextOutput.cpp BufferedTextOutput.cpp misc.cpp Static.cpp \
FileMap.cpp ZipUtils.cpp ZipFileRO.cpp Unicode.cpp \
Asset.cpp AssetDir.cpp AssetManager.cpp ResourceTypes.cpp"

for f in $CORE_SRCS; do
    "$GXX" $CXXFLAGS -c "$UTILS/$f" -o "$OUT/obj/${f%.cpp}.o"
done
"$AR" rcs "$OUT/libutils.a" "$OUT"/obj/*.o
echo "libutils.a built"
