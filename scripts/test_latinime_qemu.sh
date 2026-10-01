#!/bin/bash
# Runtime check for the LatinIME dictionary natives under qemu-user.
#
# #321 passed every static check and still crashed on hardware: Dalvik's
# java.library.path came from an LD_LIBRARY_PATH nothing exported, so
# System.loadLibrary("jni_latinime") never reached Native.c's built-in JNI
# table (N3DS_STATIC_JNI_LIBS).  This loads BinaryDictionary through an APK
# PathClassLoader with LD_LIBRARY_PATH unset, as the IME process does, then
# opens the real main.dict and asks it for suggestions.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
PROJECT="${ANDROID3DS_WIN}"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
QEMU="$ROOT/toolchain/qemu/qemu-arm-static"
APP_PROCESS="$ROOT/build/app_process_qemu/app_process_qemu"
DEXOPT_QEMU="$ROOT/build/dexopt/dexopt_qemu"
DX="$ROOT/build/dx/dx"
CORE="$ROOT/build/core/classes.jar"
FRAMEWORK="$ROOT/build/framework_jar/classes.jar"
SD="$PROJECT/sdcard/linux/android"
OVERLAY="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay"
OUT="$ROOT/build/latinime_smoke"
FAKEROOT="$OUT/fakeroot"

if [ "${SKIP_APP_PROCESS_BUILD:-0}" != 1 ]; then
    bash "$PROJECT/scripts/build_app_process_qemu.sh"
fi
for o in LatinImeSmoke.odex LatinIME.odex; do
    if [ -e "$FAKEROOT/system/app/$o" ]; then
        a3ds_sudo chown "$(id -u):$(id -g)" "$FAKEROOT/system/app/$o"
    fi
done
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$FAKEROOT/system/app" "$FAKEROOT/data"

"$JDK/bin/javac" -nowarn -source 6 -target 6 \
    -bootclasspath "$CORE:$FRAMEWORK" -classpath "$FRAMEWORK:$CORE" \
    -d "$OUT/classes" "$PROJECT/content/LatinImeSmoke.java"
"$DX" --dex --output="$OUT/latinime-smoke.jar" "$OUT/classes"
cp -a "$SD/system/." "$FAKEROOT/system/"
cp -a "$SD/data/." "$FAKEROOT/data/"
cp "$OUT/latinime-smoke.jar" "$FAKEROOT/system/app/LatinImeSmoke.apk"
# The APK and the findLibrary() placeholder come from the overlay, which is
# what sync_android_to_sdcard.sh ships, not whatever the card copy holds.
cp "$OVERLAY/system/app/LatinIME.apk" "$FAKEROOT/system/app/LatinIME.apk"
mkdir -p "$FAKEROOT/system/lib"
cp "$OVERLAY/system/lib/libjni_latinime.so" "$FAKEROOT/system/lib/libjni_latinime.so"
rm -f "$FAKEROOT/system/app/LatinIME.odex"

if [ ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]; then
    REGFILE="$(mktemp)"
    printf ':qemu-arm:M::\\x7fELF\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28\\x00:\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:%s:F\n' "$QEMU" > "$REGFILE"
    a3ds_sudo bash -c "cat '$REGFILE' > /proc/sys/fs/binfmt_misc/register"
    rm -f "$REGFILE"
fi

for apk in LatinImeSmoke LatinIME; do
a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
rm -f /system/app/$5.odex
: > /system/app/$5.odex
exec 3< /system/app/$5.apk
exec 4<> /system/app/$5.odex
exec "$3" "$4" --zip 3 4 /system/app/$5.apk ""
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$DEXOPT_QEMU" "$apk"
done

LOG="$OUT/run.log"
set +e
a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
unset LD_LIBRARY_PATH
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
export CLASSPATH="$3"
exec timeout 60s "$4" "$5" /system/bin android3ds.LatinImeSmoke
' -- "$FAKEROOT/system" "$FAKEROOT/data" /system/app/LatinImeSmoke.apk \
    "$QEMU" "$APP_PROCESS" > "$LOG" 2>&1
status=$?
set -e
cat "$LOG"
grep -q 'PASS: latinime native dictionary' "$LOG" || {
    echo "FAIL: LatinIME qemu smoke did not complete (status=$status)" >&2
    exit 1
}
