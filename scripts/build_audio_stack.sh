#!/bin/bash
# Build the Android audio stack as static archives:
#
#   libmedia.a               AudioTrack/AudioRecord/AudioSystem/ToneGenerator +
#                            every binder interface the audio services speak
#   libaudioflinger.a        AudioFlinger, the software mixer/resampler, the
#                            audio HAL and AudioPolicyService
#   libmediaplayerservice.a  MediaPlayerService + WavPlayer + WavRecorder
#   libsoundpool.a           SoundPool, which is how UI feedback sounds play
#
# WHY THIS EXISTS. Everything the framework calls "a sound" is AudioTrack on
# one end and an audio HAL on the other: notification and SMS alerts
# (NotificationManagerService -> Ringtone -> MediaPlayer), UI feedback
# (AudioService.playSoundEffect -> SoundPool), DTMF (ToneGenerator), the
# dialer's key tones, AudioRecord for the microphone. All of them die at
# AudioSystem::get_audio_flinger() if "media.audio_flinger" is not published,
# so none of them can be done piecemeal -- it is this or nothing.
#
# THE HAL IS AudioHardwareGeneric, UNMODIFIED. That is AOSP's /dev/eac driver
# and ctr_csnd.c is an exact match for what it expects: output 44100 Hz stereo
# S16 in 4096-byte buffers, input 8000 Hz mono S16 in 320-byte buffers. -D
# GENERIC_AUDIO is what selects it in AudioHardwareInterface::create().
#
# NO CODECS. -DN3DS_WAV_ONLY. See WavPlayer.h: there is no OpenCORE, no
# tremolo and no sonivox in this tree, so MediaPlayer decodes RIFF/WAVE PCM and
# nothing else, and the sound assets are transcoded to that at build time by
# scripts/build_audio_assets.sh.
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
LIBHWL="${ANDROID3DS_ROOT}"/third_party/libhardware_legacy
KERNEL="${ANDROID3DS_ROOT}"/third_party/linux
DALVIK="${ANDROID3DS_ROOT}"/third_party/dalvik
SKIA="${ANDROID3DS_ROOT}"/third_party/skia

BUILD="${ANDROID3DS_ROOT}"/build
OUT=$BUILD/audio

