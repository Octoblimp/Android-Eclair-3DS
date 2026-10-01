#!/bin/bash
# Build the standalone Android3DS speed-test Activity with the Eclair toolchain.
# By default this only produces an app-specific build output. Set
# STAGE_SPEEDTEST=1 explicitly when the manager is ready to overlay the APK.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
CONTENT="$PROJECT/content/n3ds-speedtest"
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
OUT="$ROOT/build/n3ds_speedtest_app"
BUILD_SRC="$OUT/source"
LOG="$ROOT/build_speedtest.log"
TARGET="$TP/buildroot/board/nintendo3ds/rootfs_overlay/system/app"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$CONTENT/AndroidManifest.xml" \
         "$CONTENT/src/com/android/n3dsspeedtest/SpeedTestActivity.java" \
         "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_speedtest: missing $f" >&2; exit 1; }
done

# Require the authoritative source marker before copying to the generated
# build tree. This catches an accidental build from a stale WSL checkout.
grep -F 'N3DS_SPEEDTEST_READY' \
    "$CONTENT/src/com/android/n3dsspeedtest/SpeedTestActivity.java" >/dev/null

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
cp -a "$CONTENT" "$BUILD_SRC"
: > "$LOG"

echo '=== 1/5 aapt: N3DS Speed Test resources ==='
"$AAPT" package -f -m -M "$BUILD_SRC/AndroidManifest.xml" \
    -S "$BUILD_SRC/res" -I "$FWRES" -J "$OUT/gen" \
    -F "$OUT/N3DSSpeedTest.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$BUILD_SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/N3DSSpeedTest.apk" classes.dex ) \
    >> "$LOG" 2>&1

echo '=== 5/5 platform signature ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/N3DSSpeedTest.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/N3DSSpeedTest.apk" >> "$LOG" 2>&1

"$AAPT" list "$OUT/N3DSSpeedTest.apk" | grep -qx classes.dex
"$AAPT" dump badging "$OUT/N3DSSpeedTest.apk" \
    | grep -F "package: name='com.android.n3dsspeedtest'"
"$AAPT" dump badging "$OUT/N3DSSpeedTest.apk" \
    | grep -F "launchable activity name='com.android.n3dsspeedtest.SpeedTestActivity'"
unzip -p "$OUT/N3DSSpeedTest.apk" classes.dex | strings \
    | grep -F 'N3DS_SPEEDTEST_READY'

if [ "${STAGE_SPEEDTEST:-0}" = 1 ]; then
    mkdir -p "$TARGET"
    cp "$OUT/N3DSSpeedTest.apk" "$TARGET/N3DSSpeedTest.apk"
    chmod 644 "$TARGET/N3DSSpeedTest.apk"
    rm -f "$TARGET/N3DSSpeedTest.odex"
    echo "staged: $TARGET/N3DSSpeedTest.apk"
fi

echo '=== build_speedtest: ALL OK ==='
ls -l "$OUT/N3DSSpeedTest.apk"
