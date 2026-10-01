#!/bin/bash
# Build the stock Eclair Settings application for the n3ds system image.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
TP="$ROOT/third_party"
SRC="$TP/settings"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JARSIGNER="$JDK/bin/jarsigner"
AAPT="$ROOT/build/aapt/aapt"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW_CLASSES="$ROOT/build/framework_jar/classes.jar"
CORE_CLASSES="$ROOT/build/core/classes.jar"
SEC="$TP/build_system/target/product/security"
OUT="$ROOT/build/settings_app"
BUILD_SRC="$OUT/source"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
TARGET="$OVERLAY/system/app"
LOG="$ROOT/build_settings_app.log"
SIGN_SECURITY="$OUT/jarsigner.security"

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$SRC/AndroidManifest.xml" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_settings_app: missing $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
: > "$LOG"
printf '%s\n' 'jdk.jar.disabledAlgorithms=' > "$SIGN_SECURITY"

# Stage the official Eclair tree and overlay only the hardware-appropriate
# entry screen/manifest. The source checkout stays pristine and reproducible.
cp -a "$SRC" "$BUILD_SRC"
cp "${ANDROID3DS_WIN}/content/settings/AndroidManifest.xml" \
    "$BUILD_SRC/AndroidManifest.xml"
cp "${ANDROID3DS_WIN}/content/settings/res/xml/settings.xml" \
    "$BUILD_SRC/res/xml/settings.xml"
cp "${ANDROID3DS_WIN}/content/settings/src/com/android/settings/Settings.java" \
    "$BUILD_SRC/src/com/android/settings/Settings.java"
cp "${ANDROID3DS_WIN}/content/settings/src/com/android/settings/WirelessAdbSettings.java" \
    "$BUILD_SRC/src/com/android/settings/WirelessAdbSettings.java"
cp "${ANDROID3DS_WIN}/content/settings/src/com/android/settings/MobileDataSettings.java" \
    "$BUILD_SRC/src/com/android/settings/MobileDataSettings.java"
# N3DS_DEV_UNKNOWN_SOURCES: Developer options carries an "Unknown sources"
# checkbox as well (Settings.Secure.INSTALL_NON_MARKET_APPS).
cp "${ANDROID3DS_WIN}/content/settings/src/com/android/settings/DevelopmentSettings.java" \
    "$BUILD_SRC/src/com/android/settings/DevelopmentSettings.java"
cp "${ANDROID3DS_WIN}/content/settings/res/xml/development_prefs.xml" \
    "$BUILD_SRC/res/xml/development_prefs.xml"

# The base Settings tree is a WSL-side checkout and can be older than the
# Windows overlay. Never let a retired Settings activity or its strings leak
# back into the APK merely because that checkout still has the old file.
while IFS= read -r -d '' stale; do
    case "$stale" in
        *[Ss]treet[Pp]ass*.java|*[Ss]treet[Pp]ass*.xml)
            rm -f "$stale" ;;
        *)
            case "$stale" in
                *.xml) sed -i '/[Ss]treet[Pp]ass/d' "$stale" ;;
                *) echo "build_settings_app: retired UI marker in $stale" >&2; exit 1 ;;
            esac ;;
    esac
done < <(grep -RIlZ '[Ss]treet[Pp]ass' "$BUILD_SRC" || true)

if grep -RIsq '[Ss]treet[Pp]ass' "$BUILD_SRC"; then
    echo 'build_settings_app: retired StreetPass marker remains in build source' >&2
    exit 1
fi

echo '=== 1/5 aapt: Settings resources ==='
"$AAPT" package -f -m -M "$BUILD_SRC/AndroidManifest.xml" -S "$BUILD_SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/Settings.apk" >> "$LOG" 2>&1

echo '=== 2/5 javac ==='
find "$BUILD_SRC/src" "$OUT/gen" -name '*.java' \
    | grep -Ev '/bluetooth/|/widget/|/vpn/|SettingsSafetyLegalActivity[.]java$|SettingsLicenseActivity[.]java$|SecuritySettings[.]java$|SoundAndDisplaySettings[.]java$|BrightnessPreference[.]java$|ApnEditor[.]java$|DockSettings[.]java$|WirelessSettings[.]java$' \
    > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 3/5 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1

echo '=== 4/5 package classes.dex ==='
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/Settings.apk" classes.dex ) \
    >> "$LOG" 2>&1

echo '=== 5/5 platform signature/deploy ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/Settings.apk" platform >> "$LOG" 2>&1
"$JARSIGNER" -J-Djava.security.properties="$SIGN_SECURITY" \
    -verify -verbose -certs "$OUT/Settings.apk" >> "$LOG" 2>&1
tail -40 "$LOG" | grep -F 'jar verified.' >/dev/null

# Verify the actual compiled payload, not just the source overlay.  The
# manifest, DEX, and resources are all checked because activity labels may
# live in any of them.
for payload in AndroidManifest.xml classes.dex resources.arsc; do
    if unzip -p "$OUT/Settings.apk" "$payload" | grep -aFi 'streetpass' >/dev/null; then
        echo "build_settings_app: retired StreetPass marker in $payload" >&2
        exit 1
    fi
done
if ! unzip -p "$OUT/Settings.apk" classes.dex | grep -aF 'Mobile Data' >/dev/null; then
    echo 'build_settings_app: Mobile Data class/string missing from compiled DEX' >&2
    exit 1
fi
if ! unzip -p "$OUT/Settings.apk" classes.dex | grep -aF '3DSTelco' >/dev/null; then
    echo 'build_settings_app: 3DSTelco class/string missing from compiled DEX' >&2
    exit 1
fi
# Binary XML/resource string pools are not guaranteed to be byte-searchable;
# use aapt's decoded views for the manifest and resources while retaining the
# raw-payload StreetPass scan above.
"$AAPT" dump xmltree "$OUT/Settings.apk" AndroidManifest.xml \
    | grep -F 'MobileDataSettings' >/dev/null
"$AAPT" dump xmltree "$OUT/Settings.apk" AndroidManifest.xml \
    | grep -F 'Mobile Data' >/dev/null
"$AAPT" dump xmltree "$OUT/Settings.apk" res/xml/settings.xml \
    | grep -F 'Mobile Data' >/dev/null
"$AAPT" dump xmltree "$OUT/Settings.apk" res/xml/settings.xml \
    | grep -F '3DSTelco' >/dev/null

"$AAPT" list "$OUT/Settings.apk" | grep -qx classes.dex
"$AAPT" dump xmltree "$OUT/Settings.apk" AndroidManifest.xml \
    | grep -F 'A: package="com.android.settings"' >/dev/null
if [ "${STAGE_SETTINGS_APP:-1}" = 1 ]; then
    mkdir -p "$TARGET"
    cp "$OUT/Settings.apk" "$TARGET/Settings.apk"
    chmod 644 "$TARGET/Settings.apk"
    rm -f "$TARGET/Settings.odex"
    echo "staged Settings.apk in $TARGET"
fi
echo '=== build_settings_app: ALL OK ==='
sha256sum "$OUT/Settings.apk"