mkdir -p "$OUT/obj"
rm -f "$OUT"/obj/*.o "$OUT"/*.a "$OUT"/build.log

CXXFLAGS="-nostdinc++ -nostdinc -std=gnu++98 -fno-exceptions -fno-rtti \
-fno-stack-protector -fno-pic -O2 -fno-delete-null-pointer-checks \
-Wno-attributes -Wno-write-strings -Wno-narrowing -Wno-invalid-offsetof \
-Wno-unused-but-set-variable -Wno-deprecated -Wno-multichar \
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DBINDER_IPC_32BIT \
-DGENERIC_AUDIO -DN3DS_WAV_ONLY \
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
-I $DALVIK/libnativehelper/include \
-I $DALVIK/libnativehelper/include/nativehelper \
-I $SKIA/include \
-I $SKIA/include/core \
-I $SKIA/include/images \
-I $FWBASE/media/libmediaplayerservice \
-I $FWBASE/media/jni/soundpool \
-I $FWBASE/libs/audioflinger \
-I $LIBHW/include \
-I $LIBHWL/include \
-I $SYSCORE/include \
-I $KERNEL/include/uapi"

OK=0; FAIL=0; FAILED=""

# $1 = tag used for the object name prefix, $2 = source dir, $3.. = files
build_group() {
    local tag="$1"; shift
    local dir="$1"; shift
    for f in "$@"; do
        local o="$OUT/obj/${tag}_$(echo "$f" | sed 's/\.cpp$/.o/')"
        if "$GXX" $CXXFLAGS -c "$dir/$f" -o "$o" \
                2>>"$OUT/build.log"; then
            OK=$((OK+1))
        else
            FAIL=$((FAIL+1)); FAILED="$FAILED $tag/$f"
        fi
    done
}

# ---------------------------------------------------------------- libmedia ---
# JetPlayer.cpp is omitted: it is a libsonivox (JET/EAS) front end and sonivox
# is not in this tree. Its JNI is correspondingly left out of gRegJNI.
build_group media "$FWBASE/media/libmedia" \
    AudioTrack.cpp \
    AudioRecord.cpp \
    AudioSystem.cpp \
    IAudioFlinger.cpp \
    IAudioFlingerClient.cpp \
    IAudioTrack.cpp \
    IAudioRecord.cpp \
    IAudioPolicyService.cpp \
    ToneGenerator.cpp \
    mediaplayer.cpp \
    IMediaPlayer.cpp \
    IMediaPlayerService.cpp \
    IMediaPlayerClient.cpp \
    IMediaMetadataRetriever.cpp \
    mediametadataretriever.cpp \
    IMediaRecorder.cpp \
    mediarecorder.cpp \
    IOMX.cpp \
    Metadata.cpp

# ---------------------------------------------------------- libaudioflinger ---
# A2dpAudioInterface.cpp needs liba2dp (bluez) and AudioDumpInterface.cpp is a
# debug shim; neither is selected by any -D we pass, so neither is built.
build_group audioflinger "$FWBASE/libs/audioflinger" \
    AudioFlinger.cpp \
    AudioMixer.cpp \
    AudioResampler.cpp \
    AudioResamplerCubic.cpp \
    AudioResamplerSinc.cpp \
    AudioHardwareInterface.cpp \
    AudioHardwareGeneric.cpp \
    AudioHardwareStub.cpp \
    AudioPolicyService.cpp \
    AudioPolicyManagerGeneric.cpp

# ----------------------------------------------------- libmediaplayerservice ---
build_group mediaplayerservice "$FWBASE/media/libmediaplayerservice" \
    MediaPlayerService.cpp \
    WavPlayer.cpp \
    WavRecorder.cpp

# --------------------------------------------------------------- soundpool ---
build_group soundpool "$FWBASE/media/jni/soundpool" \
    SoundPool.cpp \
    SoundPoolThread.cpp

echo "audio stack sources: OK=$OK FAIL=$FAIL"
if [ -n "$FAILED" ]; then
    echo "failed:$FAILED"
    echo "--- first 120 lines of $OUT/build.log ---"
    sed -n '1,120p' "$OUT/build.log"
    exit 1
fi

"$AR" rcs "$OUT/libmedia.a"              "$OUT"/obj/media_*.o
"$AR" rcs "$OUT/libaudioflinger.a"       "$OUT"/obj/audioflinger_*.o
"$AR" rcs "$OUT/libmediaplayerservice.a" "$OUT"/obj/mediaplayerservice_*.o
"$AR" rcs "$OUT/libsoundpool.a"          "$OUT"/obj/soundpool_*.o

# Self-verification. An archive that builds but is missing the symbol the
# service registration needs links to a mediaserver that publishes nothing.
check_sym() {
    if ! "$AR" t "$1" >/dev/null 2>&1; then
        echo "VERIFY FAILED: $1 is not an archive"; exit 1
    fi
    if ! "$TC/arm-buildroot-linux-gnueabihf-nm" "$1" 2>/dev/null \
            | grep -q "$2"; then
        echo "VERIFY FAILED: $2 not defined in $(basename "$1")"; exit 1
    fi
}
check_sym "$OUT/libaudioflinger.a"       'T .*AudioFlinger.*instantiate'
check_sym "$OUT/libaudioflinger.a"       'T .*AudioPolicyService.*instantiate'
check_sym "$OUT/libmediaplayerservice.a" 'T .*MediaPlayerService.*instantiate'
check_sym "$OUT/libmedia.a"              'T .*ToneGenerator'
# MediaPlayerService::createMediaRecorder() returns one of these. If the
# symbol is missing the service still links and still publishes, and
# recording is simply dead again -- the exact failure this replaced.
check_sym "$OUT/libmediaplayerservice.a" 'T .*WavRecorder'
echo "verify: AudioFlinger, AudioPolicyService, MediaPlayerService, ToneGenerator and WavRecorder all present"

ls -la "$OUT"/*.a
echo "=== build_audio_stack: ALL OK ==="
