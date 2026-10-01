#!/bin/bash
# #328: the Firmware-version easter egg's drawing code, run for real under
# qemu-arm. BugdroidSmoke renders the bugdroid with PlatLogoActivity's own
# drawFrame() at the bottom screen's size and checks the pixels at rest,
# mid-blink, mid-hop and after landing. Run after build_settings_app.sh +
# sync_android_to_sdcard.sh.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/a3ds_env.sh"

ROOT="$ANDROID3DS_ROOT"
JDK=/usr/lib/jvm/java-8-openjdk-amd64
QEMU="$ROOT/toolchain/qemu/qemu-arm-static"
APP_PROCESS="$ROOT/build/app_process_qemu/app_process_qemu"
DEXOPT_QEMU="$ROOT/build/dexopt/dexopt_qemu"
DX="$ROOT/build/dx/dx"
CORE="$ROOT/build/core/classes.jar"
FRAMEWORK="$ROOT/build/framework_jar/classes.jar"
SD="$ANDROID3DS_WIN/sdcard/linux/android"
OUT="$ROOT/build/bugdroid_smoke"
FAKEROOT="$OUT/fakeroot"

bash "$(dirname "${BASH_SOURCE[0]}")/build_app_process_qemu.sh"
# dexopt and the frame dump run inside the root-owned mount namespace
# below; reclaim what they wrote so repeated smoke runs stay deterministic.
if [ -e "$OUT" ]; then
    a3ds_sudo chown -R "$(id -u):$(id -g)" "$OUT"
fi
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$FAKEROOT/system/app" "$FAKEROOT/data"

"$JDK/bin/javac" -nowarn -source 6 -target 6 \
    -bootclasspath "$CORE:$FRAMEWORK" -classpath "$FRAMEWORK:$CORE" \
    -d "$OUT/classes" "$ROOT/content/BugdroidSmoke.java" \
    "$ROOT/third_party/settings/src/com/android/settings/PlatLogoActivity.java"
"$DX" --dex --output="$OUT/bugdroid-smoke.jar" "$OUT/classes"
cp -a "$SD/system/." "$FAKEROOT/system/"
cp -a "$SD/data/." "$FAKEROOT/data/"
cp "$OUT/bugdroid-smoke.jar" "$FAKEROOT/system/app/BugdroidSmoke.apk"

if [ ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]; then
    REGFILE="$(mktemp)"
    printf ':qemu-arm:M::\\x7fELF\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28\\x00:\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:%s:F\n' "$QEMU" > "$REGFILE"
    a3ds_sudo bash -c "cat '$REGFILE' > /proc/sys/fs/binfmt_misc/register"
    rm -f "$REGFILE"
fi

a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
rm -f /system/app/BugdroidSmoke.odex
: > /system/app/BugdroidSmoke.odex
exec 3< /system/app/BugdroidSmoke.apk
exec 4<> /system/app/BugdroidSmoke.odex
exec "$3" "$4" --zip 3 4 /system/app/BugdroidSmoke.apk ""
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$DEXOPT_QEMU"

LOG="$OUT/run.log"
set +e
a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
export CLASSPATH="$3"
mkdir -p /data/bugdroid_frames
exec timeout 30s "$4" "$5" /system/bin android3ds.BugdroidSmoke /data/bugdroid_frames
' -- "$FAKEROOT/system" "$FAKEROOT/data" /system/app/BugdroidSmoke.apk \
    "$QEMU" "$APP_PROCESS" > "$LOG" 2>&1
status=$?
set -e
cat "$LOG"
# The three frames it checked, as PNGs, for a look by eye.
a3ds_sudo chown -R "$(id -u):$(id -g)" "$OUT"
mkdir -p "$OUT/frames"
cp "$FAKEROOT"/data/bugdroid_frames/*.png "$OUT/frames/" 2>/dev/null || true
grep -q 'PASS: bugdroid 320x240' "$LOG" || {
    echo "FAIL: the bugdroid did not render correctly (status=$status)" >&2
    exit 1
}
