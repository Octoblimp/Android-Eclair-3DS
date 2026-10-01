#!/bin/bash
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -e

BUILD="${ANDROID3DS_ROOT}"/build
QEMU="${ANDROID3DS_ROOT}"/toolchain/qemu/qemu-arm-static
FAKEROOT=$BUILD/dexpreopt_fakeroot
SD="${ANDROID3DS_WIN}/sdcard/linux/android"
OVERLAY="${ANDROID3DS_ROOT}"/third_party/buildroot/board/nintendo3ds/rootfs_overlay
WSL_SD="${ANDROID3DS_ROOT}"/sdcard/linux/android

[ -x "$BUILD/dexopt/dexopt_qemu" ] || { echo "missing dexopt_qemu -- run build_dexpreopt_qemu.sh first"; exit 1; }
[ -f "$FAKEROOT/data/dalvik-cache/system@framework@core.jar@classes.dex" ] || {
    echo "missing fakeroot dalvik-cache -- run build_dexpreopt_qemu.sh first"; exit 1; }

echo "=== 1. binfmt_misc qemu-arm ==="
if [ ! -e /proc/sys/fs/binfmt_misc/qemu-arm ]; then
    REGFILE=$(mktemp)
    printf ':qemu-arm:M::\\x7fELF\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28\\x00:\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:%s:F\n' "$QEMU" > "$REGFILE"
    a3ds_sudo bash -c "cat '$REGFILE' > /proc/sys/fs/binfmt_misc/register"
    rm -f "$REGFILE"
fi

# N3DS_NO_STOCK_CONTACTS: the stock Contacts app is retired (#317); the
# dialer is N3dsDialer and ContactsProvider has its own prebake.
for APK_NAME in Settings Phone Mms; do
    echo "=== processing $APK_NAME ==="
    mkdir -p "$FAKEROOT/system/app"
    cp -v "$SD/system/app/$APK_NAME.apk" "$FAKEROOT/system/app/$APK_NAME.apk"
    cp "$BUILD/dexopt/dexopt_qemu" "$FAKEROOT/system/bin/dexopt"
    chmod 755 "$FAKEROOT/system/bin/dexopt"
    cp "$QEMU" "$FAKEROOT/qemu-arm-static"

    RUNSCRIPT="$FAKEROOT/run_${APK_NAME}_preopt.sh"
    cat > "$RUNSCRIPT" <<INNER_EOF
#!/bin/bash
set -e
mkdir -p /system /data
mount --bind "$FAKEROOT/system" /system
mount --bind "$FAKEROOT/data" /data
export ANDROID_ROOT=/system
export ANDROID_DATA=/data
export BOOTCLASSPATH=/system/framework/core.jar:/system/framework/framework.jar:/system/framework/services.jar
rm -f /system/app/$APK_NAME.odex
: > /system/app/$APK_NAME.odex
exec 3< /system/app/$APK_NAME.apk
exec 4<> /system/app/$APK_NAME.odex
"$QEMU" "$BUILD/dexopt/dexopt_qemu" --zip 3 4 /system/app/$APK_NAME.apk ""
rc=\$?
exec 3<&- 4<&-
exit \$rc
INNER_EOF
    chmod 755 "$RUNSCRIPT"
    a3ds_sudo unshare --mount -- "$RUNSCRIPT"
    a3ds_sudo chown "$(id -u)":"$(id -g)" "$FAKEROOT/system/app/$APK_NAME.odex" 2>/dev/null || true

    mkdir -p "$SD/system/app"
    cp -v "$FAKEROOT/system/app/$APK_NAME.odex" "$SD/system/app/$APK_NAME.odex"
    chmod 644 "$SD/system/app/$APK_NAME.odex"

    mkdir -p "$OVERLAY/system/app"
    cp -v "$FAKEROOT/system/app/$APK_NAME.odex" "$OVERLAY/system/app/$APK_NAME.odex"
    chmod 644 "$OVERLAY/system/app/$APK_NAME.odex"

    # N3DS_PREBAKE_WSL_TARGET: also deploy to the canonical WSL staging tree.
    # verify_release_artifacts.sh reads whichever tree it is launched from,
    # and sync_android_to_sdcard.sh has to run BEFORE dexpreopt and prebake --
    # so without this copy the WSL tree keeps the previous build s odex and
    # the gate reports STALE for a file that was just rebuilt.
    mkdir -p "$WSL_SD/system/app"
    cp -v "$FAKEROOT/system/app/$APK_NAME.odex" "$WSL_SD/system/app/$APK_NAME.odex"
    chmod 644 "$WSL_SD/system/app/$APK_NAME.odex"
done
echo "=== done ==="
