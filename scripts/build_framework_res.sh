#!/bin/bash
# Compile frameworks/base/core/res (the "android" package itself -- attrs,
# styles, layouts, drawables, every string/locale) with the newly-built
# aapt into framework-res.apk + R.java. Stage 3 of the framework.jar plan
# (docs/HANDOFF.md "Immediate next steps" item 3).
#
# This is the one aapt invocation in the whole project that does NOT need
# -I <base apk>: core/res *defines* the "android" resource package rather
# than consuming it (there is nothing to inherit from -- it IS the
# framework), unlike every app-style resource compile.
#
# -x IS REQUIRED AND WAS MISSING UNTIL 2026-08-04.
#
# It is what frameworks/base/core/res/Android.mk itself passes
# (LOCAL_AAPT_FLAGS := -x), and it means "extended", i.e. non-application,
# resource IDs: the framework gets package ID 0x01, not the 0x7f every
# ordinary app gets. Without it this apk was built as an application package,
# so android.R.anim.accelerate_decelerate_interpolator came out as
# 0x7f0a0004 instead of 0x010a0004 -- and every other android.R and
# com.android.internal.R constant was likewise wrong.
#
# That is invisible for as long as nothing but the framework itself reads
# these resources (the framework and its own generated R.java were at least
# self-consistent, which is why boots got as far as they did). It breaks the
# moment a real app is added: aapt fails the app's own compile with
#   Adding multiple application package resources; only one is allowed.
#   Use -x to create extended resources.
# because -I framework-res.apk hands it a *second* 0x7f package, and every
# @android:... and android:* attribute reference in the app then resolves to
# nothing. Found while building the Launcher2 home screen.
#
# Changing this changes every constant in the generated android/R.java and
# com/android/internal/R.java, so framework.jar and services.jar MUST be
# rebuilt after this script runs, in that order.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

AAPT="${ANDROID3DS_ROOT}"/build/aapt/aapt
FWBASE="${ANDROID3DS_ROOT}"/third_party/frameworks/base
CORE_RES=$FWBASE/core/res
OUT="${ANDROID3DS_ROOT}"/build/framework_res
LOG="${ANDROID3DS_ROOT}"/build_framework_res.log

rm -rf "$OUT"
mkdir -p "$OUT/gen"

echo "=== compiling core/res with aapt ==="
"$AAPT" package -v -f -m -x \
    -M "$CORE_RES/AndroidManifest.xml" \
    -S "$CORE_RES/res" \
    -A "$CORE_RES/assets" \
    -J "$OUT/gen" \
    -F "$OUT/framework-res.apk" \
    > "$LOG" 2>&1 || {
        echo "FAILED -- last 100 lines of $LOG:"
        tail -100 "$LOG"
        exit 1
    }

echo "=== output ==="
ls -la "$OUT/framework-res.apk"
find "$OUT/gen" -name "R.java" -o -name "Manifest.java"
echo "=== R.java stats ==="
find "$OUT/gen" -name "R.java" -exec wc -l {} \;
echo "=== apk contents (first 20) ==="
"$AAPT" list "$OUT/framework-res.apk" | head -20
echo "=== apk file count ==="
"$AAPT" list "$OUT/framework-res.apk" | wc -l

# --- sign -----------------------------------------------------------------
#
# SIGNING -- why this is required. PackageManagerService verifies every
# package's JAR signature during the initial scan, including framework-res.apk
# (package "android"). An unsigned apk fails collectCertificates() with
#   Package android has no certificates at entry AndroidManifest.xml; ignoring!
# which drops the android package from the package table and, on this port,
# wedged system_server inside the subsequent resource-scan (2026-08-05). AOSP
# signs framework-res.apk with the platform key via build/tools/signapk; an
# Android v1 signature *is* a standard JAR signature, so jarsigner produces a
# byte-compatible result once told to use SHA1/RSA -- JDK 8 defaults to
# SHA-256, which Eclair's verifier does not accept. Same recipe as
# build_launcher.sh step 5 (Launcher2 is already PLATFORM-signed).
#
# framework-res.apk carries no dex and PMS explicitly skips dexopting it (the
# "Gross hack" in PackageManagerService.java adds it to the no-dexopt set), so
# signing it changes nothing about dalvik-cache/odex validity.
SEC="${ANDROID3DS_ROOT}"/third_party/build_system/target/product/security
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JARSIGNER="$JDK/bin/jarsigner"
KEYSTORE=$OUT/platform.p12
if [ ! -f "$KEYSTORE" ]; then
    echo "=== creating PKCS#12 keystore from the AOSP platform key ==="
    openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
        -out "$OUT/platform.pem" >> "$LOG" 2>&1
    openssl pkcs12 -export -inkey "$OUT/platform.pem" \
        -in "$SEC/platform.x509.pem" \
        -name platform -out "$KEYSTORE" -passout pass:android >> "$LOG" 2>&1
fi
echo "=== signing framework-res.apk with the AOSP platform key ==="
"$JARSIGNER" -keystore "$KEYSTORE" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/framework-res.apk" platform \
    >> "$LOG" 2>&1 || {
        echo "FAILED (jarsigner) -- last 40 lines of $LOG:"
        tail -40 "$LOG"
        exit 1
    }
echo "=== verifying signature ==="
"$JARSIGNER" -verify "$OUT/framework-res.apk" | tail -3

# --- deploy ---------------------------------------------------------------
#
# This script did NOT deploy until 2026-08-04, so the framework-res.apk on the
# SD card was whatever some earlier session had hand-copied. That is a
# particularly nasty thing to leave manual: framework.jar's android/R.java and
# com/android/internal/R.java are generated *here*, so a framework-res.apk that
# is out of step with framework.jar means every resource ID in the system is
# looked up in the wrong table. Deploying from the same script that generates
# the R.java files makes them impossible to separate.
OVERLAY="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay
TARGET="${ANDROID3DS_ROOT}"/third_party/buildroot/output/target
echo "=== deploying framework-res.apk ==="
for d in "$OVERLAY/system/framework" "$TARGET/system/framework"; do
    mkdir -p "$d"
    cp "$OUT/framework-res.apk" "$d/framework-res.apk"
    chmod 644 "$d/framework-res.apk"
done
md5sum "$OUT/framework-res.apk" \
       "$OVERLAY/system/framework/framework-res.apk" \
       "$TARGET/system/framework/framework-res.apk"
echo
echo "REMINDER: android/R.java and com/android/internal/R.java just changed."
echo "  Run build_framework_jar.sh + deploy_framework_jar.sh, then"
echo "  build_services_jar.sh + deploy_services_jar.sh, then"
echo "  build_launcher.sh, then sync_android_to_sdcard.sh."
