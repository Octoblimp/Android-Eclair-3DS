#!/bin/bash
# Build the four static libs Skia's core module links against: libpng,
# libjpeg, libgif, libft2 (freetype). Source lists and -D flags are taken
# from each project's own AOSP Android.mk, same convention as
# build_expat_sqlite.sh / build_openssl.sh.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
SYSCORE=$TP/system_core
BUILD="${ANDROID3DS_ROOT}"/build

# -std=gnu89 -fgnu89-inline: mandatory for every C TU against bionic headers
# (see build_expat_sqlite.sh / HANDOFF.md for why).
BASE_CFLAGS="-nostdinc -O2 -fno-stack-protector -fno-pic -std=gnu89 -fgnu89-inline \
-Wno-implicit-function-declaration -Wno-attributes -Wno-pointer-sign \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER \
-isystem $($GCC -print-file-name=include) \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $SYSCORE/include"

# --------------------------------------------------------------- libpng ----
# pnggccrd.c / pngvcrd.c are x86-only MMX/VC++ optimization sources, dead
# code on ARM (PNG_ASSEMBLER_CODE_SUPPORTED is never defined here, same as
# upstream's own device build) -- excluded, not ported.
PNG=$TP/libpng
OUT=$BUILD/libpng
mkdir -p "$OUT/obj" "$OUT/log"; rm -f "$OUT"/obj/*.o

PNG_SRCS="png.c pngerror.c pngget.c pngmem.c pngpread.c pngread.c pngrio.c \
pngrtran.c pngrutil.c pngset.c pngtrans.c pngwio.c pngwrite.c pngwtran.c \
pngwutil.c"
PNG_CFLAGS="$BASE_CFLAGS -I $PNG -I $TP/zlib"

echo "=== libpng ==="
ok=0; fail=0
for f in $PNG_SRCS; do
    if "$GCC" $PNG_CFLAGS -c "$PNG/$f" -o "$OUT/obj/${f%.c}.o" \
            > "$OUT/log/${f%.c}.log" 2>&1; then
        ok=$((ok+1))
    else
        fail=$((fail+1)); echo "  FAIL $f"; tail -20 "$OUT/log/${f%.c}.log"
    fi
done
echo "  ok=$ok fail=$fail"
[ "$fail" -eq 0 ]
rm -f "$OUT/libpng.a"
"$AR" rcs "$OUT/libpng.a" "$OUT"/obj/*.o
ls -la "$OUT/libpng.a"

# -------------------------------------------------------------- libjpeg ----
# ANDROID_JPEG_NO_ASSEMBLER path: jidctint.c + jidctfst.c (C), skipping the
# old ARM assembly jidctfst.S to avoid re-deriving old-toolchain asm syntax
# assumptions for a hot loop we don't need optimized yet.
JPEG=$TP/jpeg
OUT=$BUILD/jpeg
mkdir -p "$OUT/obj" "$OUT/log"; rm -f "$OUT"/obj/*.o

JPEG_SRCS="jcapimin.c jcapistd.c jccoefct.c jccolor.c jcdctmgr.c jchuff.c \
jcinit.c jcmainct.c jcmarker.c jcmaster.c jcomapi.c jcparam.c jcphuff.c \
jcprepct.c jcsample.c jctrans.c jdapimin.c jdapistd.c jdcoefct.c jdcolor.c \
jddctmgr.c jdhuff.c jdinput.c jdmainct.c jdmarker.c jdmaster.c jdmerge.c \
jdphuff.c jdpostct.c jdsample.c jdtrans.c jerror.c jfdctflt.c jfdctfst.c \
jfdctint.c jidctflt.c jidctred.c jquant1.c jquant2.c jutils.c jmemmgr.c \
jmem-android.c jidctint.c jidctfst.c"
JPEG_CFLAGS="$BASE_CFLAGS -DAVOID_TABLES -fstrict-aliasing -I $JPEG"

echo "=== libjpeg ==="
ok=0; fail=0
for f in $JPEG_SRCS; do
    if "$GCC" $JPEG_CFLAGS -c "$JPEG/$f" -o "$OUT/obj/${f%.c}.o" \
            > "$OUT/log/${f%.c}.log" 2>&1; then
        ok=$((ok+1))
    else
        fail=$((fail+1)); echo "  FAIL $f"; tail -20 "$OUT/log/${f%.c}.log"
    fi
done
echo "  ok=$ok fail=$fail"
[ "$fail" -eq 0 ]
rm -f "$OUT/libjpeg.a"
"$AR" rcs "$OUT/libjpeg.a" "$OUT"/obj/*.o
ls -la "$OUT/libjpeg.a"

# --------------------------------------------------------------- libgif ----
GIF=$TP/giflib
OUT=$BUILD/libgif
mkdir -p "$OUT/obj" "$OUT/log"; rm -f "$OUT"/obj/*.o

GIF_CFLAGS="$BASE_CFLAGS -Wno-format -DHAVE_CONFIG_H -I $GIF"

echo "=== libgif ==="
ok=0; fail=0
for f in dgif_lib.c gifalloc.c gif_err.c; do
    if "$GCC" $GIF_CFLAGS -c "$GIF/$f" -o "$OUT/obj/${f%.c}.o" \
            > "$OUT/log/${f%.c}.log" 2>&1; then
        ok=$((ok+1))
    else
        fail=$((fail+1)); echo "  FAIL $f"; tail -20 "$OUT/log/${f%.c}.log"
    fi
done
echo "  ok=$ok fail=$fail"
[ "$fail" -eq 0 ]
rm -f "$OUT/libgif.a"
"$AR" rcs "$OUT/libgif.a" "$OUT"/obj/*.o
ls -la "$OUT/libgif.a"

# ------------------------------------------------------------- freetype ----
FT=$TP/freetype
OUT=$BUILD/freetype
mkdir -p "$OUT/obj" "$OUT/log"; rm -f "$OUT"/obj/*.o

FT_SRCS="src/base/ftbbox.c src/base/ftbitmap.c src/base/ftglyph.c \
src/base/ftstroke.c src/base/ftxf86.c src/base/ftbase.c src/base/ftsystem.c \
src/base/ftinit.c src/base/ftgasp.c src/raster/raster.c src/sfnt/sfnt.c \
src/smooth/smooth.c src/autofit/autofit.c src/truetype/truetype.c \
src/cff/cff.c src/psnames/psnames.c src/pshinter/pshinter.c"
FT_CFLAGS="$BASE_CFLAGS -DDARWIN_NO_CARBON -DFT2_BUILD_LIBRARY \
-I $FT/builds -I $FT/include"

echo "=== freetype (libft2) ==="
ok=0; fail=0
for f in $FT_SRCS; do
    base=$(basename "$f")
    if "$GCC" $FT_CFLAGS -c "$FT/$f" -o "$OUT/obj/${base%.c}.o" \
            > "$OUT/log/${base%.c}.log" 2>&1; then
        ok=$((ok+1))
    else
        fail=$((fail+1)); echo "  FAIL $f"; tail -20 "$OUT/log/${base%.c}.log"
    fi
done
echo "  ok=$ok fail=$fail"
[ "$fail" -eq 0 ]
rm -f "$OUT/libft2.a"
"$AR" rcs "$OUT/libft2.a" "$OUT"/obj/*.o
ls -la "$OUT/libft2.a"

echo
echo "all four Skia dependency libs built"
