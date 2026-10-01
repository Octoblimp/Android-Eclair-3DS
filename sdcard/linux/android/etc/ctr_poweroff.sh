#!/bin/sh
# Shutdown, run by the kernel when START is held for three seconds, or by
# GlobalActions.java (SELECT -> confirm dialog) via the sys.n3ds.poweroff
# property.
#
# drivers/platform/nintendo3ds/ctr_pwrkey.c calls orderly_poweroff(true),
# which execs whatever /proc/sys/kernel/poweroff_cmd points at -- init.rc
# points it here -- and forces power off on its own if the command cannot be
# run or fails. The kernel also arms an independent CTR_PWRKEY_FORCE_MS_DEFAULT
# deadline that cuts power directly through the MCU regardless of what this
# script does. Both buttons must power the console off unconditionally, so
# this script never refuses to power off: it makes a best-effort attempt to
# stop SD-backed writers and sync/unmount the card, but any failure along the
# way is only logged, never a reason to abort.
#
# N3DS_POWEROFF_SELECT_DEADLINE: that kernel deadline was armed *only* by the
# START timer in ctr_pwrkey.c. The SELECT path reaches this script through
# init, with no deadline armed at all, so any step here that blocked forever
# (a `sync` stuck behind the SD write path, an EBUSY remount, a reboot(2) that
# never lands) left the console powered on with a "remount,ro ... failed"
# message on screen and no way out but pulling the battery -- exactly what was
# reported. The first thing this script now does is ask the driver to arm the
# same deadline, so power is cut within N3DS_FORCE_MS no matter what follows.
#
# It deliberately does NOT use busybox's own "poweroff": without -f that tries
# to signal PID 1 with sysvinit semantics, and Android's init does not
# implement them, so nothing would happen. "poweroff -f" calls
# reboot(RB_POWER_OFF) directly, which is what we want.
#
# The power really is cut rather than the CPU merely halting: the device tree
# has a child of the working Nintendo 3DS MCU MFD.  Its built-in poweroff
# driver writes the MCU power-control register from pm_power_off_prepare and
# provides an atomic-I2C retry from pm_power_off if the first write is ignored.

MNT=/mnt/sd
SETPROP="${N3DS_SETPROP:-/system/bin/setprop}"
MOUNT_POINT="${N3DS_MOUNT_POINT:-/mnt/sd}"
POWER_OFF="${N3DS_POWER_OFF:-/sbin/poweroff}"
FORCE_ARM="${N3DS_FORCE_ARM:-/sys/module/ctr_pwrkey/parameters/force_arm_ms}"
FORCE_MS="${N3DS_FORCE_MS:-20000}"
GETPROP="${N3DS_GETPROP:-/system/bin/getprop}"
DMESG="${N3DS_DMESG:-dmesg}"
LOG_FINALIZE_TIMEOUT="${N3DS_LOG_FINALIZE_TIMEOUT:-20}"
POWER_READY="${N3DS_POWER_READY:-/proc/n3ds_poweroff_ready}"
SERVICES="wpa_supplicant dhcpcd prefs_sync logcat bootprogress bootlog lockupwatch logcatcon heartbeat adbd zygote bootanim surfaceflinger servicemanager console"

kmsg() {
    echo "poweroff: $1" > /dev/kmsg 2>/dev/null || true
    echo "poweroff: $1" > /dev/tty0 2>/dev/null || true
}

# Run "$@" but give up on it after $1 seconds. Used for every step that
# touches the SD card, because all of them can block indefinitely when the
# card's write path stalls. Returns 0 if the command finished, 1 if it had to
# be killed.
bounded() {
    _secs="$1"
    shift
    "$@" &
    _bp=$!
    _i=0
    while [ "$_i" -lt "$_secs" ]; do
        kill -0 "$_bp" 2>/dev/null || { wait "$_bp" 2>/dev/null; return $?; }
        sleep 1
        _i=$((_i + 1))
    done
    kmsg "step timed out after ${_secs}s: $*"
    kill -9 "$_bp" 2>/dev/null || true
    return 1
}

# N3DS_POWEROFF_ARM_FIRST: before touching anything that can block, hand the
# kernel an unconditional deadline. Even a total wedge below now ends in a
# real MCU power cut instead of a console stuck on the shutdown message.
if [ -w "$FORCE_ARM" ]; then
    echo "$FORCE_MS" > "$FORCE_ARM" 2>/dev/null &&
        kmsg "armed kernel force-poweroff deadline (${FORCE_MS} ms)" ||
        kmsg "WARNING: could not arm kernel force-poweroff deadline"
else
    kmsg "WARNING: $FORCE_ARM missing -- no kernel deadline armed"
fi

if [ ! -x "$SETPROP" ]; then
    SETPROP="$(command -v setprop 2>/dev/null || true)"
fi

# Best-effort: ask init to stop SD-backed writers so their logs have a
# better chance of ending cleanly. Do not wait or bail out if this fails.
# N3DS_LOG_FINALIZATION_V2: observe the writers stop, do not merely ask.
# wpa_supplicant_diag.sh writes its final snapshot from a TERM trap and
# boot_progress.sh can be parked in an SD write, so a fixed sleep is not a
# completion criterion.  Unlike the first version of this block, none of these
# checks can veto the shutdown -- a writer that will not stop is reported and
# then killed by release_sd_writers below, because the button must always work.
wait_for_log_writers() {
    [ -x "$GETPROP" ] || return 0
    _elapsed=0
    while [ "$_elapsed" -lt "$LOG_FINALIZE_TIMEOUT" ]; do
        _active=""
        for svc in $SERVICES; do
            case "$("$GETPROP" "init.svc.$svc" 2>/dev/null || true)" in
                running|restarting|stopping|post-stop) _active="$svc"; break ;;
            esac
        done
        [ -z "$_active" ] && return 0
        sleep 1
        _elapsed=$((_elapsed + 1))
    done
    kmsg "WARNING: $_active still running after ${LOG_FINALIZE_TIMEOUT}s"
    return 1
}

