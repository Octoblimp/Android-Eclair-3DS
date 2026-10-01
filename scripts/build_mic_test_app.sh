#!/bin/bash
# Build and deploy the Android3DS microphone record/playback test application.
#
# Unlike its siblings this reads $ROOT/content, not the Windows content tree.
# The Windows copy is what find_script()-style lookups prefer and what the
# older build scripts hard-code, but it is untracked in both repos: a build
# from there is a build from source that cannot be committed or reviewed.
# scripts/make_mictest-style generation writes both trees from one definition,
# so the two are identical; when they are not, the tracked one is the one to
# trust.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
CONTENT="$ROOT/content/mictest"
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
OUT="$ROOT/build/mictest_app"
SRC="$OUT/source"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$OVERLAY/system/app"
LOG="$ROOT/build_mic_test_app.log"
MARKER='N3DS_MIC_TEST_READY AudioRecord 8000 Hz mono 16-bit WAV recorder'

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$CONTENT/AndroidManifest.xml" "$CONTENT/res/drawable/icon.png" \
         "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_mic_test_app: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
cp -a "$CONTENT" "$SRC"
: > "$LOG"

echo '=== 1/5 aapt: Mic Test resources ==='
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/MicTest.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/MicTest.apk" classes.dex ) >> "$LOG" 2>&1

echo '=== 5/5 platform signature/deploy ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/MicTest.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/MicTest.apk" >> "$LOG" 2>&1

mkdir -p "$TARGET"
cp "$OUT/MicTest.apk" "$TARGET/MicTest.apk"
chmod 644 "$TARGET/MicTest.apk"
rm -f "$TARGET/MicTest.odex"

"$AAPT" list "$TARGET/MicTest.apk" | grep -qx classes.dex
"$AAPT" dump badging "$TARGET/MicTest.apk" \
    | grep -F "package: name='com.android.mictest'"
"$AAPT" dump badging "$TARGET/MicTest.apk" \
    | grep -F "launchable activity name='com.android.mictest.MicTestActivity'"
"$AAPT" dump badging "$TARGET/MicTest.apk" \
    | grep -F "uses-permission:'android.permission.RECORD_AUDIO'"
# A launcher icon must resolve to a real PNG.  This framework silently renders
# an XML shape/layer-list drawable as a blank fallback circle, so the icon is
# asserted to be a .png rather than merely present.
"$AAPT" dump badging "$TARGET/MicTest.apk" \
    | grep -E "^application: .*icon='res/drawable/icon.png'"
unzip -p "$TARGET/MicTest.apk" classes.dex | strings | grep -F "$MARKER"
# MediaRecorder's JNI is not in gRegJNI in this build; every call to it would
# throw UnsatisfiedLinkError at runtime.  Prove the dex never names it.
if unzip -p "$TARGET/MicTest.apk" classes.dex | strings \
        | grep -qE 'Landroid/media/MediaRecorder;->'; then
    echo 'FATAL: MicTest calls MediaRecorder, whose JNI is absent' >&2
    exit 1
fi
echo '=== build_mic_test_app: ALL OK ==='
ls -la "$TARGET/MicTest.apk"
