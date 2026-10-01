#!/bin/bash
# Build libsurfaceflinger.a and /system/bin/surfaceflinger.
#
# SurfaceFlinger is the compositor: it owns the framebuffer, owns every
# window's Surface, and is what WindowManagerService talks to. Without it
# WindowManagerService's constructor throws and Android has no UI at all --
# which is exactly where this port has been stuck.
#
# THE EGL DECISION -- read this before adding libEGL/libGLESv1_CM.
#
# Upstream links SurfaceFlinger against libEGL + libGLESv1_CM, which are pure
# dispatch layers: they dlopen() an implementation (/system/lib/egl/
# libGLES_android.so, i.e. libagl) and forward every call through a hook
# table. That entire mechanism is unusable here -- every binary in this image
# is statically linked and bionic's dlopen() unconditionally returns NULL for
# a static executable (docs/HANDOFF.md, "dlopen() from a static binary can't
# work").
#
# It is also unnecessary. libagl defines the real egl*/gl* C entry points
# itself (verified: eglInitialize, eglCreateWindowSurface, eglSwapBuffers,
# glClear, ... are all "T" symbols in libagl.a). With exactly one GL
# implementation and no runtime driver choice to make, linking libagl.a
# directly resolves every call at link time and the dispatch layer has
# nothing left to do. So libEGL and libGLESv1_CM are deliberately not built.
#
# Same reasoning for gralloc: libgralloc_n3ds.a is linked in and provides its
# own hw_get_module() (see hw_get_module_static.cpp), listed ahead of
# libhardware.a so the dlopen version never enters the binary.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"
STRIP="$TC/arm-buildroot-linux-gnueabihf-strip"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL=$BIONIC/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
LIBHW="${ANDROID3DS_ROOT}"/third_party/libhardware
SKIA="${ANDROID3DS_ROOT}"/third_party/skia
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
SRC=$FWBASE/libs/surfaceflinger
CMD=$FWBASE/cmds/surfaceflinger

BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/surfaceflinger
LIBGCC="$("$GCC" -print-libgcc-file-name)"

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/libsurfaceflinger.a "$OUT"/surfaceflinger "$OUT"/build.log

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-write-strings -Wno-narrowing -Wno-invalid-offsetof \
-Wno-unused-but-set-variable -Wno-deprecated \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DBINDER_IPC_32BIT \
-DLOG_TAG=\"SurfaceFlinger\" \
-DGL_GLEXT_PROTOTYPES -DEGL_EGLEXT_PROTOTYPES \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $FWBASE/opengl/include \
-I $LIBHW/include \
-I $LIBHW/modules/gralloc \
`# Transform.h says "#include <core/SkMatrix.h>" -- the Android.mk's
 # "include-path-for corecg graphics" resolves to skia/include itself, not
 # to its subdirectories, so the subdirectory name is part of the include
 # path in the source. Both roots are needed: SurfaceFlinger uses the
 # subdir-qualified form, Skia's own headers use the bare one.` \
-I $SKIA/include \
-I $SKIA/include/core \
-I $SKIA/include/config \
-I $SKIA/include/effects \
-I $SKIA/include/images \
-I $SYSCORE/include \
-I $SRC \
-I $KERNEL/include/uapi"

SRCS="
clz.cpp
DisplayHardware/DisplayHardware.cpp
DisplayHardware/DisplayHardwareBase.cpp
BlurFilter.cpp
Layer.cpp
LayerBase.cpp
LayerBuffer.cpp
LayerBlur.cpp
LayerDim.cpp
MessageQueue.cpp
SurfaceFlinger.cpp
Tokenizer.cpp
Transform.cpp
"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    o="$OUT/obj/$(echo "$f" | tr / _ | sed 's/\.cpp$/.o/')"
    if "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

if "$GXX" $CXXFLAGS -c "$CMD/main_surfaceflinger.cpp" \
        -o "$OUT/obj/main_surfaceflinger.o" 2>>"$OUT/build.log"; then
    OK=$((OK+1))
else
    FAIL=$((FAIL+1)); FAILED="$FAILED main_surfaceflinger.cpp"
fi

echo "surfaceflinger sources: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "--- see $OUT/build.log ---"
    exit 1
fi

"$AR" rcs "$OUT/libsurfaceflinger.a" \
    $(ls "$OUT"/obj/*.o | grep -v main_surfaceflinger.o)

echo "  LD  surfaceflinger"
"$GXX" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" \
    `# libutils' Static.o must run before every other global constructor or
     # every empty String8/String16 segfaults in getEmptyString(). It must be
     # linked here, as a loose object immediately after crtbegin.o, NOT
     # forced in via -Wl,-u,_ZN7android25gDarwinCantLoadAllObjectsE + an
     # init_priority attribute in the source -- this bionic's call_array()
     # (libc_init_static.c) walks forward from crtbegin.o's own plain
     # .init_array marker, so init_priority actually places a constructor
     # *before* that marker, where call_array() skips it and it never runs
     # at all. See docs/HANDOFF.md and Static.cpp's comment above
     # gFirstStatics. Being the first real object after crtbegin.o here
     # guarantees it lands immediately after that marker instead.` \
    "$BUILD/libutils/obj/Static.o" \
    "$OUT/obj/main_surfaceflinger.o" \
    -Wl,--start-group \
        "$OUT/libsurfaceflinger.a" \
        "$BUILD/libui/libui.a" \
        `# ahead of libhardware.a: provides the static hw_get_module()` \
        "$BUILD/libgralloc/libgralloc_n3ds.a" \
        "$BUILD/libhardware/libhardware.a" \
        "$BUILD/libagl/libagl.a" \
        "$BUILD/libpixelflinger/libpixelflinger.a" \
        "$BUILD/skia/libskia.a" \
        "$BUILD/libpng/libpng.a" \
        "$BUILD/jpeg/libjpeg.a" \
        "$BUILD/libgif/libgif.a" \
        "$BUILD/freetype/libft2.a" \
        "$BUILD/libbinder/libbinder.a" \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/zlib/libz.a" \
        `# sincos/sincosf: GCC synthesises calls to these from adjacent
         # sin(x)/cos(x) (Skia's SkMath.cpp/SkCordic.cpp) based on the
         # toolchain's glibc, but we link bionic, which has neither.
         # -fno-builtin-sincos does not help -- see docs/HANDOFF.md gotcha.` \
        "$BUILD/bionic_compat/libbionic_compat.a" \
        "$BUILD/libm/libm.a" \
        "$BIONIC_OUT/libc.a" \
        "$LIBGCC" \
    -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/surfaceflinger" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>&1 | grep -v 'missing .note.GNU-stack\|This behaviour is deprecated' || true

if [ ! -f "$OUT/surfaceflinger" ]; then
    echo "LINK FAILED"
    exit 1
fi

ls -la "$OUT/surfaceflinger"
file "$OUT/surfaceflinger"

DEST="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin
"$STRIP" -o "$DEST/surfaceflinger" "$OUT/surfaceflinger"
chmod 755 "$DEST/surfaceflinger"
echo "deployed: $DEST/surfaceflinger"
ls -la "$DEST/surfaceflinger"
