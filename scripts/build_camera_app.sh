#!/bin/bash
# Build and deploy the real AOSP stock Camera application (com.android.camera,
# from platform/packages/apps/Camera at the eclair-release branch -- the same
# branch the rest of this port's framework comes from).
#
# This replaces N3dsCamera, the hand-written diagnostic shell that only ever
# reported whether the kernel driver had probed. That app was useful while the
# camera was nothing but a register-poking experiment, and it was also actively
# misleading by the end: it read dmesg to decide whether the driver existed, and
# the binder RLIMIT_NICE log firehose had wrapped the ring buffer past the probe
# messages, so it printed "kernel driver: NOT FOUND" about a driver that had in
# fact probed fine and had both sensors streaming.
#
# WHAT IS UNDER IT (2026-09-30):
#   Everything is real from the app down: android.hardware.Camera, the JNI,
#   CameraService, and a real HAL, CameraHardwareN3ds (N3DS_CAMERA_HAL, built
#   by build_mediaserver.sh), which reads YUYV frames from /dev/ctr_cam and
#   posts RGB565 preview frames and libjpeg-encoded pictures.  The stub is
#   gone.
#
#   N3DS changes to the app itself, all marked in the source:
#     N3DS_CAMERA_SIZES   640x480 and 320x240 in the picture-size arrays.
#                         The sensors are VGA; without them the settings
#                         filter emptied the list and crashed on
#                         setValueIndex(0).
#     N3DS_CAMERA_SWITCH  "Switch camera" menu item: back <-> front, via the
#                         HAL's n3ds-camera-id parameter.  Two cameras, like
#                         the 3DS's own 2D camera: back is the outer-right
#                         sensor; the outer-left one is only half of the
#                         stereo pair used for 3D photos.
#     N3DS_NO_VIDEO       the stills/video switch refuses video with a toast;
#                         there is no video encoder on this device.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
CONTENT="${ANDROID3DS_WIN}/content/camera"
TP="$ROOT/third_party"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JARSIGNER="$JDK/bin/jarsigner"
AAPT="$ROOT/build/aapt/aapt"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW_CLASSES="$ROOT/build/framework_jar/classes.jar"
CORE_CLASSES="$ROOT/build/core/classes.jar"
SEC="$TP/build_system/target/product/security"
OUT="$ROOT/build/camera_app"
SRC="$OUT/source"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$OVERLAY/system/app"
LOG="$ROOT/build_camera_app.log"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$CONTENT/AndroidManifest.xml" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_camera_app: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
cp -a "$CONTENT" "$SRC"
rm -rf "$SRC/tests"
: > "$LOG"

echo '=== 1/5 aapt: Camera resources ==='
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/Camera.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/Camera.apk" classes.dex ) >> "$LOG" 2>&1

echo '=== 5/5 platform signature/deploy ==='
# Upstream signs this with the "media" certificate because it shares a uid
# (android.media) with MediaProvider. Here both are platform-signed instead,
# like every other app in this image. The shared uid needs the certificates to
# match: build_media_provider.sh checks it against this APK, so if this key
# ever changes, re-run that script too.
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/Camera.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/Camera.apk" >> "$LOG" 2>&1

mkdir -p "$TARGET"
cp "$OUT/Camera.apk" "$TARGET/Camera.apk"
chmod 644 "$TARGET/Camera.apk"
rm -f "$TARGET/Camera.odex"

# Retire the diagnostic shell it replaces, from the overlay (the source of
# truth). sync_android_to_sdcard.sh does not delete, so the SD copies are
# removed by hand in the same commit -- see the note in that script.
rm -f "$TARGET/N3dsCamera.apk" "$TARGET/N3dsCamera.odex"

"$AAPT" list "$TARGET/Camera.apk" | grep -qx classes.dex
"$AAPT" dump badging "$TARGET/Camera.apk" \
    | grep -F "package: name='com.android.camera'"
"$AAPT" dump badging "$TARGET/Camera.apk" \
    | grep -F "launchable activity name='com.android.camera.Camera'"
# Real upstream classes, not a stand-in: assert three that only the genuine
# app has. Extract the dex once rather than re-running the pipeline per class:
# `grep -q` closes the pipe as soon as it matches, and under `pipefail` that
# SIGPIPEs unzip and fails the pipeline on a *successful* match.
unzip -p "$TARGET/Camera.apk" classes.dex > "$OUT/deployed.dex"
strings "$OUT/deployed.dex" > "$OUT/deployed.strings"
for c in Lcom/android/camera/Camera Lcom/android/camera/VideoCamera \
         Lcom/android/camera/ImageGallery; do
    grep -qF "$c" "$OUT/deployed.strings" \
        || { echo "build_camera_app: $c missing from dex" >&2; exit 1; }
done
# The N3DS changes, so a stale content/camera copy cannot ship silently.
for c in "N3DS_CAMERA_SWITCH: camera " n3ds-camera-id; do
    grep -qF "$c" "$OUT/deployed.strings"         || { echo "build_camera_app: '$c' missing from dex" >&2; exit 1; }
done
"$AAPT" dump --values resources "$TARGET/Camera.apk" > "$OUT/deployed.res"
for c in '"640x480"' '"320x240"' '"Switch camera"'; do
    grep -qF "$c" "$OUT/deployed.res"         || { echo "build_camera_app: resource $c missing" >&2; exit 1; }
done
echo '=== build_camera_app: ALL OK ==='
ls -la "$TARGET/Camera.apk"