# Conservative on purpose: a vda write failure, a FAT error or a buffer I/O
# error means the sync above cannot be read as proof the card is consistent.
# It is recorded in the ring buffer -- which survives into the next boot
# capture -- rather than acted on, since refusing to power off is precisely
# the behaviour that stranded the console before.
check_storage_errors() {
    command -v "$DMESG" >/dev/null 2>&1 || return 1
    "$DMESG" 2>/dev/null | grep -Eiq \
        'Buffer I/O error|FAT-fs.*error|blk_update_request.*I/O error'
}

if [ -n "$SETPROP" ]; then
    for svc in $SERVICES; do
        "$SETPROP" ctl.stop "$svc" 2>/dev/null || true
    done
    if [ ! -x "$GETPROP" ]; then
        GETPROP="$(command -v getprop 2>/dev/null || true)"
    fi
    # Give init a moment to actually reap them before counting writers.
    wait_for_log_writers || true
fi

# N3DS_SETTINGS_PERSIST: Android has stopped; save settings changed since
# prefs_sync's last pass (it runs once a minute).  Bounded tightly, because
# the kernel deadline armed above leaves no room for a stalled card.
bounded 4 /etc/android_prefs_init.sh --flush || true

# N3DS_SD_CLEAN_SHUTDOWN: /mnt/sd can never be unmounted -- /system, /etc,
# /usr, /sdcard and /data/dalvik-cache are bind mounts of directories inside
# it, and this script's own text and /system/bin/setprop are read from it.
# The old "umount $MOUNT_POINT" therefore always failed with EBUSY, silently
# (2>/dev/null || true), so the FAT volume was never marked clean and every
# shutdown looked like a power cut to the filesystem -- hence the
# "Volume was not properly unmounted. Some data may be corrupt." advisory on
# every single boot.
#
# A read-only remount does the same job and *does* succeed while the card is
# merely mounted: fat_remount() (fs/fat/inode.c) calls sync_filesystem() and
# then fat_set_state(sb, 0, 0), which flushes everything and clears the FAT
# dirty flag.
#
# What it does NOT tolerate is a file still open for writing: do_remount()
# calls sb_prepare_remount_readonly(), which returns -EBUSY while any writable
# fd exists anywhere on the superblock -- bind mounts included, since they
# share it. ctl.stop alone never got that count to zero (Dalvik apps, adbd and
# stragglers keep /data files open), which is why the remount kept failing and
# reporting the card as busy. Kill whatever is left holding the card first.
#
# Everything in this script's own process group is skipped: init gives each
# service its own group, so that is exactly "us and our subshells" (including
# the fuser we just forked) and nothing else. Killing ourselves half way
# through the sweep would leave the card dirty and the console on.
release_sd_writers() {
    _pgid=$(awk '{print $5}' /proc/$$/stat 2>/dev/null)
    _left=""
    for _p in $(fuser -m "$MOUNT_POINT" 2>/dev/null | tr -cs '0-9' ' '); do
        [ "$_p" = "1" ] && continue
        [ "$(awk '{print $5}' /proc/$_p/stat 2>/dev/null)" = "$_pgid" ] && continue
        _left="$_left $_p"
    done
    [ -z "$_left" ] && return 0
    kmsg "still holding $MOUNT_POINT:$_left -- terminating"
    kill -15 $_left 2>/dev/null || true
    sleep 1
    kill -9 $_left 2>/dev/null || true
    sleep 1
    return 0
}

release_sd_writers
bounded 15 sync || true

_ok=0
_try=0
while [ "$_try" -lt 3 ]; do
    if bounded 10 mount -o remount,ro "$MOUNT_POINT" 2>/dev/null; then
        _ok=1
        break
    fi
    _try=$((_try + 1))
    release_sd_writers
done

if [ "$_ok" = "1" ]; then
    kmsg "remounted $MOUNT_POINT read-only (FAT marked clean)"
else
    # Something still holds a writable file open. Fall back to the old
    # best-effort behaviour rather than refusing to power off.
    kmsg "remount,ro of $MOUNT_POINT failed -- falling back to sync+umount"
    bounded 10 umount "$MOUNT_POINT" || true
    bounded 10 sync || true
fi

if check_storage_errors; then
    kmsg "WARNING: storage/FAT error in this boot -- the card may be inconsistent"
fi

kmsg "powering off now"

# N3DS_POWEROFF_READY_ACK: the card is flushed, so tell the kernel to cut power
# now rather than leaving it to the armed deadline. ctr_pwrkey's
# /proc/n3ds_poweroff_ready runs the same direct MCU write the deadline would,
# but immediately and with the acknowledgement recorded, so a `poweroff -f`
# that never returns (the failure this whole script exists for) no longer
# leaves the console lit for the rest of the timeout.
if [ -w "$POWER_READY" ]; then
    kmsg "acknowledging poweroff log gate"
    echo 1 > "$POWER_READY" 2>/dev/null || true
    sleep 3
    kmsg "log gate did not cut power -- falling back to poweroff -f"
fi

"$POWER_OFF" -f
kmsg "poweroff -f returned rc=$? -- kernel force-poweroff deadline remains armed as a backstop"
exit 0
