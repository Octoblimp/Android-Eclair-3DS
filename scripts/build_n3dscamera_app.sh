#!/bin/bash
# Build and deploy the Android3DS Camera application shell.
#
# N3DS_CAMERA_SHELL. Mirrors build_n3dsdialer_app.sh step for step; the only
# differences are the package name and the grep markers asserted at the end.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
CONTENT="${ANDROID3DS_WIN}/content/n3dscamera"
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
OUT="$ROOT/build/n3dscamera_app"
SRC="$OUT/source"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$OVERLAY/system/app"
LOG="$ROOT/build_n3dscamera_app.log"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$CONTENT/AndroidManifest.xml" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_n3dscamera_app: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
cp -a "$CONTENT" "$SRC"
: > "$LOG"

echo '=== 1/5 aapt: N3dsCamera resources ==='
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/N3dsCamera.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/N3dsCamera.apk" classes.dex ) \
    >> "$LOG" 2>&1

echo '=== 5/5 platform signature/deploy ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/N3dsCamera.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/N3dsCamera.apk" >> "$LOG" 2>&1

mkdir -p "$TARGET"
cp "$OUT/N3dsCamera.apk" "$TARGET/N3dsCamera.apk"
chmod 644 "$TARGET/N3dsCamera.apk"
rm -f "$TARGET/N3dsCamera.odex"

"$AAPT" list "$TARGET/N3dsCamera.apk" | grep -qx classes.dex
"$AAPT" dump badging "$TARGET/N3dsCamera.apk" \
    | grep -F "package: name='com.android.n3dscamera'"
"$AAPT" dump badging "$TARGET/N3dsCamera.apk" \
    | grep -F "launchable activity name='com.android.n3dscamera.N3dsCameraActivity'"
unzip -p "$TARGET/N3dsCamera.apk" classes.dex | strings \
    | grep -F 'N3DS_CAMERA_READY'
echo '=== build_n3dscamera_app: ALL OK ==='
ls -la "$TARGET/N3dsCamera.apk"
