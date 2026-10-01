#!/bin/bash
# Build libskia.a -- Skia core (2D software rasterizer + image codecs).
# This is the "single gate" blocking libandroid_runtime's android/graphics/
# half and therefore app_process: AndroidRuntime.cpp includes SkGraphics.h /
# SkImageDecoder.h / SkImageRef_GlobalPool.h.
#
# Source list is the *first* module in third_party/skia/Android.mk
# (libskia itself) -- libskiagl (GL glue, irrelevant, no GPU driver) and the
# bench/gm tool dirs are not built. emoji/EmojiFont.cpp is dropped too: it
# includes EmojiFactory.h from frameworks/opt/emoji, which was never
# fetched. emoji/EmojiFontNone.cpp is built in its place -- WebCore's font
# code calls EmojiFont::IsAvailable() unguarded and will not link without
# the four entry points, and "no emoji factory installed" is a state
# EmojiFont.cpp already defines the behaviour for.
#
# Depends on scripts/build_skia_deps.sh having already built libpng, libjpeg,
# libgif and libft2 (freetype).
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
LSTL=$BIONIC/libstdc++
SYSCORE=$TP/system_core
SKIA=$TP/skia
BUILD="${ANDROID3DS_ROOT}"/build
OUT=$BUILD/skia

mkdir -p "$OUT/obj" "$OUT/log"
rm -f "$OUT"/obj/*.o

# Same C++ dialect/prologue as every other framework lib here (see
# build_libutils.sh / build_libandroid_runtime.sh for why). No
# -DSK_SOFTWARE_FLOAT / -D__ARM_HAVE_NEON: the New3DS ARM11 MPCore has
# hardware VFP (the whole toolchain already defaults hard-float, no NEON).
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks -fno-strict-aliasing \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
-Wno-multichar -Wno-unused-variable -Wno-narrowing -Wno-reorder \
-Wno-overloaded-virtual -Wno-sign-compare \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DLINUX \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $BIONIC/libc/private \
-I $SYSCORE/include \
-I $TP/frameworks/base/include \
-I $SKIA/src/core \
-I $SKIA/include/core \
-I $SKIA/include/effects \
-I $SKIA/include/images \
-I $SKIA/include/utils \
-I $SKIA/include/xml \
-I $SKIA/include/ports \
-I $TP/freetype/include \
-I $TP/zlib \
-I $TP/libpng \
-I $TP/giflib \
-I $TP/jpeg"

SRCS="
src/core/Sk64.cpp src/core/SkBuffer.cpp src/core/SkChunkAlloc.cpp
src/core/SkCordic.cpp src/core/SkDebug.cpp src/core/SkFloatBits.cpp
src/core/SkMath.cpp src/core/SkMatrix.cpp src/core/SkMemory_stdlib.cpp
src/core/SkPoint.cpp src/core/SkRect.cpp src/core/SkRegion.cpp
src/core/SkString.cpp src/core/SkUtils.cpp src/ports/SkDebug_android.cpp emoji/EmojiFontNone.cpp
src/effects/Sk1DPathEffect.cpp src/effects/Sk2DPathEffect.cpp
src/effects/SkAvoidXfermode.cpp src/effects/SkBlurDrawLooper.cpp
src/effects/SkBlurMask.cpp src/effects/SkBlurMaskFilter.cpp
src/effects/SkColorFilters.cpp src/effects/SkColorMatrixFilter.cpp
src/effects/SkCornerPathEffect.cpp src/effects/SkDashPathEffect.cpp
src/effects/SkDiscretePathEffect.cpp src/effects/SkEmbossMask.cpp
src/effects/SkEmbossMaskFilter.cpp src/effects/SkGradientShader.cpp
src/effects/SkLayerDrawLooper.cpp src/effects/SkLayerRasterizer.cpp
src/effects/SkPaintFlagsDrawFilter.cpp src/effects/SkPixelXorXfermode.cpp
src/effects/SkPorterDuff.cpp src/effects/SkTableMaskFilter.cpp
src/effects/SkTransparentShader.cpp src/images/bmpdecoderhelper.cpp
src/images/SkFDStream.cpp src/images/SkFlipPixelRef.cpp
src/images/SkImageDecoder.cpp src/images/SkImageDecoder_libbmp.cpp
src/images/SkImageDecoder_libgif.cpp src/images/SkImageDecoder_libjpeg.cpp
src/images/SkImageDecoder_libpng.cpp src/images/SkImageDecoder_libico.cpp
src/images/SkImageDecoder_wbmp.cpp src/images/SkImageEncoder.cpp
src/images/SkImageRef.cpp src/images/SkImageRef_GlobalPool.cpp
src/images/SkImageRefPool.cpp src/images/SkMovie.cpp
src/images/SkMovie_gif.cpp src/images/SkPageFlipper.cpp
src/images/SkScaledBitmapSampler.cpp src/images/SkCreateRLEPixelRef.cpp
src/images/SkImageDecoder_Factory.cpp src/images/SkImageEncoder_Factory.cpp
src/ports/SkFontHost_android.cpp src/ports/SkFontHost_gamma.cpp
src/ports/SkFontHost_FreeType.cpp src/ports/SkFontHost_tables.cpp
src/ports/SkGlobals_global.cpp src/ports/SkImageRef_ashmem.cpp
src/ports/SkOSFile_stdio.cpp src/ports/SkTime_Unix.cpp
src/core/SkAlphaRuns.cpp src/core/SkBitmap.cpp src/core/SkBitmap_scroll.cpp
src/core/SkBitmapProcShader.cpp src/core/SkBitmapProcState.cpp
src/core/SkBitmapProcState_matrixProcs.cpp src/core/SkBitmapSampler.cpp
src/core/SkBlitRow_D16.cpp src/core/SkBlitRow_D32.cpp
src/core/SkBlitRow_D4444.cpp src/core/SkBlitter.cpp
src/core/SkBlitter_4444.cpp src/core/SkBlitter_A1.cpp
src/core/SkBlitter_A8.cpp src/core/SkBlitter_ARGB32.cpp
src/core/SkBlitter_RGB16.cpp src/core/SkBlitter_Sprite.cpp
src/core/SkCanvas.cpp src/core/SkColor.cpp src/core/SkColorFilter.cpp
src/core/SkColorTable.cpp src/core/SkComposeShader.cpp src/core/SkDeque.cpp
src/core/SkDevice.cpp src/core/SkDither.cpp src/core/SkDraw.cpp
src/core/SkEdge.cpp src/core/SkFilterProc.cpp src/core/SkFlattenable.cpp
src/core/SkGeometry.cpp src/core/SkGlobals.cpp src/core/SkGlyphCache.cpp
src/core/SkGraphics.cpp src/core/SkMMapStream.cpp src/core/SkMask.cpp
src/core/SkMaskFilter.cpp src/core/SkPackBits.cpp src/core/SkPaint.cpp
src/core/SkPath.cpp src/core/SkPathEffect.cpp src/core/SkPathHeap.cpp
src/core/SkPathMeasure.cpp src/core/SkPicture.cpp src/core/SkPictureFlat.cpp
src/core/SkPicturePlayback.cpp src/core/SkPictureRecord.cpp
src/core/SkPixelRef.cpp src/core/SkProcSpriteBlitter.cpp
src/core/SkPtrRecorder.cpp src/core/SkQuadClipper.cpp
src/core/SkRasterizer.cpp src/core/SkRefCnt.cpp src/core/SkRegion_path.cpp
src/core/SkScalerContext.cpp src/core/SkScan.cpp src/core/SkScan_AntiPath.cpp
src/core/SkScan_Antihair.cpp src/core/SkScan_Hairline.cpp
src/core/SkScan_Path.cpp src/core/SkShader.cpp src/core/SkShape.cpp
src/core/SkSpriteBlitter_ARGB32.cpp src/core/SkSpriteBlitter_RGB16.cpp
src/core/SkStream.cpp src/core/SkStroke.cpp src/core/SkStrokerPriv.cpp
src/core/SkTSearch.cpp src/core/SkTypeface.cpp src/core/SkUnPreMultiply.cpp
src/core/SkXfermode.cpp src/core/SkWriter32.cpp src/utils/SkBoundaryPatch.cpp
src/utils/SkCamera.cpp src/utils/SkDumpCanvas.cpp src/utils/SkInterpolator.cpp
src/utils/SkMeshUtils.cpp src/utils/SkNinePatch.cpp src/utils/SkProxyCanvas.cpp
src/opts/SkBlitRow_opts_arm.cpp src/opts/SkBitmapProcState_opts_arm.cpp
"

ok=0; fail=0
FAILED=""
for f in $SRCS; do
    base=$(basename "$f")
    if [ ! -f "$SKIA/$f" ]; then
        echo "  MISSING $f"
        fail=$((fail+1)); FAILED="$FAILED $base"
        continue
    fi
    if "$GXX" $CXXFLAGS -c "$SKIA/$f" -o "$OUT/obj/${base%.cpp}.o" \
            > "$OUT/log/${base%.cpp}.log" 2>&1; then
        ok=$((ok+1))
    else
        fail=$((fail+1))
        FAILED="$FAILED $base"
    fi
done

echo "compiled : $ok"
echo "failed   : $fail"

if [ -n "$FAILED" ]; then
    echo
    echo "=== failures ==="
    for b in $FAILED; do
        echo "--- $b"
        grep -m5 -E "error:|fatal error:" "$OUT/log/${b%.cpp}.log" 2>/dev/null | sed 's/^/    /'
    done
fi

if [ "$ok" -gt 0 ]; then
    rm -f "$OUT/libskia.a"
    "$AR" rcs "$OUT/libskia.a" "$OUT"/obj/*.o
    ls -la "$OUT/libskia.a"
fi

[ "$fail" -eq 0 ]
