#!/bin/bash
# Runtime render check for the WebKit engine under qemu-user.
#
# #321 and #322 showed real pages as blank on hardware while every static
# check passed.  This runs content/WebKitRenderSmoke.java in app_process_qemu
# (WebKit is statically linked into it, exactly as on the device): a WebView
# loads a small page with no network, WebCore lays it out and records it, and
# the test rasterises both capturePicture() and WebView.draw() and checks
# for the page's red box, green background and black text.
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
OUT="$ROOT/build/webkit_render_smoke"
FAKEROOT="$OUT/fakeroot"
APK=WebKitRenderSmoke

if [ "${SKIP_APP_PROCESS_BUILD:-0}" != 1 ]; then
    bash "$PROJECT/scripts/build_app_process_qemu.sh"
fi
if [ -d "$OUT" ]; then
    a3ds_sudo chown -R "$(id -u):$(id -g)" "$OUT"
fi
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$FAKEROOT/system/app" "$FAKEROOT/data/webkitsmoke"

"$JDK/bin/javac" -nowarn -source 6 -target 6 \
    -bootclasspath "$CORE:$FRAMEWORK" -classpath "$FRAMEWORK:$CORE" \
    -d "$OUT/classes" "$PROJECT/content/WebKitRenderSmoke.java"
"$DX" --dex --output="$OUT/webkit-render-smoke.jar" "$OUT/classes"
cp -a "$SD/system/." "$FAKEROOT/system/"
cp -a "$SD/data/." "$FAKEROOT/data/"
cp "$OUT/webkit-render-smoke.jar" "$FAKEROOT/system/app/$APK.apk"

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
rm -f /system/app/$5.odex
: > /system/app/$5.odex
exec 3< /system/app/$5.apk
exec 4<> /system/app/$5.odex
exec "$3" "$4" --zip 3 4 /system/app/$5.apk ""
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$DEXOPT_QEMU" "$APK"

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
exec timeout 240s "$4" "$5" /system/bin android3ds.WebKitRenderSmoke
' -- "$FAKEROOT/system" "$FAKEROOT/data" /system/app/$APK.apk \
    "$QEMU" "$APP_PROCESS" > "$LOG" 2>&1
status=$?
set -e
cat "$LOG"
# The rasterised passes, for a human to look at.
a3ds_sudo chown -R "$(id -u):$(id -g)" "$FAKEROOT/data/webkitsmoke" 2>/dev/null || true
cp -f "$FAKEROOT"/data/webkitsmoke/*.png "$OUT/" 2>/dev/null || true
ls "$OUT"/*.png 2>/dev/null || true
grep -q 'PASS: webkit render' "$LOG" || {
    echo "FAIL: WebKit qemu render smoke did not pass (status=$status)" >&2
    exit 1
}
