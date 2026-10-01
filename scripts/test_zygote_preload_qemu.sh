#!/bin/bash
# Exercise the complete ARM zygote class/resource preload on the host.
#
# This is deliberately stricter than dexpreopt.  dexpreopt proves that each
# bootclasspath jar is structurally usable; this launches the real ARM
# app_process and loads every entry from framework.jar's preloaded-classes.
# Any static initializer that calls an omitted JNI method therefore fails here
# instead of consuming another physical 3DS boot/test cycle.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
BUILD="$ROOT/build"
QEMU="$ROOT/toolchain/qemu/qemu-arm-static"
APP_PROCESS="$BUILD/app_process_qemu/app_process_qemu"
SD="${ANDROID3DS_WIN}/sdcard/linux/android"
SCRIPTS="${ANDROID3DS_WIN}/scripts"
FAKEROOT="$BUILD/zygote_preload_fakeroot"
LOG="$ROOT/test_zygote_preload_qemu.log"
START_SYSTEM_SERVER=${START_SYSTEM_SERVER:-0}

test -x "$QEMU"
bash "$SCRIPTS/build_app_process_qemu.sh"
test -x "$APP_PROCESS"
test -s "$SD/system/framework/core.jar"
test -s "$SD/system/framework/framework.jar"
test -s "$SD/system/framework/services.jar"
test -s "$SD/system/framework/framework-res.apk"

rm -rf "$FAKEROOT"
mkdir -p "$FAKEROOT/system" "$FAKEROOT/data/dalvik-cache"

# Use the exact files intended for the SD card, including framework resources,
# fonts, properties, and pre-generated Dalvik caches.  Copying all of system/
# also prevents a host-only missing file from being mistaken for a port bug.
cp -a "$SD/system/." "$FAKEROOT/system/"
if [ -d "$SD/data" ]; then
    cp -a "$SD/data/." "$FAKEROOT/data/"
fi

python3 "$SCRIPTS/jar_dexdep.py" verify "$SD"

RUNNER="$FAKEROOT/run_zygote_preload.sh"
zygote_extra=""
if [ "$START_SYSTEM_SERVER" = 1 ]; then
    zygote_extra="--start-system-server"
fi
cat > "$RUNNER" <<EOF
#!/bin/bash
set -o pipefail
mkdir -p /system /data
mount --bind "$FAKEROOT/system" /system
mount --bind "$FAKEROOT/data" /data
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
export LD_LIBRARY_PATH=/system/lib
rm -f /tmp/android3ds-zygote-test.sock
timeout --signal=TERM 45s python3 "$SCRIPTS/qemu_zygote_socket_exec.py" \
    /tmp/android3ds-zygote-test.sock "$QEMU" "$APP_PROCESS" \
    -Xzygote /system/bin --zygote $zygote_extra
EOF
chmod 755 "$RUNNER"

set +e
a3ds_sudo unshare --mount -- "$RUNNER" > "$LOG" 2>&1
status=$?
set -e

cat "$LOG"

if grep -Eq 'Error preloading|Failure preloading resources|Resources[$]NotFoundException|width and height must be > 0|UnsatisfiedLinkError|Zygote died with exception|thread exiting with uncaught exception' "$LOG"; then
    echo "FAIL: zygote hit a fatal class/resource preload exception" >&2
    exit 1
fi

grep -q '\.\.\.preloaded [0-9][0-9]* classes in' "$LOG" || {
    echo "FAIL: zygote never completed class preloading" >&2
    exit 1
}
grep -q 'Accepting command socket connections' "$LOG" || {
    echo "FAIL: zygote never reached its command loop" >&2
    exit 1
}

if [ "$START_SYSTEM_SERVER" = 1 ]; then
    grep -q 'SystemServer' "$LOG" || {
        echo "FAIL: --start-system-server never entered SystemServer" >&2
        exit 1
    }
fi

# A healthy zygote waits forever in the command loop, so timeout(1)'s 124 is
# the expected exit.  A zero/non-timeout status means it unexpectedly exited.
if [ "$status" -ne 124 ]; then
    echo "FAIL: zygote exited unexpectedly with status $status" >&2
    exit 1
fi

echo "PASS: ARM zygote completed every class/resource preload and entered its command loop"
