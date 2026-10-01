#!/bin/bash
# Build libcameraservice.a and /system/bin/mediaserver.
#
# mediaserver is what publishes "media.camera" to ServiceManager. Without it
# android.hardware.Camera.open() throws at Camera::connect() and the stock
# Camera app shows nothing, no matter how good the kernel driver is.
#
# All four services now: AudioFlinger, MediaPlayerService, CameraService and
# AudioPolicyService, in that order (AudioPolicyService reaches AudioFlinger
# over binder from its own constructor). The four archives come from
# scripts/build_audio_stack.sh, which must have run first.
#
# N3DS_CAMERA_HAL: THE CAMERA HAL IS REAL NOW. CameraHardwareN3ds reads YUV
# 4:2:2 frames from /dev/ctr_cam (kernel #314's capture driver, built from
# GBATEK's CAM register map), shows them as an RGB565 preview and encodes
# stills with libjpeg. It replaced CameraHardwareStub + FakeCamera, AOSP's
# software camera, which is what this image shipped while the CAM block was
# believed undocumented. Those two files stay in the tree but are no longer
# compiled: there must be exactly one openCameraHardware().
#
# N3DS_NO_LIBMEDIA IS GONE. CameraService's only libmedia use is the shutter
# click and the record beep, and libmedia now exists, so they are built back
# in. The two assets are .wav rather than upstream's .ogg because WavPlayer is
# the only decoder in this image -- see WavPlayer.h and build_audio_assets.sh.
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
LIBHWL="${ANDROID3DS_ROOT}"/third_party/libhardware_legacy
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
JPEG="${ANDROID3DS_ROOT}"/third_party/jpeg
SRC=$FWBASE/camera/libcameraservice
CMD=$FWBASE/media/mediaserver

BUILD="${ANDROID3DS_ROOT}"/build
BIONIC_OUT=$BUILD/bionic
OUT=$BUILD/mediaserver
LIBGCC="$("$GCC" -print-libgcc-file-name)"
# libutils CallStack.cpp calls _Unwind_Backtrace/_Unwind_VRS_Get, which on
# ARM live in libgcc_eh.a rather than the libgcc.a -print-libgcc-file-name
# reports. libui Surface.o is what references CallStack, and it entered this
# link along with MediaPlayerService setVideoSurface.
LIBGCC_EH="$("$GCC" -print-file-name=libgcc_eh.a)"

for a in libmedia libaudioflinger libmediaplayerservice libsoundpool; do
    if [ ! -f "$BUILD/audio/$a.a" ]; then
        echo "missing $BUILD/audio/$a.a -- run scripts/build_audio_stack.sh first"
        exit 1
    fi
done
if [ ! -f "$BUILD/jpeg/libjpeg.a" ]; then
    echo "missing $BUILD/jpeg/libjpeg.a -- run scripts/build_skia_deps.sh first"
    exit 1
fi

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/libcameraservice.a "$OUT"/mediaserver "$OUT"/build.log

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-write-strings -Wno-narrowing -Wno-invalid-offsetof \
-Wno-unused-but-set-variable -Wno-deprecated -Wno-multichar \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DBINDER_IPC_32BIT \
-DGENERIC_AUDIO -DN3DS_WAV_ONLY \
-DLOG_TAG=\"CameraService\" \
-include $SYSCORE/include/arch/linux-arm/AndroidConfig.h \
-isystem $($GXX -print-file-name=include) \
-I $LSTL/include \
-I $BIONIC/libc/include \
-I $BIONIC/libm/include \
-I $BIONIC/libc/kernel/common \
-I $BIONIC/libc/kernel/arch-arm \
-I $BIONIC/libc/arch-arm/include \
-I $FWBASE/include \
-I $FWBASE/include/media/n3ds_openmax \
-I $FWBASE/libs/audioflinger \
-I $FWBASE/media/libmediaplayerservice \
-I $LIBHW/include \
-I $LIBHWL/include \
-I $SYSCORE/include \
-I $SRC \
-I $JPEG \
-I $KERNEL/include/uapi"

# CameraHardwareN3ds.cpp is the HAL (N3DS_CAMERA_HAL above); it links against
# build_skia_deps.sh's libjpeg.a, the same archive app_process uses.
SRCS="
CameraService.cpp
CameraHardwareN3ds.cpp
"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    o="$OUT/obj/$(echo "$f" | sed 's/\.cpp$/.o/')"
    if "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

if "$GXX" $CXXFLAGS -c "$CMD/main_mediaserver_n3ds.cpp" \
        -o "$OUT/obj/main_mediaserver_n3ds.o" 2>>"$OUT/build.log"; then
    OK=$((OK+1))
else
    FAIL=$((FAIL+1)); FAILED="$FAILED main_mediaserver_n3ds.cpp"
fi

# MediaPlayerService resolves content:// URLs through
# openContentProviderFile(). It lives under core/jni/ but is not JNI -- it is
# a plain binder call to the "activity" service. libandroid_runtime.a also
# compiles it, so keep this copy loose rather than in any archive.
if "$GXX" $CXXFLAGS -c "$FWBASE/core/jni/ActivityManager.cpp" \
        -o "$OUT/obj/ActivityManager.o" 2>>"$OUT/build.log"; then
    OK=$((OK+1))
else
    FAIL=$((FAIL+1)); FAILED="$FAILED ActivityManager.cpp"
fi

echo "mediaserver sources: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "--- see $OUT/build.log ---"
    sed -n '1,60p' "$OUT/build.log"
    exit 1
fi

