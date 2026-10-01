#!/bin/bash
# Build the official AOSP Eclair Browser as a platform-signed system APK.
#
# The static-runtime integration this script used to wait on is done:
# libwebcore.a is linked into app_process and registered from gRegJNI[] as
# android::register_android_webkit_WebCore, and android.webkit is back in
# framework.jar, so WebView has an engine behind it and the stock sources
# compile with zero errors.  BROWSER_FRONT_END=stock (the default) builds
# them.
#
# BROWSER_FRONT_END=n3ds still builds the old 240-line placeholder activity
# against the cut-down manifest.  It is kept because it is the front end that
# has actually survived a boot on hardware: if the stock Browser turns out to
# misbehave on a 320x240 bottom screen, this is a one-variable way back to a
# Browser.apk that installs and launches.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

PROJECT="${ANDROID3DS_ROOT}"
TP=$PROJECT/third_party
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JARSIGNER="$JDK/bin/jarsigner"
AAPT=$PROJECT/build/aapt/aapt
DX=$PROJECT/build/dx/dx
SRC=$TP/browser
SEC=$TP/build_system/target/product/security
FWRES=$PROJECT/build/framework_res/framework-res.apk
FW_CLASSES=$PROJECT/build/framework_jar/classes.jar
CORE_CLASSES=$PROJECT/build/core/classes.jar
OUT=$PROJECT/build/browser
LOG=$PROJECT/build_browser.log
OVERLAY=$TP/buildroot/board/nintendo3ds/rootfs_overlay
TARGET=$OVERLAY/system/app
FRONT_END=${BROWSER_FRONT_END:-stock}

case "$FRONT_END" in
stock)
    MANIFEST=$SRC/AndroidManifest.xml
    SRCDIR=$SRC/src
    ;;
n3ds)
    MANIFEST=$SRC/AndroidManifest.n3ds.xml
    SRCDIR=$SRC/n3ds_src
    ;;
*)
    echo "build_browser: BROWSER_FRONT_END must be stock or n3ds" >&2
    exit 1
    ;;
esac

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$MANIFEST" "$SRCDIR" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    [ -e "$f" ] || { echo "build_browser: missing prerequisite $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
: > "$LOG"
echo "=== front end: $FRONT_END ($MANIFEST) ==="
cp "$MANIFEST" "$OUT/AndroidManifest.xml"

echo "=== 1/5 aapt: compiling Browser resources ==="
"$AAPT" package -f -m \
    -M "$OUT/AndroidManifest.xml" \
    -S "$SRC/res" \
    -A "$SRC/assets" \
    -I "$FWRES" \
    -J "$OUT/gen" \
    -F "$OUT/Browser.apk" \
    >> "$LOG" 2>&1 || { echo "FAILED (aapt)"; tail -80 "$LOG"; exit 1; }

echo "=== 2/5 javac ==="
find "$SRCDIR" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
echo "  $(wc -l < "$OUT/sources.txt") java files"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" \
    -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1 \
    || { echo "FAILED (javac)"; tail -100 "$LOG"; exit 1; }

echo "=== 3/5 dx ==="
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" \
    >> "$LOG" 2>&1 || { echo "FAILED (dx)"; tail -80 "$LOG"; exit 1; }

echo "=== 4/5 aapt add classes.dex ==="
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/Browser.apk" classes.dex ) \
    >> "$LOG" 2>&1 || { echo "FAILED (aapt add)"; tail -60 "$LOG"; exit 1; }

echo "=== 5/5 platform signing ==="
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" -in "$SEC/platform.x509.pem" \
    -name platform -out "$OUT/platform.p12" -passout pass:android \
    >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/Browser.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -verify "$OUT/Browser.apk"

mkdir -p "$TARGET"
cp "$OUT/Browser.apk" "$TARGET/Browser.apk"
chmod 644 "$TARGET/Browser.apk"

echo "=== Browser package ==="
"$AAPT" dump badging "$OUT/Browser.apk" | grep -E "^package:"
"$AAPT" dump badging "$OUT/Browser.apk" | grep -E "^launchable[ -]activity" || {
    echo "build_browser: no launchable activity -- nothing would appear in the launcher" >&2
    exit 1
}
"$AAPT" list "$OUT/Browser.apk" | grep -x classes.dex
ls -la "$TARGET/Browser.apk"
