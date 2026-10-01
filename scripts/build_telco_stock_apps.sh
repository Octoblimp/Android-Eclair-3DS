#!/bin/bash
# Build the original Eclair Phone, Contacts/Dialer, and Mms apps with bounded
# Android3DS 3DSTelco overlays. Set STAGE_TELCO_APPS=1 only for release staging.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
TP="$ROOT/third_party"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JARSIGNER="$JDK/bin/jarsigner"
AAPT="$ROOT/build/aapt/aapt"
AIDL="$ROOT/build/aidl/aidl"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW_CLASSES="$ROOT/build/framework_jar/classes.jar"
CORE_CLASSES="$ROOT/build/core/classes.jar"
SEC="$TP/build_system/target/product/security"
OUT="$ROOT/build/telco_stock_apps"
TARGET="$TP/buildroot/board/nintendo3ds/rootfs_overlay/system/app"
LOG="$ROOT/build_telco_stock_apps.log"
SIGN_SECURITY="$OUT/jarsigner.security"

for file in "$AAPT" "$AIDL" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
    "$SEC/platform.pk8" "$SEC/platform.x509.pem" "$SEC/shared.pk8" "$SEC/shared.x509.pem"; do
    test -e "$file" || { echo "build_telco_stock_apps: missing $file" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT"
: > "$LOG"
# Android Eclair requires v1 SHA-1 APK signatures. Modern JDK policy otherwise
# reports these correctly signed platform APKs as unsigned, so confine the
# compatibility override to this verification process and build directory.
printf '%s\n' 'jdk.jar.disabledAlgorithms=' > "$SIGN_SECURITY"

# N3DS_NO_STOCK_CONTACTS (#317): the stock Contacts app is retired -- the
# dialer is N3dsDialer, ContactsProvider is built on its own.
for app in Phone Mms; do
    test -f "$TP/$app/AndroidManifest.xml" || { echo "missing stock $app" >&2; exit 1; }
    mkdir -p "$OUT/$app"
    cp -a "$TP/$app" "$OUT/$app/source"
    if [ -d "$PROJECT/content/stock-app-overlays/$app" ]; then
        cp -a "$PROJECT/content/stock-app-overlays/$app/." "$OUT/$app/source/"
    fi
done

python3 "$PROJECT/scripts/patch_telco_stock_apps.py" \
    "$OUT/Phone/source" "$OUT/Mms/source"

build_one() {
    app="$1"
    cert="$2"
    app_out="$OUT/$app"
    source="$app_out/source"
    mkdir -p "$app_out/gen" "$app_out/classes" "$app_out/dex"

    aapt_args=(package -f -m -M "$source/AndroidManifest.xml" -S "$source/res" -I "$FWRES" -J "$app_out/gen" -F "$app_out/$app.apk")
    if [ -d "$source/assets" ]; then aapt_args+=( -A "$source/assets" ); fi
    "$AAPT" "${aapt_args[@]}" >> "$LOG" 2>&1

    if [ "$app" = Phone ]; then
        while IFS= read -r aidl; do
            "$AIDL" -I"$source/src" -I"$TP/frameworks/base/core/java" \
                -I"$TP/frameworks/base/telephony/java" -o"$app_out/gen" "$aidl" >> "$LOG" 2>&1
        done < <(find "$source/src" -name '*.aidl' -type f | sort)
    fi

    # The current minimal framework JAR intentionally omits android.webkit.
    # Mms only needs this small pure-Java helper; compile the canonical Eclair
    # source into the copied app build until the full WebKit framework lands.
    if [ "$app" = Mms ] && ! jar tf "$FW_CLASSES" | grep -qx 'android/webkit/MimeTypeMap.class'; then
        mkdir -p "$app_out/gen/android/webkit"
        cp "$TP/frameworks/base/core/java/android/webkit/MimeTypeMap.java" \
            "$app_out/gen/android/webkit/MimeTypeMap.java"
    fi

    find "$source/src" "$app_out/gen" -name '*.java' -type f \
        | grep -v '/tests/' \
        | grep -v '/SplitAggregateView.java$' \
        | grep -v '/BluetoothHeadsetService.java$' \
        > "$app_out/sources.txt"
    "$JAVAC" -J-Xmx1024m -nowarn -encoding UTF-8 -source 6 -target 6 \
        -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
        -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$app_out/classes" \
        @"$app_out/sources.txt" >> "$LOG" 2>&1
    "$DX" --dex --output="$app_out/dex/classes.dex" "$app_out/classes" >> "$LOG" 2>&1
    ( cd "$app_out/dex" && "$AAPT" add -f "$app_out/$app.apk" classes.dex ) >> "$LOG" 2>&1

    openssl pkcs8 -inform DER -nocrypt -in "$SEC/$cert.pk8" -out "$app_out/$cert.pem" >> "$LOG" 2>&1
    openssl pkcs12 -export -inkey "$app_out/$cert.pem" -in "$SEC/$cert.x509.pem" \
        -name "$cert" -out "$app_out/$cert.p12" -passout pass:android >> "$LOG" 2>&1
    "$JARSIGNER" -keystore "$app_out/$cert.p12" -storetype pkcs12 -storepass android \
        -sigalg SHA1withRSA -digestalg SHA1 "$app_out/$app.apk" "$cert" >> "$LOG" 2>&1
    "$JARSIGNER" -J-Djava.security.properties="$SIGN_SECURITY" \
        -verify -verbose -certs "$app_out/$app.apk" >> "$LOG" 2>&1
    tail -40 "$LOG" | grep -F 'jar verified.' >/dev/null
    "$AAPT" list "$app_out/$app.apk" | grep -qx classes.dex
}

echo '=== building original Phone.apk with 3DSTelco service/VoIP ==='
build_one Phone platform
echo '=== building original Mms.apk with 3DSTelco message transport ==='
build_one Mms platform

unzip -p "$OUT/Phone/Phone.apk" classes.dex | strings | grep -F 'N3DS_TELCO_ORIGINAL_PHONE_READY'
# NOT asserted for Contacts: 'io.divergen.telco.action.CALL'.  The dial
# routing that puts it there is not reproduced by this script -- the Contacts
# overlay directory is empty and patch_telco_stock_apps.py touches only
# QuickContactActivity -- so it exists solely in the shipped artifact.  See
# N3DS_TELCO_STAGING_IS_OPT_IN below; the difference is now enforced at
# staging time instead of asserted falsely here.
unzip -p "$OUT/Mms/Mms.apk" classes.dex | strings | grep -F 'N3DS_TELCO_ORIGINAL_MMS_READY'
"$AAPT" dump xmltree "$OUT/Phone/Phone.apk" AndroidManifest.xml \
    | grep -F 'A: package="com.android.phone"' >/dev/null
"$AAPT" dump xmltree "$OUT/Mms/Mms.apk" AndroidManifest.xml \
    | grep -F 'A: package="com.android.mms"' >/dev/null

# N3DS_TELCO_STAGING_IS_OPT_IN
#
# Staging is deliberately off by default, and this is not cosmetic caution.
# The Phone/Contacts/Mms that ship in rootfs_overlay/system/app carry hand
# applied patches whose sources are no longer in this workspace -- notably the
# Contacts dialer guards N3DS_DIALER_OPTIONAL_TONE_JNI,
# N3DS_DIALER_AUDIO_SERVICE_GUARD and N3DS_DIALER_LOCAL_KEYPAD, which
# scripts/test_telco_live_regressions.py asserts against the shipped artifact
# because the artifact is the only place they still exist.
#
# This script rebuilds those APKs from the AOSP sources plus the telco call
# routing patch only. Copying its output over the overlay therefore SILENTLY
# DROPS the dialer guards and the release gate fails at
# test_telco_live_regressions.py:35. If that happens, recover with
#   git show HEAD:board/nintendo3ds/rootfs_overlay/system/app/Contacts.apk
# in third_party/buildroot, restore it to the overlay and to BOTH sdcard
# staging trees, then re-run scripts/prebake_telco_odex.sh.
#
# Set STAGE_TELCO_APPS=1 only when you have confirmed the rebuilt APKs still
# contain every marker the gate asserts.
# Markers a shipped APK carries that a rebuild must not lose.  Read out of
# the dex rather than the sources precisely because the sources are what went
# missing.
telco_markers() {
    unzip -p "$1" classes.dex | strings \
        | grep -oE 'N3DS_[A-Z0-9_]+|io\.divergen\.telco\.action\.CALL' \
        | sort -u
}

# Markers whose feature was removed on purpose, and which a rebuild is
# therefore allowed to lose.  #325: the LOUD/QUIET speaker toggle is gone --
# 3DSTelco calls are always on the loudspeaker -- and its marker with it.
TELCO_RETIRED_MARKERS="N3DS_TELCO_SPEAKER_UNAVAILABLE"

# Refuse to stage an APK that would drop something the installed one has.
telco_staging_is_safe() {
    app="$1"
    shipped="$TARGET/$app.apk"
    rebuilt="$OUT/$app/$app.apk"
    if [ ! -f "$shipped" ]; then
        return 0
    fi
    lost="$(comm -23 <(telco_markers "$shipped") <(telco_markers "$rebuilt") \
        | grep -vxF -e "$(echo $TELCO_RETIRED_MARKERS | tr ' ' '\n')" || true)"
    if [ -n "$lost" ]; then
        echo "FATAL: staging $app would drop markers the shipped APK has:" >&2
        echo "$lost" | sed 's/^/    /' >&2
        echo "Recover the sources, or stage a different app with" >&2
        echo "  STAGE_TELCO_APPS=1 STAGE_TELCO_ONLY='Phone' $0" >&2
        exit 1
    fi
}

if [ "${STAGE_TELCO_APPS:-0}" = 1 ]; then
    mkdir -p "$TARGET"
    for app in ${STAGE_TELCO_ONLY:-Phone Mms}; do
        test -f "$OUT/$app/$app.apk" || {
            echo "STAGE_TELCO_ONLY names $app, which this script does not build" >&2
            exit 1
        }
        telco_staging_is_safe "$app"
        cp "$OUT/$app/$app.apk" "$TARGET/$app.apk"
        chmod 644 "$TARGET/$app.apk"
        rm -f "$TARGET/$app.odex"
        echo "staged $app.apk in $TARGET"
    done
fi

echo '=== build_telco_stock_apps: ALL OK ==='
sha256sum "$OUT/Phone/Phone.apk" "$OUT/Mms/Mms.apk"
