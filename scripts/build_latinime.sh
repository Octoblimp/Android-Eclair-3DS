#!/bin/bash
# Build and stage AOSP LatinIME (android-2.0_r1, Google's stock "Android
# keyboard") as the system input method.  Replaces the custom N3DSKeyboard.
#
# Pieces that live elsewhere:
#   - Java/resource patches for the 320x240 screen: third_party/latinime
#     (N3DS_LATINIME_* markers).
#   - The dictionary natives are linked into app_process
#     (build_app_process.sh, N3DS_STATIC_JNI_LIBS) and found by Dalvik's
#     built-in JNI table (dalvik/vm/Native.c); /system/lib/libjni_latinime.so
#     staged here is only a placeholder so PathClassLoader.findLibrary() still
#     resolves the name.
#   - The real English dictionary is compiled from AOSP's en_us_wordlist.xml
#     by make_latinime_dict.py (N3DS_LATINIME_REAL_DICT); upstream Eclair
#     only ever shipped a one-word stub.
#   - SettingsProvider makes it the default (N3DS_DEFAULT_LATINIME).
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
TP="$ROOT/third_party"
SRC="$TP/latinime"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
JAVAC="$JDK/bin/javac"
JARSIGNER="$JDK/bin/jarsigner"
AAPT="$ROOT/build/aapt/aapt"
DX="$ROOT/build/dx/dx"
FWRES="$ROOT/build/framework_res/framework-res.apk"
FW_CLASSES="$ROOT/build/framework_jar/classes.jar"
CORE_CLASSES="$ROOT/build/core/classes.jar"
SEC="$TP/build_system/target/product/security"
OUT="$ROOT/build/latinime"
OVERLAY="$TP/buildroot/board/nintendo3ds/rootfs_overlay"
WIN_ROOT="${ANDROID3DS_WIN}"
# All three /system/app staging trees (see prebake_launcher_odex.sh,
# N3DS_PREBAKE_WSL_TARGET): the gate reads whichever one it runs from.
APP_TREES=(
    "$OVERLAY/system/app"
    "$WIN_ROOT/sdcard/linux/android/system/app"
    "$ROOT/sdcard/linux/android/system/app"
)
LOG="$ROOT/build_latinime.log"
APK=LatinIME.apk

for f in "$AAPT" "$DX" "$FWRES" "$FW_CLASSES" "$CORE_CLASSES" \
         "$SRC/AndroidManifest.xml" "$SRC/dictionaries/en_us_wordlist.xml.gz" \
         "$ROOT/scripts/make_latinime_dict.py" \
         "$SEC/platform.pk8" "$SEC/platform.x509.pem"; do
    test -e "$f" || { echo "build_latinime: missing $f" >&2; exit 1; }
done
# A fresh upstream clone gets the N3DS patches here (idempotent).
python3 "$ROOT/scripts/patch_latinime_n3ds.py" >> "$ROOT/build_latinime.log"
for marker in N3DS_LATINIME_NO_EXTRACT N3DS_LATINIME_NO_CONTACTS; do
    grep -q "$marker" "$SRC/src/com/android/inputmethod/latin/LatinIME.java" \
        || { echo "build_latinime: $marker patch missing" >&2; exit 1; }
done

rm -rf "$OUT"
mkdir -p "$OUT/gen" "$OUT/classes" "$OUT/dex" "$OUT/src"
cp -a "$SRC/AndroidManifest.xml" "$SRC/res" "$SRC/src" "$OUT/src"/
: > "$LOG"

echo '=== 1/6 main.dict from en_us_wordlist.xml (N3DS_LATINIME_REAL_DICT) ==='
python3 "$ROOT/scripts/make_latinime_dict.py" \
    "$SRC/dictionaries/en_us_wordlist.xml.gz" "$OUT/src/res/raw/main.dict" \
    | tee -a "$LOG"
test "$(stat -c %s "$OUT/src/res/raw/main.dict")" -gt 500000

