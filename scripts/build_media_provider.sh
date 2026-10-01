#!/bin/bash
# Stock Eclair MediaProvider: the "media" content provider (MediaStore) that
# the stock Camera app inserts photos into and its gallery reads back. Without
# it ContentResolver.insert(Images.Media.EXTERNAL_CONTENT_URI) throws
# IllegalArgumentException ("Unknown URL") on every shot.
#
# The source at third_party/MediaProvider is pristine upstream (android-2.0_r1,
# see ANDROID3DS_PROVENANCE.md there). Every change is made to a disposable
# copy under build/, the way build_contacts_provider.sh does it.
#
# N3DS_NO_MEDIA_SCANNER: there is no native media scanner in this image (no
# libmedia_jni.so, no opencore), and app_process is a static binary, so the
# class initialiser of android.media.MediaScanner -- System.loadLibrary(
# "media_jni") -- can only throw. That is an Error, not an Exception: nothing
# in the scanner paths catches it, it kills android.process.media, and
# ActivityManager then kills every client holding a reference to a provider in
# that process -- the Camera app. So, in the build copy:
#   - MediaScannerReceiver is removed from the manifest. Upstream it scans on
#     BOOT_COMPLETED and MEDIA_MOUNTED, and MountService on this port
#     broadcasts MEDIA_MOUNTED on every boot (there is no vold; see
#     publishExternalStorageState there).
#   - MediaScannerService is removed too. Nothing on this image binds
#     IMediaScannerService (no MediaScannerConnection user in the framework,
#     the Camera app or any shipped app), and left exported it would be one
#     bindService() away from the same crash.
#   - getCompressedAlbumArt() catches Throwable around `new MediaScanner()`,
#     so album art falls through to the folder-art search instead of killing
#     the thumbnail thread.
# The two scanner classes are still compiled; they are just never reachable.
#
# N3DS_MEDIA_SHARED_UID_SIGNING: android.media is a shared user ID, and the
# stock Camera app declares it too. PackageManagerService drops any package
# whose certificate does not match the shared user's ("has no signatures that
# match those in shared user android.media; ignoring!"), so whichever of the
# two it scanned second would silently disappear. Upstream signs both with
# the "media" key; build_camera_app.sh signs Camera with "platform". This
# script signs with whichever of those two keys Camera.apk actually carries,
# and fails if the result does not match it.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail
ROOT="${ANDROID3DS_ROOT}"
SRC="$ROOT/third_party/MediaProvider"
OUT="$ROOT/build/media_provider"
OVERLAY="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
AAPT="$ROOT/build/aapt/aapt"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW="$ROOT/build/framework_jar/classes.jar"
CORE="$ROOT/build/core/classes.jar"
SEC="$ROOT/third_party/build_system/target/product/security"
LOG="$ROOT/build_media_provider.log"
CAMERA_APK="$OVERLAY/system/app/Camera.apk"
for file in "$SRC/AndroidManifest.xml" "$SRC/src/com/android/providers/media/MediaProvider.java" \
        "$FWRES" "$FW" "$CORE" "$AAPT" "$DX" \
        "$SEC/platform.pk8" "$SEC/platform.x509.pem" "$SEC/media.pk8" "$SEC/media.x509.pem"; do
    test -s "$file" || { echo "Missing provider build input: $file" >&2; exit 1; }
done

# SHA-256 fingerprint of the first certificate in an APK's signature block.
apk_cert() {
    local listing block
    listing="$(unzip -Z1 "$1")"
    block="$(printf '%s\n' "$listing" | grep -E '^META-INF/[^/]+[.](RSA|DSA|EC)$' | awk 'NR == 1')"
    test -n "$block" || { echo "no signature block in $1" >&2; return 1; }
    unzip -p "$1" "$block" | openssl pkcs7 -inform DER -print_certs \
        | openssl x509 -noout -fingerprint -sha256
}
key_cert() {
    openssl x509 -in "$SEC/$1.x509.pem" -noout -fingerprint -sha256
}

KEY=platform
if [ -s "$CAMERA_APK" ]; then
    CAMERA_CERT="$(apk_cert "$CAMERA_APK")"
    if [ "$CAMERA_CERT" = "$(key_cert platform)" ]; then
        KEY=platform
    elif [ "$CAMERA_CERT" = "$(key_cert media)" ]; then
        KEY=media
    else
        echo "build_media_provider: Camera.apk is signed by neither the platform nor the" >&2
        echo "media key ($CAMERA_CERT); cannot share android.media with it" >&2
        exit 1
    fi
else
    CAMERA_CERT=
    echo "build_media_provider: WARNING: $CAMERA_APK missing; signing with platform," >&2
    echo "the key build_camera_app.sh uses. Re-run this after building Camera." >&2
fi
echo "=== android.media shared user: signing with the $KEY key ==="

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex"
mkdir -p "$OUT/source"
cp -a "$SRC/src" "$SRC/res" "$SRC/AndroidManifest.xml" "$OUT/source/"
SRC="$OUT/source"
# N3DS_NO_MEDIA_SCANNER (see the top of this file). Each edit must match
# exactly once, or the build stops: a silent no-op here is a device that
# crashes android.process.media on boot.
python3 - "$SRC" <<'PY'
import re
import sys

