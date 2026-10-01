#!/bin/bash
# Build libandroid_runtime.a -- the JNI layer under the Android framework.
#
# This is what app_process (zygote) links against. AndroidRuntime::start()
# creates the VM, calls jniRegisterSystemMethods() and then walks gRegJNI[],
# 98 register_*() entry points implementing the natives behind android.os,
# android.util, android.database, android.view, android.text, android.net and
# the rest of the framework.
#
# Upstream builds all 101 sources at once. 53 of them need Skia, libui,
# libmedia or EGL/GLES -- none of which exist here yet -- so this builds the 48
# that only depend on what is already ported (libbinder, libutils, libcutils,
# libdvm, SQLite, expat, ICU, OpenSSL) and reports precisely which ones fail.
# The graphics half follows once external/skia is built.
#
# The source list is read out of upstream's own Android.mk rather than being
# retyped, so it cannot silently drift.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TC="${ANDROID3DS_ROOT}"/toolchain/armv6-eabihf--glibc--stable-2025.08-1/bin
GXX="$TC/arm-buildroot-linux-gnueabihf-g++"
GCC="$TC/arm-buildroot-linux-gnueabihf-gcc"
AR="$TC/arm-buildroot-linux-gnueabihf-ar"

TP="${ANDROID3DS_ROOT}"/third_party
BIONIC=$TP/bionic
LSTL=$BIONIC/libstdc++
SYSCORE=$TP/system_core
FWBASE=$TP/frameworks/base
DALVIK=$TP/dalvik
JNI=$FWBASE/core/jni
OUT="${ANDROID3DS_ROOT}"/build/libandroid_runtime

