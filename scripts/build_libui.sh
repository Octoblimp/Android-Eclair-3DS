#!/bin/bash
# Build libui.a -- the client/server surface API layer.
#
# This is the layer SurfaceFlinger and every app talk to each other through:
# ISurfaceComposer/ISurface/ISurfaceFlingerClient (the binder interfaces),
# Surface/SurfaceComposerClient (the client side), SharedBufferStack (the
# lock-free producer/consumer ring in shared memory), GraphicBuffer*
# (gralloc's C++ wrappers), Region/Rect/Transform, and
# FramebufferNativeWindow (the android_native_window_t that libagl's EGL
# renders into and posts through gralloc).
#
# Source list from frameworks/base/libs/ui/Android.mk, minus:
#
#   (nothing at present)
#
# Camera.cpp/CameraParameters.cpp/ICamera.cpp/ICameraClient.cpp/
# ICameraService.cpp used to be cut here, on the grounds that no camera was
# wired into userspace. One now is: the stock Camera app, its JNI
# (android_hardware_Camera.cpp) and CameraService all bind through exactly
# these five files, so they are back in. Eclair has no separate
# libcamera_client -- the camera client lives inside libui, which is why these
# sit next to Surface.cpp.
#
#   (Overlay.cpp/IOverlay.cpp were excluded on the same reasoning -- the
#   overlay HAL is a hardware video plane and this device has none -- but
#   they have to be built anyway: ISurface's binder interface has
#   createOverlay() in its vtable and LayerBuffer derives an OverlayChannel
#   from BnOverlay, so both are structural link-time dependencies regardless
#   of whether any overlay hardware exists. At runtime hw_get_module()
#   returns -ENOENT for the overlay module and the code path is simply never
#   taken.)
#
#   EventHub.cpp and KeyLayoutMap.cpp are already built into
#   libservices_jni.a (see build_services_jni.sh). KeyCharacterMap.cpp belongs
#   here: framework JNI calls it in every app process, and omitting it made the
#   first 3DS face-button press fail with UnsatisfiedLinkError: ctor_native.
#
#   EventRecurrence.cpp -- calendar recurrence-rule parsing, in libui only
#   for historical reasons; its JNI registration was already cut from
#   gRegJNI[].
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

BIONIC="${ANDROID3DS_ROOT}"/third_party/bionic
LSTL=$BIONIC/libstdc++
SYSCORE="${ANDROID3DS_ROOT}"/third_party/system_core
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
LIBHW="${ANDROID3DS_ROOT}"/third_party/libhardware
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
SRC=$FWBASE/libs/ui

OUT="${ANDROID3DS_ROOT}"/build/libui
mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/libui.a "$OUT"/build.log

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-write-strings -Wno-narrowing -Wno-invalid-offsetof \
-Wno-unused-but-set-variable -Wno-deprecated \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DBINDER_IPC_32BIT \
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
-I $SYSCORE/include \
-I $SRC \
-I $KERNEL/include/uapi"

SRCS="
Camera.cpp
CameraParameters.cpp
ICamera.cpp
ICameraClient.cpp
ICameraService.cpp
EGLUtils.cpp
FramebufferNativeWindow.cpp
GraphicBuffer.cpp
GraphicBufferAllocator.cpp
GraphicBufferMapper.cpp
KeyCharacterMap.cpp
ISurfaceComposer.cpp
ISurface.cpp
ISurfaceFlingerClient.cpp
IOverlay.cpp
Overlay.cpp
LayerState.cpp
PixelFormat.cpp
Rect.cpp
Region.cpp
SharedBufferStack.cpp
Surface.cpp
SurfaceComposerClient.cpp
"

OK=0; FAIL=0; FAILED=""
for f in $SRCS; do
    if "$GXX" $CXXFLAGS -c "$SRC/$f" -o "$OUT/obj/${f%.cpp}.o" 2>>"$OUT/build.log"; then
        OK=$((OK+1))
    else
        FAIL=$((FAIL+1)); FAILED="$FAILED $f"
    fi
done

echo "libui: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "--- see $OUT/build.log ---"
    exit 1
fi

"$AR" rcs "$OUT/libui.a" "$OUT"/obj/*.o
ls -la "$OUT/libui.a"
