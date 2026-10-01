#!/bin/bash
# Build Eclair's SettingsProvider as the platform-signed system APK. Core
# services query content://settings during SystemServer boot; without it the
# system process deliberately kills itself before ActivityManager launches HOME.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
TP="$ROOT/third_party"
SRC="$TP/frameworks/base/packages/SettingsProvider"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JARSIGNER="$JDK/bin/jarsigner"
AAPT="$ROOT/build/aapt/aapt"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW_CLASSES="$ROOT/build/framework_jar/classes.jar"
CORE_CLASSES="$ROOT/build/core/classes.jar"
SEC="$TP/build_system/target/product/security"
OUT="$ROOT/build/settings_provider"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$OVERLAY/system/app"
SYSTEM_ETC="$OVERLAY/system/etc"
N3DS_BOOKMARKS="${ANDROID3DS_WIN}/content/system/etc/bookmarks.xml"
LOG="$ROOT/build_settings_provider.log"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$SRC/AndroidManifest.xml" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_settings_provider: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
: > "$LOG"

echo '=== 1/5 aapt: SettingsProvider resources ==='
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/SettingsProvider.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/SettingsProvider.apk" classes.dex ) \
    >> "$LOG" 2>&1

echo '=== 5/5 platform signature ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/SettingsProvider.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/SettingsProvider.apk" >> "$LOG" 2>&1

mkdir -p "$TARGET"
cp "$OUT/SettingsProvider.apk" "$TARGET/SettingsProvider.apk"
chmod 644 "$TARGET/SettingsProvider.apk"
rm -f "$TARGET/SettingsProvider.odex"
mkdir -p "$SYSTEM_ETC"
cp "$N3DS_BOOKMARKS" "$SYSTEM_ETC/bookmarks.xml"
chmod 644 "$SYSTEM_ETC/bookmarks.xml"

"$AAPT" list "$TARGET/SettingsProvider.apk" | grep -qx classes.dex
"$AAPT" dump xmltree "$TARGET/SettingsProvider.apk" AndroidManifest.xml \
    | grep -q 'android:authorities.*="settings"'
echo '=== build_settings_provider: ALL OK ==='
ls -la "$TARGET/SettingsProvider.apk"