mkdir -p "$OUT/obj" "$OUT/log"
rm -f "$OUT"/obj/*.o "$OUT"/log/*.log

# Same C++ dialect and prologue as every other framework library here --
# see build_libutils.sh for why -std=gnu++98 and -include AndroidConfig.h.
CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks -fno-strict-aliasing \
-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \
-Wno-multichar -Wno-unused-variable -Wno-narrowing \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DLINUX \
-DN3DS_STATIC_JNI \
-DGL_GLEXT_PROTOTYPES -DEGL_EGLEXT_PROTOTYPES \
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
-I $FWBASE/include \
-I $FWBASE/include/ui \
-I $FWBASE/include/utils \
-I $FWBASE/native/include \
-I $FWBASE/opengl/include \
-I $FWBASE/opengl/include/EGL \
-I $FWBASE/opengl/include/GLES \
-I $JNI \
`# Both levels: sources say #include "JNIHelp.h" but AndroidRuntime.h says
 # #include <nativehelper/jni.h>, so the parent has to be on the path too.` \
-I $DALVIK/libnativehelper/include \
-I $DALVIK/libnativehelper/include/nativehelper \
-I $DALVIK/vm \
-I $TP/sqlite/dist \
`# sqlite3_android.h -- Android's ICU-backed collation additions to SQLite,
 # a separate directory from the amalgamation.` \
-I $TP/sqlite/android \
`# hardware/*.h and hardware_legacy/*.h: power, gps, wifi, uevent, flashlight,
 # sensors. Fetched from AOSP hardware/libhardware{,_legacy} at eclair-release,
 # same as the external/ libraries.` \
-I $TP/libhardware/include \
-I $TP/libhardware_legacy/include \
`# android_net_wifi_Wifi.cpp says #include "wifi.h", unqualified.` \
-I $TP/libhardware_legacy/include/hardware_legacy \
-I $TP/expat/lib \
-I $TP/openssl/include \
-I $TP/icu4c/common \
-I $TP/icu4c/i18n \
-I $TP/zlib \
`# Skia -- unblocks the android/graphics/ half (Bitmap, Canvas, Paint, ...).
 # Both include styles appear in upstream sources: "SkCanvas.h" (flat) and
 # <core/SkCanvas.h> (rooted at skia/include), so both must be on the path.` \
-I $TP/skia/include \
-I $TP/skia/include/core \
-I $TP/skia/include/effects \
-I $TP/skia/include/images \
-I $TP/skia/include/utils \
-I $TP/skia/include/xml \
-I $TP/skia/include/ports \
`# SkImageRef_ashmem.h is a Skia-internal header (src/ports), not exported
 # via include/ -- BitmapFactory.cpp reaches into it directly anyway.` \
-I $TP/skia/src/ports \
-I $TP/freetype/include \
`# GraphicsJNI.h is local to this directory; some sources reach it as a
 # bare include from siblings under core/jni/.` \
-I $JNI/android/graphics"

# Read LOCAL_SRC_FILES straight out of upstream's makefile.
SRCS=$(awk '/^LOCAL_SRC_FILES/,/[^\\]$/' "$JNI/Android.mk" \
       | sed 's/\\$//' | tr -s ' \t' '\n' | grep -E '\.(cpp|c)([.]arm)?$' | sort -u)

# Everything needing libmedia, the Java EGL/GLES bindings, bluetooth or a
# camera HAL. Deferred until those exist.
#
# android/graphics/ came off this list when external/skia was built.
# "Surface" came off it on 2026-08-04 when the compositor was built
# (libui + libagl + libpixelflinger + the gralloc HAL + SurfaceFlinger):
# android_view_Surface.cpp is what android.view.Surface/SurfaceSession bind
# to, and WindowManagerService cannot construct without it.
# The audio stack landed on 2026-09-12, so android_media_AudioRecord,
# AudioSystem, AudioTrack and ToneGenerator came off this list. JetPlayer
# stays: it is the libsonivox front end and there is no sonivox in this
# tree. Note the regex has to name JetPlayer rather than _media_ now.
DEFER='JetPlayer|bluetooth|sonivox|emoji'

ok=0; fail=0; deferred=0
FAILED=""
for f in $SRCS; do
    base=$(basename "$f")
    source="$JNI/${f%.arm}"
    objbase="${base%.cpp.arm}"
    objbase="${objbase%.*}"
    if echo "$f" | grep -qiE "$DEFER"; then
        deferred=$((deferred + 1))
        continue
    fi
    [ -f "$source" ] || { echo "  MISSING $source"; continue; }

    extra_flags=""
    case "$f" in *.cpp.arm) extra_flags="-x c++" ;; esac
    if "$GXX" $CXXFLAGS $extra_flags -c "$source" -o "$OUT/obj/$objbase.o" \
            > "$OUT/log/$objbase.log" 2>&1; then
        ok=$((ok + 1))
    else
        fail=$((fail + 1))
        FAILED="$FAILED $base"
    fi
done

echo "compiled  : $ok"
echo "failed    : $fail"
echo "deferred  : $deferred  (need Skia / libui / libmedia / EGL)"

if [ -n "$FAILED" ]; then
    echo
    echo "=== failures ==="
    for b in $FAILED; do
        echo "--- $b"
        logbase="${b%.cpp.arm}"; logbase="${logbase%.*}"
        grep -m3 -E "error:|fatal error:" "$OUT/log/$logbase.log" | sed 's/^/    /'
    done
fi

# The two libmedia_jni sources. Upstream ships these in a separate .so that
# registers itself from JNI_OnLoad; a static image never loads a .so, so
# they are compiled in here and called from gRegJNI instead. MediaPlayer is
# what Ringtone/NotificationManagerService use for alerts and SoundPool is
# what AudioService.playSoundEffect() uses for every UI click.
#
# MediaRecorder joined them on 2026-09-13, and not because anything here
# records to 3GP. AudioRecord.audioParamCheck() calls the static method
# MediaRecorder.getAudioSourceMax(), so MediaRecorder.<clinit> -- and
# therefore native_init() -- runs on the way into every AudioRecord in
# the system. Leaving it unregistered did not disable recording, it made
# recording throw NoClassDefFoundError naming a class the caller never
# mentioned. The JNI itself needs no encoder: it is a thin binder shim
# over libmedia's mediarecorder.cpp, which build_audio_stack.sh already
# compiles.
#
# The rest of media/jni is still out: MediaScanner wants an encoder,
# AmrInputStream wants the OpenCORE AMR encoder, and
# MediaMetadataRetriever wants a demuxer. None of those exist here.
EXTRA_SRCS="
$FWBASE/media/jni/android_media_MediaPlayer.cpp
$FWBASE/media/jni/android_media_MediaRecorder.cpp
$FWBASE/media/jni/soundpool/android_media_SoundPool.cpp
"
for source in $EXTRA_SRCS; do
    objbase=$(basename "$source" .cpp)
    if "$GXX" $CXXFLAGS -I $FWBASE/media/jni/soundpool \
            -c "$source" -o "$OUT/obj/$objbase.o" \
            > "$OUT/log/$objbase.log" 2>&1; then
        ok=$((ok + 1))
    else
        fail=$((fail + 1))
        echo "--- $objbase.cpp"
        grep -m3 -E "error:|fatal error:" "$OUT/log/$objbase.log" | sed "s/^/    /"
    fi
done

# gRegJNI is ordered and a missing entry is a silent zygote exit 0, so
# assert the audio registrations are actually in the table rather than
# just in the archive. See scripts/test_zygote_preload_qemu.sh.
#
# MediaRecorder is in this list even though no app in the image records
# through it: AudioRecord's constructor initialises it, so dropping the
# registration breaks the microphone rather than the recorder.
for sym in AudioRecord AudioSystem AudioTrack ToneGenerator MediaPlayer \
           MediaRecorder SoundPool; do
    if ! grep -q "REG_JNI(register_android_media_$sym)" "$JNI/AndroidRuntime.cpp"; then
        echo "VERIFY FAILED: register_android_media_$sym missing from gRegJNI"
        exit 1
    fi
done
echo "verify  : all seven audio JNI registrations present in gRegJNI"

if [ "$ok" -gt 0 ]; then
    "$AR" rcs "$OUT/libandroid_runtime.a" "$OUT"/obj/*.o
    ls -la "$OUT/libandroid_runtime.a"
fi
