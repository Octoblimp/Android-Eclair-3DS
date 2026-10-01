#!/bin/bash
# Transcode the Android sound assets into the only format this image can play.
#
# WavPlayer (media/libmediaplayerservice/WavPlayer.cpp) is the entire decoder
# stack here: there is no external/opencore, no external/tremolo and no
# external/sonivox, so every upstream .ogg in frameworks/base/data/sounds is
# undecodable.  ffmpeg does the decoding once, at build time, into RIFF/WAVE
# 16-bit PCM, which WavPlayer reads with fread().
#
# 22050 Hz mono is deliberate.  AudioFlinger's AudioMixer resamples anything up
# to 2x the output rate and the CSND driver runs at 44100 Hz stereo, so 22050
# mono is the largest rate that still halves the file size, and ctr_csnd's
# write path folds stereo to mono anyway (one CSND channel drives both
# speakers) -- shipping stereo would double the image for nothing.
#
# The boot sound is different and does NOT go through any of this.  The boot
# animation runs long before zygote, let alone mediaserver, so there is no
# AudioFlinger to ask: /etc/bootanim.sh writes raw PCM straight to /dev/eac,
# which needs 44100 Hz 16-bit stereo little-endian with no header at all.
#
# Idempotent and incremental: a destination newer than its source is skipped,
# so a re-run after one new asset costs one ffmpeg call.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
SOUNDS="$ROOT/third_party/frameworks/base/data/sounds"
OVERLAY="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay"
AUDIO="$OVERLAY/system/media/audio"
# The boot sound's source recording is not in the repo; point
# ANDROID3DS_BOOT_SOUND (e.g. in ~/.config/android3ds/env) at it to
# re-encode. Without it the committed bootsound.pcm is left alone.
BOOTSRC="${ANDROID3DS_BOOT_SOUND:-$HOME/Downloads/android_audio/android_audio.mp3}"
BOOTPCM="$OVERLAY/system/media/bootsound.pcm"

RATE=22050
FF="ffmpeg -hide_banner -loglevel error -y"

command -v ffmpeg >/dev/null || { echo "ffmpeg not installed"; exit 1; }
test -d "$SOUNDS" || { echo "missing $SOUNDS"; exit 1; }

mkdir -p "$AUDIO/ui" "$AUDIO/notifications" "$AUDIO/ringtones" "$AUDIO/alarms" \
         "$AUDIO/telco"

conv=0
skip=0

# transcode <relative-source> <destination-subdir> [<destination-basename>]
transcode() {
    src="$SOUNDS/$1"
    dstdir="$AUDIO/$2"
    base="${3:-$(basename "$1")}"
    dst="$dstdir/${base%.*}.wav"
    if [ ! -f "$src" ]; then
        echo "  MISSING $1"
        return 0
    fi
    if [ -f "$dst" ] && [ "$dst" -nt "$src" ]; then
        skip=$((skip + 1))
        return 0
    fi
    $FF -i "$src" -ac 1 -ar "$RATE" -c:a pcm_s16le -f wav "$dst"
    conv=$((conv + 1))
}

# --- ui -------------------------------------------------------------------
# AudioService loads these five into a SoundPool and plays them for every
# keypress, list scroll, focus move and click -- the "navigation, tapping and
# selection" sounds. camera_click and VideoRecord are named directly by
# CameraService.cpp (it constructs a MediaPlayer on the literal path).
echo "=== ui ==="
for f in Effect_Tick KeypressStandard KeypressSpacebar KeypressDelete \
         KeypressReturn VideoRecord camera_click; do
    transcode "effects/$f.ogg" ui
done

# --- notifications --------------------------------------------------------
# F1_New_SMS is the one Mms uses for an incoming text; F1_MissedCall and
# F1_NewVoicemail are what the telephony stack posts.
echo "=== notifications ==="
for f in F1_New_SMS F1_New_MMS F1_MissedCall F1_NewVoicemail; do
    transcode "$f.ogg" notifications
done
for f in Beat_Box_Android Bees_Knees Cheeper Heaven IM_Me ShortCircuit \
         Star_Struck TaDa Tinkerbell moonbeam pixiedust pizzicato tweeters; do
    transcode "notifications/$f.ogg" notifications
done
for f in CaffeineSnake DearDeer DontPanic Highwire KzurbSonar OnTheHunt Voila; do
    transcode "newwavelabs/$f.ogg" notifications
done

# --- ringtones ------------------------------------------------------------
# A deliberately trimmed set. Ringtones are the long assets (20-30s each) and
# uncompressed PCM is ~44 KB/s, so the full AudioPackage3 list would add tens
# of megabytes to an image that is synced to SD over a slow path.
echo "=== ringtones ==="
for f in Ring_Classic_02 Ring_Digital_02 Ring_Synth_02 Ring_Synth_04; do
    transcode "$f.ogg" ringtones
done
for f in BeatPlucker BentleyDubs BirdLoop CurveBall EtherShake Growl \
         LoopyLounge LoveFlute MidEvilJaunt MildlyAlarming NewPlayer \
         Noises1 OrganDub Terminated TwirlAway World; do
    transcode "newwavelabs/$f.ogg" ringtones
done

# --- alarms ---------------------------------------------------------------
echo "=== alarms ==="
for f in Alarm_Buzzer Alarm_Beep_01 Alarm_Beep_02 Alarm_Beep_03 \
         Alarm_Classic Alarm_Rooster_02; do
    transcode "$f.ogg" alarms
done

