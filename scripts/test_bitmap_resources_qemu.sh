#!/bin/bash
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
OUT="$ROOT/build/bitmap_resource_smoke"
FAKEROOT="$OUT/fakeroot"

bash "$PROJECT/scripts/build_app_process_qemu.sh"
# dexopt runs inside the root-owned mount namespace below; reclaim its one
# side-by-side output so repeated smoke runs remain deterministic.
if [ -e "$OUT/fakeroot/system/app/BitmapSmoke.odex" ]; then
    a3ds_sudo chown "$(id -u):$(id -g)" \
        "$OUT/fakeroot/system/app/BitmapSmoke.odex"
fi
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$FAKEROOT/system/app" "$FAKEROOT/data"

"$JDK/bin/javac" -nowarn -source 6 -target 6 \
    -bootclasspath "$CORE:$FRAMEWORK" -classpath "$FRAMEWORK:$CORE" \
    -d "$OUT/classes" "$PROJECT/content/BitmapResourceSmoke.java"
"$DX" --dex --output="$OUT/bitmap-smoke.jar" "$OUT/classes"
cp -a "$SD/system/." "$FAKEROOT/system/"
cp -a "$SD/data/." "$FAKEROOT/data/"
cp "$OUT/bitmap-smoke.jar" "$FAKEROOT/system/app/BitmapSmoke.apk"
unzip -j "$SD/system/framework/framework-res.apk" \
    res/drawable-mdpi/sym_def_app_icon.png -d "$OUT" >/dev/null

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
rm -f /system/app/BitmapSmoke.odex
: > /system/app/BitmapSmoke.odex
exec 3< /system/app/BitmapSmoke.apk
exec 4<> /system/app/BitmapSmoke.odex
exec "$3" "$4" --zip 3 4 /system/app/BitmapSmoke.apk ""
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
exec timeout 30s "$4" "$5" /system/bin android3ds.BitmapResourceSmoke "$6"
' -- "$FAKEROOT/system" "$FAKEROOT/data" /system/app/BitmapSmoke.apk \
    "$QEMU" "$APP_PROCESS" "$OUT/sym_def_app_icon.png" > "$LOG" 2>&1
status=$?
set -e
cat "$LOG"
grep -q 'PASS: bitmap decode/width/height/scale' "$LOG" || {
    echo "FAIL: bitmap smoke did not complete (status=$status)" >&2
    exit 1
}
