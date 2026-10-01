#!/bin/bash
# Build AOSP Eclair's real home screen -- packages/apps/Launcher2 at
# android-2.0_r1 -- into a signed /system/app/Launcher2.apk.
#
# This is the last missing piece for a home screen: everything under it is
# already built (framework.jar, framework-res.apk, services.jar with
# PackageManagerService/ActivityManagerService, the compositor). What was
# missing is any package at all declaring
#   <category android:name="android.intent.category.HOME" />
# so ActivityManagerService had nothing to resolve when it tried to start the
# home activity. /system/app did not even exist on the card.
#
# There is no AOSP build system here, so this reimplements what BUILD_PACKAGE
# does, in five steps: aapt (resources + R.java), javac, dx, aapt add, sign.
#
# SIGNING -- why jarsigner and not signapk.
# PackageManagerService verifies every package's JAR signature, including ones
# in /system/app; an unsigned APK fails with INSTALL_PARSE_FAILED_NO_CERTIFICATES
# and is silently skipped, which would look exactly like "the launcher isn't
# there". AOSP signs with build/tools/signapk, a host Java tool that needs
# BouncyCastle. An Android v1 signature *is* a standard JAR signature, so the
# JDK's own jarsigner produces a byte-compatible result once it is told to use
# SHA1/RSA (JDK 8 defaults to SHA-256, which Eclair's verifier does not accept).
# The key is AOSP's own platform testkey, converted from the PKCS#8 DER +
# X.509 PEM pair that build/target/product/security ships into a PKCS#12
# keystore -- LOCAL_CERTIFICATE := platform in Launcher2's Android.mk.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

TP="${ANDROID3DS_ROOT}"/third_party
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JAR="$JDK/bin/jar"
KEYTOOL="$JDK/bin/keytool"
JARSIGNER="$JDK/bin/jarsigner"

AAPT="${ANDROID3DS_ROOT}"/build/aapt/aapt
DX="${ANDROID3DS_ROOT}"/build/dx/dx
SRC=$TP/launcher2
SEC=$TP/build_system/target/product/security
FWRES="${ANDROID3DS_ROOT}"/build/framework_res/framework-res.apk
FW_CLASSES="${ANDROID3DS_ROOT}"/build/framework_jar/classes.jar
CORE_CLASSES="${ANDROID3DS_ROOT}"/build/core/classes.jar

