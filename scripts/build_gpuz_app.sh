#!/bin/bash
# Build and deploy the Android3DS GPU-Z application.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
CONTENT="${ANDROID3DS_WIN}/content/gpuz"
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
OUT="$ROOT/build/gpuz_app"
SRC="$OUT/source"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$OVERLAY/system/app"
LOG="$ROOT/build_gpuz_app.log"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$CONTENT/AndroidManifest.xml" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_gpuz_app: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
cp -a "$CONTENT" "$SRC"
: > "$LOG"

echo '=== 1/5 aapt: GPU-Z resources ==='
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/GPU-Z.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/GPU-Z.apk" classes.dex ) \
    >> "$LOG" 2>&1

echo '=== 5/5 platform signature/deploy ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/GPU-Z.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/GPU-Z.apk" >> "$LOG" 2>&1

mkdir -p "$TARGET"
cp "$OUT/GPU-Z.apk" "$TARGET/GPU-Z.apk"
chmod 644 "$TARGET/GPU-Z.apk"
rm -f "$TARGET/GPU-Z.odex"

"$AAPT" list "$TARGET/GPU-Z.apk" | grep -qx classes.dex
"$AAPT" dump badging "$TARGET/GPU-Z.apk" \
    | grep -F "package: name='com.android.gpuz'"
"$AAPT" dump badging "$TARGET/GPU-Z.apk" \
    | grep -F "launchable activity name='com.android.gpuz.GPUZActivity'"
echo '=== build_gpuz_app: ALL OK ==='
ls -la "$TARGET/GPU-Z.apk"