src = sys.argv[1]

def patch(path, pattern, replacement, flags=0):
    with open(path) as f:
        text = f.read()
    text, count = re.subn(pattern, replacement, text, flags=flags)
    assert count == 1, "%s: expected exactly one match for %r, got %d" % (
        path, pattern, count)
    with open(path, "w") as f:
        f.write(text)

manifest = src + "/AndroidManifest.xml"
patch(manifest, r'\n[ \t]*<receiver android:name="MediaScannerReceiver">.*?</receiver>[ \t]*\n',
      "\n", re.S)
patch(manifest, r'\n[ \t]*<service android:name="MediaScannerService"[^>]*>.*?</service>[ \t]*\n',
      "\n", re.S)

provider = src + "/src/com/android/providers/media/MediaProvider.java"
patch(provider,
      r'( +)MediaScanner scanner = new MediaScanner\(context\);\n'
      r' +compressed = scanner\.extractAlbumArt\(pfd\.getFileDescriptor\(\)\);\n',
      r'\1try {\n'
      r'\1    MediaScanner scanner = new MediaScanner(context);\n'
      r'\1    compressed = scanner.extractAlbumArt(pfd.getFileDescriptor());\n'
      r'\1} catch (Throwable t) {\n'
      r'\1    // N3DS_NO_MEDIA_SCANNER: no libmedia_jni, so this is an\n'
      r'\1    // UnsatisfiedLinkError. Fall through to the folder-art search.\n'
      r'\1    compressed = null;\n'
      r'\1}\n')
print("patched: manifest (receiver, service), MediaProvider.getCompressedAlbumArt")
PY
: > "$LOG"
"$AAPT" package -f -m -M "$SRC/AndroidManifest.xml" -S "$SRC/res" \
    -I "$FWRES" -J "$OUT/gen" -F "$OUT/MediaProvider.apk" >> "$LOG" 2>&1
find "$SRC/src" "$OUT/gen" -name '*.java' -type f > "$OUT/sources.txt"
"$JDK/bin/javac" -J-Xmx512m -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE:$FW" -classpath "$FW:$CORE" \
    -d "$OUT/classes" @"$OUT/sources.txt" >> "$LOG" 2>&1
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1
(cd "$OUT/dex" && "$AAPT" add -f "$OUT/MediaProvider.apk" classes.dex) >> "$LOG" 2>&1
openssl pkcs8 -inform DER -nocrypt -in "$SEC/$KEY.pk8" -out "$OUT/$KEY.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/$KEY.pem" -in "$SEC/$KEY.x509.pem" \
    -name "$KEY" -out "$OUT/$KEY.p12" -passout pass:android >> "$LOG" 2>&1
printf '%s\n' 'jdk.jar.disabledAlgorithms=' > "$OUT/jarsigner.security"
"$JDK/bin/jarsigner" -keystore "$OUT/$KEY.p12" -storetype pkcs12 -storepass android \
    -sigalg SHA1withRSA -digestalg SHA1 "$OUT/MediaProvider.apk" "$KEY" >> "$LOG" 2>&1
"$JDK/bin/jarsigner" -J-Djava.security.properties="$OUT/jarsigner.security" \
    -verify -verbose -certs "$OUT/MediaProvider.apk" >> "$LOG" 2>&1
tail -40 "$LOG" | grep -F 'jar verified.' >/dev/null
"$AAPT" list "$OUT/MediaProvider.apk" | grep -qx classes.dex
"$AAPT" dump xmltree "$OUT/MediaProvider.apk" AndroidManifest.xml > "$OUT/manifest.txt"
grep -F "android:authorities" "$OUT/manifest.txt" | grep -F '="media"' >/dev/null
grep -F "android:sharedUserId" "$OUT/manifest.txt" | grep -F '="android.media"' >/dev/null
for gone in MediaScannerReceiver MediaScannerService; do
    if grep -F "$gone" "$OUT/manifest.txt" >/dev/null; then
        echo "build_media_provider: $gone is still declared in the manifest" >&2
        exit 1
    fi
done
PROVIDER_CERT="$(apk_cert "$OUT/MediaProvider.apk")"
test "$PROVIDER_CERT" = "$(key_cert "$KEY")"
if [ -n "$CAMERA_CERT" ] && [ "$PROVIDER_CERT" != "$CAMERA_CERT" ]; then
    echo "build_media_provider: MediaProvider and Camera would not share android.media" >&2
    exit 1
fi
mkdir -p "$OVERLAY/system/app"
cp "$OUT/MediaProvider.apk" "$OVERLAY/system/app/MediaProvider.apk"
chmod 644 "$OVERLAY/system/app/MediaProvider.apk"
rm -f "$OVERLAY/system/app/MediaProvider.odex"
sha256sum "$OUT/MediaProvider.apk"
echo '=== build_media_provider: ALL OK ==='
