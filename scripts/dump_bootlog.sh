#!/bin/sh
# Phase 1 diagnostics: dump the boot log + system state to the real SD
# card so it can be read from a PC (no WiFi/network yet, no other way
# to get data off this device). Runs once at boot as a oneshot service
# (see init.rc), after init.rc's own "on init" section has already
# mounted the SD card read-write at /mnt/sd to back Android's
# persistent /data -- so the mount below is normally a harmless no-op,
# kept only as a fallback in case that earlier mount ever fails.
#
# Unlike the original version of this script, the mount is NOT undone
# afterward -- it has to stay up for the rest of the session since
# /data depends on it.
#
# Safety: never overwrites an existing file. "set -C" (noclobber) makes
# "> file" fail if file already exists instead of truncating it, so a
# previous boot's log (or anything else already on the card) can never
# be clobbered by this script -- it only ever creates brand new files,
# trying boot_log.txt, then boot_log_1.txt, boot_log_2.txt, etc.
set -C

capture() {
	# $1 = destination base name (without extension), $2 = numbered suffix pattern
	base="$1"
	i=0
	while [ "$i" -lt 100 ]; do
		if [ "$i" -eq 0 ]; then
			target="/mnt/sd/linux/${base}.txt"
		else
			target="/mnt/sd/linux/${base}_$i.txt"
		fi
		if {
			echo "=== date ==="; date
			echo; echo "=== uname -a ==="; uname -a
			echo; echo "=== dmesg ==="; dmesg
			echo; echo "=== /proc/cpuinfo ==="; cat /proc/cpuinfo
			echo; echo "=== ls -la /dev ==="; ls -la /dev
			echo; echo "=== mount ==="; mount
			echo; echo "=== free ==="; free
			echo; echo "=== /proc/interrupts ==="; cat /proc/interrupts
			echo; echo "=== /proc/partitions ==="; cat /proc/partitions
			echo; echo "=== ls /sys/class/net ==="; ls /sys/class/net
			echo; echo "=== ifconfig -a ==="; ifconfig -a
			echo; echo "=== /proc/net/wireless ==="; cat /proc/net/wireless
			echo; echo "=== ls /sys/bus/sdio/devices ==="; ls -la /sys/bus/sdio/devices 2>&1
			echo; echo "=== ls /sys/class/mmc_host ==="; ls -la /sys/class/mmc_host 2>&1
			echo; echo "=== sdio device uevent/vendor/device (actual chip ID) ==="
			for d in /sys/bus/sdio/devices/*/; do
				echo "--- $d ---"
				cat "$d/uevent" 2>&1
				echo "vendor: $(cat "$d/vendor" 2>&1)"
				echo "device: $(cat "$d/device" 2>&1)"
			done
			echo; echo "=== lsmod ==="; lsmod
		} > "$target" 2>/dev/null; then
			break
		fi
		i=$((i + 1))
	done
}

# Report status straight to the screen (/dev/tty0), not just to a file that
# depends on the very SD mount we're trying to diagnose. If the mount or the
# capture ever fails again, this is how to find out *why* without needing a
# boot_log.txt that, by definition, won't exist in that failure case.
scr() {
	echo "$1" > /dev/tty0 2>/dev/null
}

mkdir -p /mnt/sd

# init.rc's "on init" already tried this mount once, synchronously, before
# any service started. On real hardware that single attempt has been seen
# to lose a race against the SD card / virtio-blk device not being fully
# ready yet, silently leaving /mnt/sd as an empty ramdisk directory (and
# /data as a symlink to a spot that doesn't really exist on the card).
# init.rc has no retry/loop primitive to fix that itself, but this is a
# plain shell script, so retry here with a short pause. Bumped from 5 to 15
# attempts (up to 15s) -- 5 was not enough on at least one real boot.
scr "[bootlog] mounting /mnt/sd..."
i=0
while [ "$i" -lt 15 ]; do
	if grep -q ' /mnt/sd ' /proc/mounts; then
		break
	fi
	mount -t vfat -o rw /dev/vda1 /mnt/sd 2>/dev/null || mount -t vfat -o rw /dev/vda /mnt/sd 2>/dev/null
	if grep -q ' /mnt/sd ' /proc/mounts; then
		break
	fi
	i=$((i + 1))
	sleep 1
done

if grep -q ' /mnt/sd ' /proc/mounts; then
	scr "[bootlog] /mnt/sd mounted after ${i}s"
else
	scr "[bootlog] /mnt/sd FAILED to mount after 15s -- ls /dev/vda*:"
	ls -la /dev/vda* > /dev/tty0 2>&1
fi

mkdir -p /mnt/sd/linux

# N3DS_PICA_BOOT_PROBE: read-only status collection after the kernel's one
# delayed, watchdog-bounded qualification attempt. This logger never starts
# another command list and therefore cannot bypass reboot-only quarantine.
if [ -x /system/bin/pica200_smoketest ]; then
	i=0
	while [ "$i" -lt 100 ]; do
		if [ "$i" -eq 0 ]; then
			pica_target=/mnt/sd/linux/pica200_probe.txt
		else
			pica_target=/mnt/sd/linux/pica200_probe_$i.txt
		fi
		if [ -e "$pica_target" ]; then
			i=$((i + 1))
			continue
		fi
		if /system/bin/pica200_smoketest > "$pica_target" 2>&1; then
			scr "[pica200] read-only status saved after kernel qualification attempt"
			break
		elif [ -s "$pica_target" ]; then
			scr "[pica200] probe failed; saved diagnostics"
			break
		fi
		i=$((i + 1))
	done
	sync
fi

# Same reasoning: make sure Android's /data tree is really there even if
# init.rc's own attempt at creating it lost the race above. mkdir -p is
# idempotent, so this is a harmless no-op on the common case where
# init.rc's mount + mkdirs already succeeded.
mkdir -p /mnt/sd/linux/android/data/property

if grep -q ' /mnt/sd ' /proc/mounts; then
	if capture boot_log; then
		scr "[bootlog] wrote boot_log.txt"
	else
		scr "[bootlog] capture() FAILED (100 filename attempts exhausted?)"
	fi
	sync

	# The AR6002 WiFi bring-up (HTC target-ready handshake) has been
	# observed to keep producing dmesg output well after this immediate
	# snapshot and after the console shell has already appeared -- i.e.
	# it's slow/async, not something the boot-time snapshot above can
	# catch. Take a second snapshot after a delay, in the background, so
	# it doesn't hold up the console shell from starting. No re-mount
	# needed -- /mnt/sd stays mounted for the whole session now.
	(
		sleep 30
		capture boot_log_delayed
		sync
	) &
else
	# SD write is impossible without the mount, but still leave something
	# behind in the initramfs's own tmpfs so a live shell (once reachable)
	# can "cat /tmp/boot_log.txt" even though it won't survive reboot.
	mkdir -p /tmp
	{
		echo "=== SD MOUNT FAILED -- this is a ramdisk-only fallback capture ==="
		echo "=== date ==="; date
		echo; echo "=== dmesg ==="; dmesg
		echo; echo "=== mount ==="; mount
		echo; echo "=== ls -la /dev ==="; ls -la /dev
		echo; echo "=== /proc/partitions ==="; cat /proc/partitions
	} > /tmp/boot_log.txt 2>/dev/null
	scr "[bootlog] wrote fallback /tmp/boot_log.txt (ramdisk only, not on SD)"
fi