OUT="${ANDROID3DS_ROOT}"/build/launcher2
LOG="${ANDROID3DS_ROOT}"/build_launcher.log
# The rootfs overlay, not output/target: the overlay is the source of truth
# that scripts/sync_android_to_sdcard.sh copies into output/target and then on
# to the card (see that script's "refreshing output/target" step).
OVERLAY=$TP/buildroot/board/nintendo3ds/rootfs_overlay
TARGET=$OVERLAY/system/app

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$SRC/AndroidManifest.xml" "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    [ -e "$f" ] || { echo "build_launcher: missing prerequisite $f" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
: > "$LOG"

# --- 1. Resources + R.java -------------------------------------------------
#
# -I framework-res.apk: unlike core/res (which *defines* the android package),
# an app *consumes* it, so aapt needs the framework's resource table to resolve
# every @android:... and android:* attribute reference.
echo "=== 1/5 aapt: compiling resources ==="
"$AAPT" package -f -m \
    -M "$SRC/AndroidManifest.xml" \
    -S "$SRC/res" \
    -I "$FWRES" \
    -J "$OUT/gen" \
    -F "$OUT/Launcher2.apk" \
    >> "$LOG" 2>&1 || { echo "FAILED (aapt) -- last 60 lines:"; tail -60 "$LOG"; exit 1; }
find "$OUT/gen" -name '*.java' | sed "s|^|  gen: |"

# --- 2. javac --------------------------------------------------------------
#
# Compiled against the *framework's own* classes, not an SDK android.jar:
# Launcher2 uses @hide APIs (LiveFolders, the internal WallpaperService glue)
# that no public SDK jar exposes. -source/-target 6 for the same reason
# build_core_jar.sh and build_framework_jar.sh use it: dx only accepts class
# file major version <= 50, and JDK 8 is the last JVM that will emit it.
echo "=== 2/5 javac ==="
find "$SRC/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
echo "  $(wc -l < "$OUT/sources.txt") java files"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" \
    -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1 \
    || { echo "FAILED (javac) -- last 60 lines:"; tail -60 "$LOG"; exit 1; }

# --- 3. dx -----------------------------------------------------------------
echo "=== 3/5 dx ==="
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" \
    >> "$LOG" 2>&1 || { echo "FAILED (dx) -- last 60 lines:"; tail -60 "$LOG"; exit 1; }
ls -la "$OUT/dex/classes.dex"

# --- 4. Put classes.dex in the apk ----------------------------------------
#
# Run from $OUT/dex so the zip entry is named "classes.dex" at the archive
# root. aapt add stores the path it is given verbatim; a nested path here
# means Dalvik never finds the dex and the package fails to load with no
# obvious error.
echo "=== 4/5 aapt add classes.dex ==="
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/Launcher2.apk" classes.dex ) \
    >> "$LOG" 2>&1 || { echo "FAILED (aapt add) -- last 40 lines:"; tail -40 "$LOG"; exit 1; }

# --- 5. Sign ---------------------------------------------------------------
echo "=== 5/5 signing with the AOSP platform key ==="
# platform.pk8 is a DER-encoded PKCS#8 private key (not PEM). Convert the
# key+cert pair into a PKCS#12 keystore jarsigner can read.
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" -in "$SEC/platform.x509.pem" \
    -name platform -out "$OUT/platform.p12" -passout pass:android \
    >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/Launcher2.apk" platform \
    >> "$LOG" 2>&1 || { echo "FAILED (jarsigner) -- last 40 lines:"; tail -40 "$LOG"; exit 1; }

echo "=== verifying signature ==="
"$JARSIGNER" -verify "$OUT/Launcher2.apk" | tail -3

# --- /system/etc/permissions ----------------------------------------------
#
# PackageManagerService.readPermissions() reads every .xml in
# /system/etc/permissions at startup. That directory has never existed on this
# port, so PMS logged "No directory /system/etc/permissions, skipping" and
# carried on with an empty permission->gid table: android.permission.INTERNET
# never mapped to the "inet" gid, WRITE_EXTERNAL_STORAGE never mapped to
# "sdcard_rw", and the <library> declarations (android.test.runner etc) were
# absent. Nothing had noticed because nothing had ever installed a package.
#
# platform.xml starts from AOSP's own file, installed by
# frameworks/base/data/etc/Android.mk on every real build.  Strip the two
# Bluetooth permission-to-GID mappings and the shell grant: the 3DS has no
# Bluetooth controller, the kernel BT stack is disabled, and advertising
# net_bt/net_bt_admin groups would preserve a capability that cannot exist.
# The android.hardware.* feature files next to it are deliberately NOT
# installed: they advertise camera/telephony/proximity hardware to
# PackageManager.hasSystemFeature(), and declaring hardware this device does
# not expose to userspace yet would be a lie the framework acts on.
echo "=== installing /system/etc/permissions/platform.xml ==="
mkdir -p "$OVERLAY/system/etc/permissions"
cp "$TP/frameworks/base/data/etc/platform.xml" \
   "$OVERLAY/system/etc/permissions/platform.xml"
sed -i \
    -e '/<permission name="android.permission.BLUETOOTH_ADMIN"/,/<\/permission>/d' \
    -e '/<permission name="android.permission.BLUETOOTH"/,/<\/permission>/d' \
    -e '/<assign-permission name="android.permission.BLUETOOTH"/d' \
    "$OVERLAY/system/etc/permissions/platform.xml"
if grep -q 'BLUETOOTH' "$OVERLAY/system/etc/permissions/platform.xml"; then
    echo "FATAL: Bluetooth permission mapping survived platform.xml filtering" >&2
    exit 1
fi
chmod 644 "$OVERLAY/system/etc/permissions/platform.xml"

# --- deploy ----------------------------------------------------------------
mkdir -p "$TARGET"
cp "$OUT/Launcher2.apk" "$TARGET/Launcher2.apk"
chmod 644 "$TARGET/Launcher2.apk"

echo "=== done ==="
ls -la "$TARGET/Launcher2.apk"
echo "--- HOME category present in the built manifest? ---"
"$AAPT" dump xmltree "$OUT/Launcher2.apk" AndroidManifest.xml \
    | grep -A2 -i "category" | grep -i "HOME" || echo "  WARNING: no HOME category found"
echo "--- classes.dex present? ---"
"$AAPT" list "$OUT/Launcher2.apk" | grep -x "classes.dex" || echo "  WARNING: classes.dex missing"
