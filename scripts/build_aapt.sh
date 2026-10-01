#!/bin/bash
# Build aapt, the Android Asset Packaging Tool, from frameworks/base/tools/aapt.
# Host tool (BUILD_HOST_EXECUTABLE in the real Android.mk) -- runs on the WSL
# build machine, not the 3DS, so this uses the system g++/gcc against glibc,
# not the ARM cross toolchain or bionic headers. Same reasoning as
# build_aidl.sh.
#
# Needed to compile core/res/ into framework-res.apk + R.java -- see
# docs/HANDOFF.md "Immediate next steps" item 3, stage 2.
#
# Real AOSP links aapt against *host* builds of libutils/libcutils/liblog
# (distinct from the bionic/ARM ones already built for the device image) plus
# libexpat/libpng/zlib and a small "libhost" helper (build/libs/host,
# fetched separately -- see scripts/fetch_build_libhost.sh). This script
# builds all of those host-side archives first, then aapt itself.
#
# libpng specifically must be the *vendored* AOSP copy
# (third_party/libpng, a 2009-era libpng ~1.2), not the system libpng-dev
# (1.6): Images.cpp calls png_ptr->io_ptr directly (opaque since 1.4),
# png_sizeof/png_set_gray_1_2_4_to_8 (renamed/removed since), and expects
# zlib's Z_BEST_COMPRESSION visible through png.h. libexpat's API has been
# stable since 1.95 so the system package is fine there.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
LIBHOST_SRC="${ANDROID3DS_ROOT}"/third_party/build/libs/host
LIBPNG_SRC="${ANDROID3DS_ROOT}"/third_party/libpng
ICU4C="${ANDROID3DS_ROOT}"/third_party/icu4c
AAPT_SRC=$FWBASE/tools/aapt
OUT="${ANDROID3DS_ROOT}"/build/aapt
LOG="${ANDROID3DS_ROOT}"/build_aapt.log
mkdir -p "$OUT/obj"/{liblog,libcutils,libutils,libhost,libpng,aapt}

CXX=g++
CC=gcc
: > "$LOG"

# Host AndroidConfig.h (linux-x86, not linux-arm): defines HAVE_PTHREADS,
# OS_PATH_SEPARATOR, HAVE_SYS_UIO_H etc for a desktop Linux host, same role
# as the linux-arm one plays for the device builds.
ANDROID_CONFIG="-include $SYSCORE/include/arch/linux-x86/AndroidConfig.h"

COMMON_INCLUDES="-I $SYSCORE/include -I $FWBASE/include -I $ICU4C/common"

# -std=gnu++98: same reason as every other frameworks/base C++ port in this
# project (build_libutils.sh, build_libandroid_runtime.sh) -- modern GCC
# makes char16_t/char32_t built-in keywords from C++11 on, colliding with
# Eclair's own typedef in String16.h/String8.h. Applies to the host build
# too since it's the same source.
CXXFLAGS="-std=gnu++98 -fno-exceptions -fno-rtti -g -O2 -Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
$ANDROID_CONFIG $COMMON_INCLUDES"
CFLAGS="-std=gnu89 -fgnu89-inline -g -O2 -Wno-attributes -Wno-implicit-function-declaration \
$ANDROID_CONFIG $COMMON_INCLUDES"

compile() {
    local compiler=$1 flags=$2 src=$3 obj=$4
    echo "  CC  $(basename "$src")" | tee -a "$LOG"
    "$compiler" $flags -c "$src" -o "$obj" >> "$LOG" 2>&1 || {
        echo "FAILED compiling $src -- last 60 lines of $LOG:"
        tail -60 "$LOG"
        exit 1
    }
}

echo "=== liblog (host, FAKE_LOG_DEVICE -- logs to stderr, matches real AOSP's host liblog build) ==="
for f in logd_write.c fake_log_device.c logprint.c event_tag_map.c; do
    compile "$CC" "$CFLAGS -DFAKE_LOG_DEVICE=1" "$SYSCORE/liblog/$f" "$OUT/obj/liblog/${f%.c}.o"
