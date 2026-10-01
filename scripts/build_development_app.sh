#!/bin/bash
# Build and deploy the Android3DS "Dev Tools" application (real upstream AOSP
# port, com.android.development, from platform/development apps/Development
# at the android-2.1_r1 tag). Replaces the old custom com.android.devtools
# stand-in app.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
CONTENT="${ANDROID3DS_WIN}/content/development"
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
OUT="$ROOT/build/development_app"
SRC="$OUT/source"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$OVERLAY/system/app"
LOG="$ROOT/build_development_app.log"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$CONTENT/AndroidManifest.xml" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_development_app: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
cp -a "$CONTENT" "$SRC"
: > "$LOG"

echo '=== 1/5 aapt: Development resources ==='
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/Development.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/Development.apk" classes.dex ) \
    >> "$LOG" 2>&1

echo '=== 5/5 platform signature/deploy ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/Development.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/Development.apk" >> "$LOG" 2>&1

mkdir -p "$TARGET"
cp "$OUT/Development.apk" "$TARGET/Development.apk"
chmod 644 "$TARGET/Development.apk"
rm -f "$TARGET/Development.odex"

"$AAPT" list "$TARGET/Development.apk" | grep -qx classes.dex
"$AAPT" dump badging "$TARGET/Development.apk" \
    | grep -F "package: name='com.android.development'"
"$AAPT" dump badging "$TARGET/Development.apk" \
    | grep -F "launchable activity name='com.android.development.Development'"
# No custom sentinel string exists in real upstream code (unlike the old
# fabricated app); verify the real ported classes actually made it into the
# dex instead.
unzip -p "$TARGET/Development.apk" classes.dex | strings \
    | grep -F 'Lcom/android/development/DevelopmentSettings;'
unzip -p "$TARGET/Development.apk" classes.dex | strings \
    | grep -F 'Lcom/android/development/PointerLocation;'
echo '=== build_development_app: ALL OK ==='
ls -la "$TARGET/Development.apk"