echo "transcoded: $conv   up-to-date: $skip"

# --- boot sound -----------------------------------------------------------
# Raw headerless PCM: /dev/eac is a character device, not a file format. The
# rate has to match the driver's pcm_rate module parameter (44100) because
# nothing in this path resamples, and it has to be stereo because
# ctr_csnd_dev_write() masks the count to whole 4-byte stereo frames and
# averages the pair down to the single CSND channel.
echo "=== boot sound ==="
if [ ! -f "$BOOTSRC" ]; then
    echo "  $BOOTSRC not found -- leaving $(basename "$BOOTPCM") alone"
elif [ -f "$BOOTPCM" ] && [ "$BOOTPCM" -nt "$BOOTSRC" ]; then
    echo "  up to date"
else
    $FF -i "$BOOTSRC" -ac 2 -ar 44100 -c:a pcm_s16le -f s16le "$BOOTPCM"
    echo "  $(stat -c %s "$BOOTPCM") bytes raw s16le 44100 stereo"
fi

# --- 3DSTelco spoken announcements ----------------------------------------
# Assembled at run time by TelcoAudio.java as
#     caller.wav  d<digit>.wav ...  unavailable.wav
# so one clip per digit covers every 3- and 4-digit subscriber number without
# a TTS engine.  espeak-ng is a build-time dependency only; nothing in the
# image synthesises speech.
#
# The leading and trailing silence espeak-ng pads each utterance with has to
# go, or a four-digit number takes six seconds to read out.  The areverse
# sandwich trims both ends and leaves a fixed, deliberate gap: 120 ms between
# digits so they do not slur, 60 ms between phrases.
echo "=== telco announcements ==="
TELCO="$AUDIO/telco"
ESPEAK_ARGS="-v en-us -s 150 -p 45 -a 190"
TRIM_HEAD="silenceremove=start_periods=1:start_threshold=-50dB:detection=peak"

# say <basename> <trailing-silence-seconds> <text>
say() {
    dst="$TELCO/$1.wav"
    keep="$2"
    text="$3"
    if [ -f "$dst" ] && [ "$dst" -nt "$0" ]; then
        skip=$((skip + 1))
        return 0
    fi
    raw="$TELCO/.$1.raw.wav"
    espeak-ng $ESPEAK_ARGS -w "$raw" "$text"
    $FF -i "$raw" -ac 1 -ar "$RATE" -c:a pcm_s16le         -af "$TRIM_HEAD,areverse,${TRIM_HEAD}:start_silence=$keep,areverse"         -f wav "$dst"
    rm -f "$raw"
    conv=$((conv + 1))
}

if ! command -v espeak-ng >/dev/null; then
    missing=0
    for f in caller unavailable recorded d0 d1 d2 d3 d4 d5 d6 d7 d8 d9; do
        [ -f "$TELCO/$f.wav" ] || missing=$((missing + 1))
    done
    if [ "$missing" -ne 0 ]; then
        echo "espeak-ng is not installed and $missing announcement clip(s) are"
        echo "missing.  Install it (apt-get install espeak-ng) -- the Phone app"
        echo "cannot tell a caller the callee is unavailable without them."
        exit 1
    fi
    echo "  espeak-ng absent; all clips already built, leaving them alone"
else
    say caller 0.06 "The caller"
    say unavailable 0.06 "is unavailable. Please leave a message after the tone."
    say recorded 0.06 "Your message has been saved. Goodbye."
    i=0
    for word in zero one two three four five six seven eight nine; do
        say "d$i" 0.12 "$word"
        i=$((i + 1))
    done
    echo "  $(find "$TELCO" -name '*.wav' | wc -l) clips in $TELCO"
fi

# --- verification ---------------------------------------------------------
# Anything WavPlayer::parseHeader() would reject is a silent no-sound bug on
# hardware, so assert the shape here instead: RIFF/WAVE, PCM tag, 16-bit.
bad=0
for w in $(find "$AUDIO" -name '*.wav'); do
    hdr=$(od -An -tx1 -N44 "$w" | tr -d ' \n')
    case "$hdr" in
    52494646*) ;;
    *) echo "NOT RIFF: $w"; bad=$((bad + 1)); continue ;;
    esac
    # bits-per-sample is the 16-bit LE field at offset 34 of a canonical
    # 44-byte header, which is what ffmpeg's wav muxer writes.
    bps=$(od -An -tu2 -j34 -N2 "$w" | tr -d ' ')
    [ "$bps" = 16 ] || { echo "NOT 16-bit ($bps): $w"; bad=$((bad + 1)); }
done
if [ "$bad" -ne 0 ]; then
    echo "VERIFY FAILED: $bad file(s) WavPlayer cannot parse"
    exit 1
fi

# The announcement is the one asset set with a hard consumer: TelcoAudio.java
# names these files literally, so a missing one is a silent call, not a
# degraded one.  Assert the whole set rather than the count.
for f in caller unavailable recorded d0 d1 d2 d3 d4 d5 d6 d7 d8 d9; do
    test -s "$AUDIO/telco/$f.wav" || {
        echo "VERIFY FAILED: missing announcement clip telco/$f.wav"
        exit 1
    }
done

n=$(find "$AUDIO" -name '*.wav' | wc -l)
echo "verify  : $n wav files, all RIFF/WAVE 16-bit PCM"
du -sh "$AUDIO"
test -s "$BOOTPCM" && echo "boot    : $BOOTPCM $(stat -c %s "$BOOTPCM") bytes"
echo "=== build_audio_assets: OK ==="