done
ar rcs "$OUT/liblog.a" "$OUT"/obj/liblog/*.o

echo "=== libcutils (host subset: atomic + threads) ==="
for f in atomic.c threads.c; do
    compile "$CC" "$CFLAGS" "$SYSCORE/libcutils/$f" "$OUT/obj/libcutils/${f%.c}.o"
done
ar rcs "$OUT/libcutils.a" "$OUT"/obj/libcutils/*.o

echo "=== libutils (host, frameworks/base/libs/utils) ==="
UTILS=$FWBASE/libs/utils
CORE_SRCS="RefBase.cpp String8.cpp String16.cpp VectorImpl.cpp SharedBuffer.cpp \
Threads.cpp Timers.cpp SystemClock.cpp Debug.cpp CallStack.cpp \
StopWatch.cpp TextOutput.cpp BufferedTextOutput.cpp misc.cpp Static.cpp \
FileMap.cpp ZipUtils.cpp ZipFileRO.cpp Unicode.cpp \
Asset.cpp AssetDir.cpp AssetManager.cpp ResourceTypes.cpp"
for f in $CORE_SRCS; do
    compile "$CXX" "$CXXFLAGS" "$UTILS/$f" "$OUT/obj/libutils/${f%.cpp}.o"
done
ar rcs "$OUT/libutils.a" "$OUT"/obj/libutils/*.o

echo "=== libhost (build/libs/host -- pseudolocalize + CopyFile) ==="
compile "$CC"  "$CFLAGS -I $LIBHOST_SRC/include" "$LIBHOST_SRC/CopyFile.c" "$OUT/obj/libhost/CopyFile.o"
compile "$CXX" "$CXXFLAGS -I $LIBHOST_SRC/include" "$LIBHOST_SRC/pseudolocalize.cpp" "$OUT/obj/libhost/pseudolocalize.o"
ar rcs "$OUT/libhost.a" "$OUT"/obj/libhost/*.o

echo "=== libpng (host, vendored third_party/libpng -- NOT system libpng-dev, see header note) ==="
# pnggccrd.c / pngvcrd.c are x86 MMX/VC++ asm-optimization sources gated by
# PNG_ASSEMBLER_CODE_SUPPORTED, which nothing here defines -- same exclusion
# build_skia_deps.sh already made for the device build.
PNG_SRCS="png.c pngerror.c pngget.c pngmem.c pngpread.c pngread.c pngrio.c \
pngrtran.c pngrutil.c pngset.c pngtrans.c pngwio.c pngwrite.c pngwtran.c \
pngwutil.c"
for f in $PNG_SRCS; do
    compile "$CC" "-std=gnu89 -fgnu89-inline -g -O2 -Wno-implicit-function-declaration -I $LIBPNG_SRC" \
        "$LIBPNG_SRC/$f" "$OUT/obj/libpng/${f%.c}.o"
done
ar rcs "$OUT/libpng.a" "$OUT"/obj/libpng/*.o

echo "=== aapt itself ==="
AAPT_SRCS="AaptAssets.cpp Command.cpp Main.cpp Package.cpp StringPool.cpp \
XMLNode.cpp ResourceTable.cpp Images.cpp Resource.cpp SourcePos.cpp \
ZipEntry.cpp ZipFile.cpp"
for f in $AAPT_SRCS; do
    compile "$CXX" "$CXXFLAGS -I $LIBHOST_SRC/include -I $LIBPNG_SRC -Wno-format-y2k" "$AAPT_SRC/$f" "$OUT/obj/aapt/${f%.cpp}.o"
done

# -Wl,-u,...gDarwinCantLoadAllObjectsE: forces Static.o (which seeds
# gEmptyStringImpl/gEmptyString16Impl) into the link. Without it nothing in
# aapt's own objects directly references a Static.o symbol -- only a global
# constructor pulled in transitively does -- so the archive linker never
# pulls the member in and every empty String8 (Bundle's constructor is the
# first) segfaults in getEmptyString()/android_atomic_inc(NULL). Same fix
# already on record for dalvikvm/app_process, see docs/HANDOFF.md
# "libutils static-init NULL crash".
"$CXX" $CXXFLAGS -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE -o "$OUT/aapt" "$OUT"/obj/aapt/*.o \
    "$OUT/libhost.a" "$OUT/libutils.a" "$OUT/libcutils.a" "$OUT/liblog.a" "$OUT/libpng.a" \
    -lexpat -lz -lpthread -lrt >> "$LOG" 2>&1 || {
        echo "FAILED linking aapt -- last 80 lines of $LOG:"
        tail -80 "$LOG"
        exit 1
    }

ls -la "$OUT/aapt"
echo "=== aapt smoke test ==="
"$OUT/aapt" version
