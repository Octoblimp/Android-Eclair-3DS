#!/bin/bash
# #327: America/Chicago must resolve from the shipped zoneinfo database, and
# Eclair's SntpClient must produce the real time (it used to double the
# clock offset). Runs core.jar/framework.jar under qemu-arm against the staged
# SD /system, so run it after sync_android_to_sdcard.sh.
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
OUT="$ROOT/build/timezone_smoke"
FAKEROOT="$OUT/fakeroot"

for f in "$SD/system/usr/share/zoneinfo/zoneinfo.dat" \
         "$SD/system/usr/share/zoneinfo/zoneinfo.idx"; do
    test -s "$f" || { echo "FAIL: $f is not staged" >&2; exit 1; }
done

bash "$PROJECT/scripts/build_app_process_qemu.sh"
rm -rf "$OUT"
mkdir -p "$OUT/classes" "$FAKEROOT/system/app" "$FAKEROOT/data"

"$JDK/bin/javac" -nowarn -source 6 -target 6 \
    -bootclasspath "$CORE:$FRAMEWORK" -classpath "$FRAMEWORK:$CORE" \
    -d "$OUT/classes" "$PROJECT/content/TimeZoneSmoke.java"
"$DX" --dex --output="$OUT/timezone-smoke.jar" "$OUT/classes"
cp -a "$SD/system/." "$FAKEROOT/system/"
cp -a "$SD/data/." "$FAKEROOT/data/"
cp "$OUT/timezone-smoke.jar" "$FAKEROOT/system/app/TimeZoneSmoke.apk"

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
: > /system/app/TimeZoneSmoke.odex
exec 3< /system/app/TimeZoneSmoke.apk
exec 4<> /system/app/TimeZoneSmoke.odex
exec "$3" "$4" --zip 3 4 /system/app/TimeZoneSmoke.apk ""
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$DEXOPT_QEMU"

LOG="$OUT/run.log"
# bionic's resolver needs net.dns1, which no property service sets under
# qemu-user, so resolve the NTP server here and hand the guest an address.
NTP_SERVER="$(getent ahostsv4 pool.ntp.org 2>/dev/null | awk 'NR==1 {print $1}' || true)"
NTP_SERVER="${NTP_SERVER:-pool.ntp.org}"
echo "NTP server for the guest: $NTP_SERVER"
set +e
a3ds_sudo unshare --mount -- bash -c '
set -e
mkdir -p /system /data
mount --bind "$1" /system
mount --bind "$2" /data
export ANDROID_ROOT=/system ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
export CLASSPATH=/system/app/TimeZoneSmoke.apk
exec timeout 60s "$3" "$4" /system/bin android3ds.TimeZoneSmoke "$5"
' -- "$FAKEROOT/system" "$FAKEROOT/data" "$QEMU" "$APP_PROCESS" "$NTP_SERVER" > "$LOG" 2>&1
status=$?
set -e
cat "$LOG"
grep -q 'PASS: zoneinfo America/Chicago + SNTP offset' "$LOG" || {
    echo "FAIL: time zone smoke did not complete (status=$status)" >&2
    exit 1
}
