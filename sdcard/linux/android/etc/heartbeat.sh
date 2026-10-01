#!/bin/sh
# Proof-of-life for the top screen debug console, independent of
# everything else that has turned out to be able to freeze on this port.
#
# Every diagnostic tool built so far (dump_bootlog.sh, lockup_watch.sh,
# boot_progress.sh) depends on writing to the SD card, which shares the same
# virtio-blk/PXI path already root-caused once for a total lockup (see
# docs/HANDOFF.md, project_pxi_workqueue_lockup) -- if a future freeze is in
# that same family, or anywhere else in the SD path, all three go dark with
# it and leave nothing behind, exactly like the two most recent sessions'
# freezes (no lockup_dump.txt/crash_signature.txt/boot_log.txt at all).
#
# This writes one short line to /dev/kmsg every 2s instead. /dev/kmsg needs
# no filesystem, no SD card, no mount -- only the kernel and this one shell
# process need to still be scheduled. Because ignore_loglevel is set (see
# nintendo3ds_ctr.dts/nintendo3ds_ktr.dts bootargs), it also prints straight
# to the physical top screen (fbcon), so a photo/video taken at the moment
# of a freeze should show the last line's uptime -- pinning down almost
# exactly when the freeze happened without needing anything pulled off the
# card afterward. It also lands in dmesg itself, so it still shows up in
# boot_log.txt/lockup_dump.txt on the boots where those DO survive.
#
# Deliberately NOT a firehose: logcat_console.sh's own header comment warns
# that fbcon=rotate:1 software-rotates and full-redraws on scroll, so
# constant console traffic is a real CPU cost, not just cosmetic, and named
# as the first thing to disable if a lockup reappears after it was added.
# One short line every 2s is a small addition on top of that existing cost,
# not a second firehose -- if lockups start correlating with this instead,
# disable this service first before suspecting anything else.
#
# Not oneshot: runs for the life of the boot, init restarts it if it dies.
# If THIS stops updating too, that's real evidence of a genuine whole-kernel
# freeze rather than an Android-userspace-only hang, since nothing here
# touches Dalvik, zygote, surfaceflinger, or the SD card at all.
#
# N3DS_HEARTBEAT_OPT_IN (#323): off by default.  The freezes it was built to
# time (PXI workqueue lockup, VFP11 EX Oops) are root-caused and fixed, and a
# line every 2s was the bulk of the top-screen scroll a #322 tester asked to
# have removed.  To bring it back for a freeze hunt, create an empty file
# named debug_heartbeat in sd:/linux/ from a PC and reboot -- no rebuild.
# The file is read once here, at start; nothing else touches the card.
# When off this process stays alive and asleep, so init does not keep
# restarting it and ctr_poweroff.sh's service list needs no change.

if [ ! -e /mnt/sd/linux/debug_heartbeat ]; then
	echo "heartbeat: off (create sd:/linux/debug_heartbeat to enable, N3DS_HEARTBEAT_OPT_IN)" > /dev/kmsg 2>/dev/null
	while true; do
		sleep 3600
	done
fi

i=0
while true; do
	up=$(cut -d' ' -f1 /proc/uptime 2>/dev/null)
	free_kb=$(free 2>/dev/null | awk '/^Mem:/ { print $4 }')
	load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)
	echo "[heartbeat $i] up=${up}s free=${free_kb}kB load=${load}" > /dev/kmsg 2>/dev/null
	i=$((i + 1))
	sleep 2
done
