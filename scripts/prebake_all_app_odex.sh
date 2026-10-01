#!/bin/bash
# N3DS_PREBAKE_ALL: rebake every bundled app's odex.
#
# Dalvik records, inside each app odex, the signature of every bootclasspath
# dalvik-cache file it was optimised against. Change core.jar, framework.jar
# or services.jar and EVERY app odex becomes stale at once -- the device then
# falls back to on-device dexopt for each of them, which on this hardware is
# the difference between a boot and a five-minute stall.
#
# That has always been true, and the fix has always been "run the eleven
# prebake scripts again", which is exactly the kind of step that gets
# half-done. There is one list now. Run this after build_dexpreopt_qemu.sh,
# which must itself run after sync_android_to_sdcard.sh:
#
#     sync_android_to_sdcard.sh
#     build_dexpreopt_qemu.sh
#     prebake_all_app_odex.sh
#     verify_release_artifacts.sh
#     build_sdcard_zip.sh
#
# Ordering matters both ways: dexpreopt reads the SD staging tree, so it has
# to follow the sync; the app odex record the boot cache dexpreopt produces,
# so they have to follow dexpreopt.
. "$(dirname "${BASH_SOURCE[0]:-$0}")/a3ds_env.sh"
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"

SCRIPTS=(
    prebake_launcher_odex.sh
    prebake_browser_odex.sh
    prebake_settings_app_odex.sh
    prebake_settings_provider_odex.sh
    prebake_telephony_provider_odex.sh
    prebake_contacts_provider_odex.sh
    prebake_media_provider_odex.sh
    prebake_touchdiag_app_odex.sh
    prebake_globaltime_app_odex.sh
    prebake_gpuz_app_odex.sh
    prebake_latinime_odex.sh
    prebake_development_app_odex.sh
    prebake_n3dsdialer_app_odex.sh
    prebake_camera_app_odex.sh
    prebake_mictest_app_odex.sh
    prebake_telco_odex.sh
)

failed=()
for s in "${SCRIPTS[@]}"; do
    if [ ! -x "$HERE/$s" ]; then
        echo "prebake_all_app_odex: missing $s" >&2
        exit 1
    fi
    echo "=== $s ==="
    if "$HERE/$s" > "/tmp/prebake_${s%.sh}.log" 2>&1; then
        echo "    ok"
    else
        echo "    FAILED -- see /tmp/prebake_${s%.sh}.log" >&2
        failed+=("$s")
    fi
done

if [ ${#failed[@]} -ne 0 ]; then
    echo
    echo "prebake_all_app_odex: ${#failed[@]} script(s) failed: ${failed[*]}" >&2
    exit 1
fi

# N3DS_PIN_MTIME_PARITY: every prebake script copies its odex into the Windows
# and the WSL staging tree with two separate cp calls, and the Windows-copy
# release gate compares those trees with rsync -t at whole-second resolution.
# A pair of copies that straddles a second boundary fails the gate on mtime
# alone (framework.jar, MicTest.odex, Contacts.odex on 2026-09-30 -- a
# different file each run). Mirror the mtime, but ONLY for byte-identical
# files: a real content mismatch must still reach the gate and fail it.
SD_APP="${ANDROID3DS_WIN}/sdcard/linux/android/system/app"
WSL_APP="${ANDROID3DS_ROOT}/sdcard/linux/android/system/app"
mirrored=0
for odex in "$SD_APP"/*.odex; do
    peer="$WSL_APP/$(basename "$odex")"
    if [ -f "$peer" ] && cmp -s "$odex" "$peer"; then
        touch -r "$odex" "$peer"
        mirrored=$((mirrored + 1))
    fi
done
echo "=== mirrored Windows staging mtime onto $mirrored identical WSL odex ==="

echo
echo "=== prebake_all_app_odex: all ${#SCRIPTS[@]} app odex rebaked ==="
echo "Now run verify_release_artifacts.sh -- it is the only thing that"
echo "actually checks the recorded bootclasspath signatures."