"$AR" rcs "$OUT/libcameraservice.a" \
    $(ls "$OUT"/obj/*.o | grep -v -e main_mediaserver_n3ds.o -e ActivityManager.o)

echo "  LD  mediaserver"
# libutils' Static.o as the first loose object after crtbegin.o -- see
# build_surfaceflinger.sh for why this cannot be done with -Wl,-u instead.
"$GXX" -nostdlib -static \
    "$BIONIC_OUT/crtbegin.o" \
    "$BUILD/libutils/obj/Static.o" \
    "$OUT/obj/main_mediaserver_n3ds.o" \
    "$OUT/obj/ActivityManager.o" \
    -Wl,--start-group \
        "$OUT/libcameraservice.a" \
        "$BUILD/jpeg/libjpeg.a" \
        "$BUILD/audio/libmediaplayerservice.a" \
        "$BUILD/audio/libaudioflinger.a" \
        "$BUILD/audio/libsoundpool.a" \
        "$BUILD/audio/libmedia.a" \
        "$BUILD/libui/libui.a" \
        "$BUILD/libgralloc/libgralloc_n3ds.a" \
        "$BUILD/libhardware/libhardware.a" \
        `# libui's PixelFormat.cpp calls gglGetPixelFormatTable` \
        "$BUILD/libpixelflinger/libpixelflinger.a" \
        "$BUILD/libbinder/libbinder.a" \
        "$BUILD/libutils/libutils.a" \
        "$BUILD/libcutils/libcutils.a" \
        "$BUILD/liblog/liblog.a" \
        "$BUILD/libstdcxx/libstdc++.a" \
        "$BUILD/bionic_compat/libbionic_compat.a" \
        "$BUILD/libm/libm.a" \
        "$BIONIC_OUT/libc.a" \
        "$LIBGCC" \
        "$LIBGCC_EH" \
    -Wl,--end-group \
    "$BIONIC_OUT/crtend.o" \
    -o "$OUT/mediaserver" \
    -Wl,-e,_start -Wl,--no-warn-mismatch \
    -Wl,--defsym=__aeabi_unwind_cpp_pr0=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr1=0 \
    -Wl,--defsym=__aeabi_unwind_cpp_pr2=0 \
    2>&1 | grep -v 'missing .note.GNU-stack\|This behaviour is deprecated' || true

if [ ! -f "$OUT/mediaserver" ]; then
    echo "LINK FAILED"
    exit 1
fi

file "$OUT/mediaserver"

# Self-verification. A mediaserver that links but does not publish
# "media.camera" is indistinguishable from no mediaserver at all from the
# app's side, so assert the string is actually in the binary.
for s in media.camera media.audio_flinger media.player media.audio_policy; do
    if ! strings "$OUT/mediaserver" | grep -qx "$s"; then
        echo "VERIFY FAILED: '$s' not found in the binary"
        exit 1
    fi
done
echo "verify: all four service names present"

# The audio stack is only real if the HAL went in with it. AudioHardwareGeneric
# is what opens /dev/eac; if -DGENERIC_AUDIO ever gets dropped,
# AudioHardwareInterface::create() silently falls back to AudioHardwareStub
# and every sound in the system plays into a bit bucket with no error.
if ! strings "$OUT/mediaserver" | grep -qx "/dev/eac"; then
    echo "VERIFY FAILED: /dev/eac not in the binary -- AudioHardwareStub got linked"
    exit 1
fi
echo "verify: /dev/eac present (AudioHardwareGeneric, not the stub)"

# N3DS_CAMERA_HAL: the real HAL went in, and the stub did not. Four things
# have to be true for the Camera app to show the sensor and save a picture:
#   - the HAL opens /dev/ctr_cam and its START ioctl
#   - the preview it hands CameraService is RGB565, and CameraService
#     registers it as such (N3DS_CAMERA_RGB565) -- YUV comes out grey here
#   - libjpeg is linked in for stills
#   - FakeCamera's status frame is gone, so the stub cannot be what runs
MS_STRINGS="$(mktemp)"
strings "$OUT/mediaserver" > "$MS_STRINGS"
for s in "/dev/ctr_cam" "N3DS_CAMERA_HAL: camera HAL up, source %s" \
         "n3ds-camera-id" "rgb565" "Wrong JPEG library version: library is %d, caller expects %d"; do
    if ! grep -qF "$s" "$MS_STRINGS"; then
        rm -f "$MS_STRINGS"
        echo "VERIFY FAILED: camera HAL string missing: $s"
        exit 1
    fi
done
for s in "NO LIVE CAMERA FEED" "0X10120000 IS UNKNOWN."; do
    if grep -qxF "$s" "$MS_STRINGS"; then
        rm -f "$MS_STRINGS"
        echo "VERIFY FAILED: FakeCamera is still linked ($s) -- the stub HAL is in"
        exit 1
    fi
done
rm -f "$MS_STRINGS"
if ! grep -qF 'n3dsHeapFormat(params)' "$SRC/CameraService.cpp"; then
    echo "VERIFY FAILED: CameraService.cpp registers camera heaps as YCbCr again (N3DS_CAMERA_RGB565)"
    exit 1
fi
echo "verify: CameraHardwareN3ds + libjpeg linked, RGB565 heaps, stub gone"

DEST="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay/system/bin
"$STRIP" -o "$DEST/mediaserver" "$OUT/mediaserver"
chmod 755 "$DEST/mediaserver"
echo "=== build_mediaserver: ALL OK ==="
ls -la "$DEST/mediaserver"
