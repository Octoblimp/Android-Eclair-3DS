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
OVERLAY="$ROOT/third_party/buildroot/board/nintendo3ds/rootfs_overlay"
OUT="$ROOT/build/key_input_smoke"
FAKEROOT="$OUT/fakeroot"

bash "$PROJECT/scripts/build_app_process_qemu.sh"
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$FAKEROOT/system/app" "$FAKEROOT/data"

"$JDK/bin/javac" -nowarn -source 6 -target 6 \
    -bootclasspath "$CORE:$FRAMEWORK" -classpath "$FRAMEWORK:$CORE" \
    -d "$OUT/classes" "$PROJECT/content/KeyCharacterMapSmoke.java"
"$DX" --dex --output="$OUT/key-input-smoke.jar" "$OUT/classes"
cp -a "$SD/system/." "$FAKEROOT/system/"
cp -a "$SD/data/." "$FAKEROOT/data/"
mkdir -p "$FAKEROOT/system/usr/keychars"
cp "$OVERLAY/system/usr/keychars/qwerty.kcm.bin" \
    "$FAKEROOT/system/usr/keychars/qwerty.kcm.bin"
cp "$OUT/key-input-smoke.jar" "$FAKEROOT/system/app/KeyInputSmoke.apk"

if [ ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]; then
    REGFILE="$(mktemp)"
    printf ':qemu-arm:M::\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x28\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:%s:F\n' "$QEMU" > "$REGFILE"
    a3ds_sudo bash -c "cat '$REGFILE' > /proc/sys/fs/binfmt_misc/register"
    rm -f "$REGFILE"
fi

a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
export ANDROID_ROOT=/system ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
: > /system/app/KeyInputSmoke.odex
exec 3< /system/app/KeyInputSmoke.apk
exec 4<> /system/app/KeyInputSmoke.odex
exec "$3" "$4" --zip 3 4 /system/app/KeyInputSmoke.apk ""
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$DEXOPT_QEMU"

LOG="$OUT/run.log"
set +e
a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
export ANDROID_ROOT=/system ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
export CLASSPATH=/system/app/KeyInputSmoke.apk
exec timeout 30s "$3" "$4" /system/bin android3ds.KeyCharacterMapSmoke
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$APP_PROCESS" > "$LOG" 2>&1
status=$?
set -e
cat "$LOG"
grep -q 'PASS: KeyCharacterMap JNI/native map x/X' "$LOG" || {
    echo "FAIL: key-input smoke did not complete (status=$status)" >&2
    exit 1
}