echo '=== 2/6 aapt: LatinIME resources ==='
# -0 .dict: stored, not deflated, so BinaryDictionary's AssetManager open
# (ACCESS_BUFFER) maps it straight out of the APK instead of inflating
# 1.2 MB into the heap -- upstream's LOCAL_AAPT_FLAGS.
"$AAPT" package -f -m -0 .dict -M "$OUT/src/AndroidManifest.xml" \
    -S "$OUT/src/res" -I "$FWRES" -J "$OUT/gen" -F "$OUT/$APK" >> "$LOG" 2>&1

echo '=== 3/6 javac ==='
find "$OUT/src/src" "$OUT/gen" -name '*.java' > "$OUT/sources.txt"
"$JAVAC" -nowarn -encoding UTF-8 -source 6 -target 6 \
    -bootclasspath "$CORE_CLASSES:$FW_CLASSES" \
    -classpath "$FW_CLASSES:$CORE_CLASSES" -d "$OUT/classes" \
    @"$OUT/sources.txt" >> "$LOG" 2>&1

echo '=== 4/6 dx ==='
"$DX" --dex --output="$OUT/dex/classes.dex" "$OUT/classes" >> "$LOG" 2>&1
( cd "$OUT/dex" && "$AAPT" add -f "$OUT/$APK" classes.dex ) >> "$LOG" 2>&1

echo '=== 5/6 platform signature ==='
openssl pkcs8 -inform DER -nocrypt -in "$SEC/platform.pk8" \
    -out "$OUT/platform.pem" >> "$LOG" 2>&1
openssl pkcs12 -export -inkey "$OUT/platform.pem" \
    -in "$SEC/platform.x509.pem" -name platform \
    -out "$OUT/platform.p12" -passout pass:android >> "$LOG" 2>&1
"$JARSIGNER" -keystore "$OUT/platform.p12" -storetype pkcs12 \
    -storepass android -sigalg SHA1withRSA -digestalg SHA1 \
    "$OUT/$APK" platform >> "$LOG" 2>&1
"$JARSIGNER" -J-Djava.security.properties=/dev/null \
    -J-Djdk.jar.disabledAlgorithms= -verify "$OUT/$APK" >> "$LOG" 2>&1

# Self-checks on the artifact before anything is staged.
"$AAPT" list "$OUT/$APK" | grep -qx classes.dex
"$AAPT" dump badging "$OUT/$APK" | grep -qF "package: name='com.android.inputmethod.latin'"
"$AAPT" dump xmltree "$OUT/$APK" AndroidManifest.xml > "$OUT/manifest.txt"
grep -qF 'android.permission.BIND_INPUT_METHOD' "$OUT/manifest.txt"
grep -qF 'android.view.InputMethod' "$OUT/manifest.txt"
if grep -qF 'sharedUserId' "$OUT/manifest.txt"; then
    echo "build_latinime: manifest still declares a sharedUserId (N3DS_LATINIME_OWN_UID)" >&2
    exit 1
fi
unzip -v "$OUT/$APK" res/raw/main.dict | grep -E ' Stored ' > /dev/null \
    || { echo "build_latinime: res/raw/main.dict is compressed" >&2; exit 1; }

echo '=== 6/6 stage ==='
for t in "${APP_TREES[@]}"; do
    mkdir -p "$t"
    cp "$OUT/$APK" "$t/$APK.new"
    chmod 644 "$t/$APK.new"
    mv -f "$t/$APK.new" "$t/$APK"
    # The odex must come from this exact APK: prebake_latinime_odex.sh.
    rm -f "$t/LatinIME.odex"
done
mkdir -p "$OVERLAY/system/lib"
printf '%s\n' \
    'N3DS_STATIC_JNI_LIBS placeholder: libjni_latinime is linked into' \
    '/system/bin/app_process and found by dalvik/vm/Native.c; this file only' \
    'lets PathClassLoader.findLibrary() resolve the name.' \
    > "$OVERLAY/system/lib/libjni_latinime.so"
chmod 644 "$OVERLAY/system/lib/libjni_latinime.so"
echo '=== build_latinime: ALL OK ==='
ls -la "${APP_TREES[@]/%//$APK}" "$OVERLAY/system/lib/libjni_latinime.so"
