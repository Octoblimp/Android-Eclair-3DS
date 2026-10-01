#!/bin/bash
# Original Eclair SMS/MMS database used by the stock Messages application.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail
ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
SRC="$PROJECT/third_party/TelephonyProvider"
OUT="$ROOT/build/telephony_provider"
OVERLAY="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
AAPT="$ROOT/build/aapt/aapt"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW="$ROOT/build/framework_jar/classes.jar"
CORE="$ROOT/build/core/classes.jar"
SEC="$ROOT/third_party/build_system/target/product/security"
LOG="$ROOT/build_telephony_provider.log"
for file in "$SRC/AndroidManifest.xml" "$FWRES" "$FW" "$CORE" "$AAPT" "$DX"; do
    test -s "$file" || { echo "Missing provider build input: $file" >&2; exit 1; }
done
rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
mkdir -p "$OUT/source"
cp -a "$SRC/src" "$SRC/res" "$SRC/AndroidManifest.xml" "$OUT/source/"
SRC="$OUT/source"
: > "$LOG"
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/TelephonyProvider.apk" >> "$LOG" 2>&1
find "$SRC/src" "$OUT/gen" -name '*.java' -type f > "$OUT/sources.txt"
"$JDK/bin/javac" -J-Xmx512m -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE:$FW" -classpath "$FW:$CORE" \
    -d "$OUT/classes" @"$OUT/sources.txt" >> "$LOG" 2>&1
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1
(cd "$OUT/dex" && "$AAPT" add -f "$OUT/TelephonyProvider.apk" classes.dex) >> "$LOG" 2>&1
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" -in "$SEC/platform.x509.pem" \
    -name platform -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
printf '%s\n' 'jdk.jar.disabledAlgorithms=' > "$OUT/jarsigner.security"
"$JDK/bin/jarsigner" -keystore "$OUT/platform.p12" -storetype pkcs12 -storepass android \
    -sigalg SHA1withRSA -digestalg SHA1 "$OUT/TelephonyProvider.apk" platform >> "$LOG" 2>&1
"$JDK/bin/jarsigner" -J-Djava.security.properties="$OUT/jarsigner.security" \
    -verify -verbose -certs "$OUT/TelephonyProvider.apk" >> "$LOG" 2>&1
tail -40 "$LOG" | grep -F 'jar verified.' >/dev/null
"$AAPT" list "$OUT/TelephonyProvider.apk" | grep -qx classes.dex
"$AAPT" dump xmltree "$OUT/TelephonyProvider.apk" AndroidManifest.xml > "$OUT/manifest.txt"
for authority in sms mms mms-sms; do
    grep -F "android:authorities" "$OUT/manifest.txt" | grep -F "=\"$authority\"" >/dev/null
done
mkdir -p "$OVERLAY/system/app"
cp "$OUT/TelephonyProvider.apk" "$OVERLAY/system/app/TelephonyProvider.apk"
chmod 644 "$OVERLAY/system/app/TelephonyProvider.apk"
rm -f "$OVERLAY/system/app/TelephonyProvider.odex"
sha256sum "$OUT/TelephonyProvider.apk"
echo '=== build_telephony_provider: ALL OK ==='
