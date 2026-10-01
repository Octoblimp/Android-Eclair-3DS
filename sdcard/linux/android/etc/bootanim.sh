#!/bin/sh
# Start the boot animation on the bottom screen.
#
# This wrapper exists only so the player's diagnostics reach /dev/kmsg (and
# therefore boot_log_latest.txt). init discards a service's stderr, and there
# is no logcat to read /dev/log with yet.
#
# exec, not a pipeline: the binary must *become* this process so that init's
# stop/restart signals -- and the kill -TERM -1 that ctr_poweroff.sh sends --
# reach the player itself rather than a shell waiting on it.
#
# /system/bin/bootanimation plays /system/media/bootanimation.zip -- the real
# Android format, read with upstream's own ZipFileRO -- and falls back to the
# built-in mask-and-shine animation from /system/media/images if the zip is
# missing.

BIN=/system/bin/bootanimation

if [ ! -x "$BIN" ]; then
    echo "bootanim: FAIL: $BIN missing or not executable" > /dev/kmsg 2>/dev/null
    exit 1
fi

# N3DS_FB1_PAGE_OFFSET: sd:/linux/panel_yoff.txt is no longer read.  The
# "scanout shift" it compensated for was fb1's scanout starting 1024 bytes
# into its mmap() page; DisplayTarget now points at the scanout itself, so a
# value left on an old card would only push a correctly aligned picture off.

# fbtest's 40s calibration pattern used to run here before every boot animation
# (logo placement + panel colour-channel diagnostics -- see the "fb1 offset"
# session recap in docs/HANDOFF.md). Logo placement is confirmed correct now,
# so it no longer runs by default. fbtest itself is NOT deleted -- it is still
# built and deployed at /system/bin/fbtest, and DisplayTarget's calibration
# code is exactly what the top screen will need for its own debug console
# later. Re-enable by uncommenting the block below (or adding a trigger file
# check) if the panel geometry ever needs re-measuring.
#
# if [ -x /system/bin/fbtest ]; then
#     echo "bootanim: running fbtest first (40s)" > /dev/kmsg 2>/dev/null
#     /system/bin/fbtest > /dev/kmsg 2>&1
# fi

# The boot sound used to be started from here, backgrounded.  It is now its
# own oneshot service, /etc/bootsound.sh, declared in init.rc ahead of both
# mediaserver and this script.
#
# Two reasons it had to leave.  A child of this script dies with this script,
# and SurfaceFlinger::bootFinished() does property_set("ctl.stop", "bootanim")
# the moment the first frame of real UI is ready -- which lands inside the
# 1.78 s clip and cut it off.  And the sound has to reach /dev/eac before
# mediaserver does: AudioFlinger's AudioHardwareGeneric opens it from a
# constructor, and init starts services in definition order.

echo "bootanim: starting" > /dev/kmsg 2>/dev/null

exec "$BIN" 2>/dev/kmsg
