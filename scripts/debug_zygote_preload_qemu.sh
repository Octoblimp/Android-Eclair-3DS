#!/bin/bash
# Symbolicate a fatal signal from the host-side ARM zygote preload test.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

ROOT="${ANDROID3DS_ROOT}"
BUILD="$ROOT/build"
QEMU="$ROOT/toolchain/qemu/qemu-arm-static"
APP_PROCESS="$BUILD/app_process_qemu/app_process_qemu"
FAKEROOT="$BUILD/zygote_preload_fakeroot"
SCRIPTS="${ANDROID3DS_WIN}/scripts"
GDB_LOG="$ROOT/debug_zygote_preload_qemu.log"
PORT=12345

test -x "$APP_PROCESS"
test -d "$FAKEROOT/system"
test -d "$FAKEROOT/data"

RUNNER="$FAKEROOT/run_zygote_gdb.sh"
cat > "$RUNNER" <<EOF
#!/bin/bash
set -e
mkdir -p /system /data
mount --bind "$FAKEROOT/system" /system
mount --bind "$FAKEROOT/data" /data
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
export LD_LIBRARY_PATH=/system/lib
export ANDROID3DS_QEMU_GDB_PORT=$PORT
rm -f /tmp/android3ds-zygote-gdb.sock
python3 "$SCRIPTS/qemu_zygote_socket_exec.py" \
    /tmp/android3ds-zygote-gdb.sock "$QEMU" "$APP_PROCESS" \
    -Xzygote /system/bin --zygote > "$FAKEROOT/qemu-gdb-target.log" 2>&1 &
qemu_pid=\$!

gdb-multiarch --batch "$APP_PROCESS" \
    -ex 'set pagination off' \
    -ex 'set confirm off' \
    -ex 'target remote :$PORT' \
    -ex 'continue' \
    -ex 'thread apply all bt full' \
    -ex 'info registers' \
    -ex 'x/16i \$pc-24' > "$GDB_LOG" 2>&1 || true

kill \$qemu_pid 2>/dev/null || true
wait \$qemu_pid 2>/dev/null || true
EOF
chmod 755 "$RUNNER"

a3ds_sudo unshare --mount -- "$RUNNER"
cat "$FAKEROOT/qemu-gdb-target.log"
cat "$GDB_LOG"
