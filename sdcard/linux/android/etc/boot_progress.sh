#!/bin/sh
# Cheap incremental checkpoint so an early/near-instant wedge still leaves
# evidence behind, even if it never reaches a lockup_watch.sh trigger.
#
# 2026-08-04: a boot with an empty /data/dalvik-cache (four full-framework
# dexopts back to back, instead of the one that the last confirmed-good boot
# needed) softlocked with an rcu_sched self-detected stall at t~76s
# (crash.jpg). dump_bootlog.sh only snapshots at t~0-15s and once more at
# t~30s; lockup_watch.sh only writes anything once a lockup *signature* has
# already appeared in dmesg, and by the time that happens the machine may
# already be too starved for lockup_watch's own dmesg/write to complete
# reliably (the RCU message itself says "unless rcu_sched gets sufficient
# CPU time, OOM is now expected behavior" -- i.e. the kernel is telling you
# scheduling itself is in trouble). Neither gives any data for a wedge that
# happens between t=30s and whichever trigger fires, or never fires.
#
# This writes a small, cheap snapshot from very early in boot, always
# overwriting one fixed file via a temp+rename so a snapshot that gets
# interrupted mid-write doesn't corrupt the last good one. Whatever the
# last successful write was is on the card even if everything after it is
# lost to a total wedge.
#
# 2026-08-05 (this session): "cheap" was wrong, and the evidence for that is
# in the file this script itself produced. Its header said uptime=131.98 but
# the dmesg tail *inside the same snapshot* ran to t=415.8 -- i.e. ONE
# iteration of the block below took 283 seconds to write ~50 KB, because
# each write to the FAT temp file blocked. The matching kernel hung-task
# warning names this script by name:
#
#   INFO: task boot_progress.s:146 blocked for more than 120 seconds
#   __schedule <- schedule_preempt_disabled <- __mutex_lock
#     <- fat_alloc_clusters <- fat_add_cluster <- __fat_get_block
#     <- fat_write_begin <- generic_perform_write <- vfs_write
#
# Rewriting a ~50 KB file every 3 s means a truncate + full cluster
# reallocation every 3 s, forever, on a FAT filesystem sitting behind
# virtio-blk -> ctr_pxi -> ARM9. Add logcat's own rotating 256 KB writes,
# lockup_watch.sh and dump_bootlog.sh on the same card, and the sustained
# loadavg of ~5.2 seen on that boot is almost entirely tasks in D state
# waiting on this. lockup_watch.sh then needed 45 s to commit a 130-byte
# header before the machine froze outright.
#
# So: 15 s instead of 3 s, 250 dmesg lines instead of 600, and ONE dmesg
# read per tick instead of two full ring-buffer reads. That is roughly a
# 10x cut in bytes-per-second to the card.
#
# 2026-09-11: boot_progress.txt now keeps EVERY dmesg line, not a 250-line
# tail. That sounds like it undoes the fix above, and it would have if it were
# done the obvious way -- but the 283-second stall documented above was not
# caused by the file being large, it was caused by REWRITING it. A truncate
# plus a full cluster reallocation of a growing file, every tick, forever.
#
# This appends instead. Each tick emits only the dmesg lines that appeared
# since the previous tick, so a line is written to the card exactly once, and
# the total bytes this script ever writes is bounded by how much the kernel
# actually logs -- not by file size x tick count. In steady state that is far
# LESS SD traffic than the old 250-line rewrite, which re-wrote the same 250
# lines every 30 s whether or not anything had changed.
#
# Ring-buffer wrap is handled explicitly: if the first line of the ring is no
# longer the line we remember, the ring rolled over, we say so in the file and
# resynchronise rather than silently skipping or duplicating a block.
#
# It also now reports how long each snapshot took to /dev/kmsg -- no SD
# dependency, prints straight to the top screen. That turns this script
# into an SD-latency probe: if the per-write time climbs from a fraction of
# a second into tens of seconds, the storage path is degrading, and that is
# visible in a photograph without pulling anything off the card.

OUT=/mnt/sd/linux/boot_progress.txt
# Keep staged Wi-Fi traces separate from boot_progress.txt. The latter
# intentionally stores only a tail, while this file preserves narrow matching
# lines from both the first SD-backed checkpoint and a later checkpoint.
WIFI_OUT=/mnt/sd/linux/wifi_trace.txt
WIFI_TMP=/mnt/sd/linux/.wifi_trace.tmp
WIFI_SNAPSHOT_TMP=/mnt/sd/linux/.wifi_snapshot.tmp
WIFI_RE='cfg80211|3ds-sdhc|sdio|GPIO|WiFi power|CMD[2357]|AR6K|AR6002|ath6|BMI|BMIDone|HTC|wlan0|wpa_supplicant|firmware|3ds-dsp|dsp_chime|boot reply|readback|PSTS='
# Keep the first filtered snapshot large enough for the complete prefixed
# register dump, while bounding every stage so the 20-stage trace cannot
# duplicate the whole dmesg ring on every interval.
# N3DS_WIFI_TRACE_EARLY_UNTRUNCATED (2026-09-11): this was 256, applied as
# `tail -n 256`, i.e. it kept the NEWEST 256 matches and silently discarded the
# oldest.  The 2026-09-11 capture matched exactly 256 lines, so it was sitting
# at the cap -- and everything before t=5.662 s had been thrown away.  That
# window is where platform drivers probe, which cost a hardware round-trip:
# the absence of any `3ds-dsp` line in that file was read as "the DSP driver
# never probed", when the file could not have contained it either way.
# (dsp_chime opened /dev/ctr_dsp0 successfully later in the same boot, which
# proves probe DID run and reach misc_register().)
#
# The early stage is one snapshot of a ring buffer that is bounded anyway, so
# capping it buys nothing and costs evidence.  0 means no truncation.
WIFI_INITIAL_LINES=0
# N3DS_WIFI_TRACE_DELAYED_WINDOW: the Mobile Data AP failure lands ~220 s in,
# so it is only ever captured by a delayed stage.  At 64 lines a single target
# assert (60 register lines before N3DS_AR6014_REGDUMP_COMPACT) evicted every
# AR6002 AP: line and the whole WMI command-history ring -- the dump destroyed
# the evidence it was printed to explain, in both AP runs captured so far.
# What has to fit now is ~8 register lines + ~10 AP profile lines + a 16-entry
# command ring plus the AR6002 chatter interleaved with them.
WIFI_DELAYED_LINES=96
# N3DS_WIFI_TRACE_BRINGUP_SNAPSHOT: the delayed tail above is sized for a
# steady-state stage, and the driver emits far more than 96 matching lines in
# the 30 s that contain its own bring-up.  In #257 that silently evicted the
# BMI download, the HTC setup and the WMI-ready banner from every capture, so
# a patch whose only evidence is printed there could not be confirmed at all.
# Take one much larger snapshot the first time wlan0 exists.
WIFI_BRINGUP_LINES=600
WIFI_BRINGUP_STAMP=/tmp/.wifi_bringup_captured

# N3DS_BOOT_PROGRESS_FULL_LOG: state for the incremental dmesg appender.
# BP_COUNT  - how many ring-buffer lines have already been written to OUT.
# BP_FIRST  - the first line of the ring as of the last tick, used to detect
#             wrap.  Both live in /tmp (tmpfs): no SD traffic, and they reset
#             naturally on reboot, which is what we want.
BP_COUNT_FILE=/tmp/.bp_dmesg_count
BP_FIRST_FILE=/tmp/.bp_dmesg_first
# N3DS_PICA_AND_BOUNDED_DIAGNOSTICS: the latest hardware run began
# returning virtio/FAT write errors after 183 seconds while the old
# logger rewrote this file forever. Thirty-second snapshots for ten
# minutes preserve evidence without permanent SD traffic.
INTERVAL=30
MAX_SNAPSHOTS=20

CRASH_OUT=/mnt/sd/linux/crash_signature.txt
CRASH_TMP=/mnt/sd/linux/.crash_signature.tmp

kmsg() {
	echo "boot-progress: $1" > /dev/kmsg 2>/dev/null
}

# N3DS_BOOT_PROGRESS_FSYNC: flush ONE file, not the world.  See the
# N3DS_NO_GLOBAL_SYNC note in the loop below for why `sync` is banned here.
# busybox in this config has no fsync applet, but dd conv=fsync is compiled
# in; if=/dev/null + conv=notrunc means it writes nothing and truncates
# nothing, it just fsync()s the fd it opened.
fsync_file() {
	[ -f "$1" ] || return 0
	dd if=/dev/null of="$1" conv=notrunc,fsync 2>/dev/null || true
}

now() {
	cut -d' ' -f1 /proc/uptime 2>/dev/null
}

i=0
while [ $i -lt 60 ] && ! grep -q ' /mnt/sd ' /proc/mounts; do
	sleep 1
	i=$((i + 1))
done
grep -q ' /mnt/sd ' /proc/mounts || exit 0

kmsg "armed (snapshot every ${INTERVAL}s, full dmesg, append-only)"

snapshot_count=0
while [ $snapshot_count -lt $MAX_SNAPSHOTS ]; do
	t0=$(now)

	# ONE ring-buffer read per tick, reused for both files below. The old
	# code ran `dmesg` twice per 3s tick, i.e. it read the entire kernel log
	# buffer 40 times a minute just to build two files out of it.
	snap=$(dmesg 2>/dev/null)

	# N3DS_BOOT_PROGRESS_FULL_LOG: append-only, every line, no tail.
	#
	# The first tick truncates OUT (this boot's log starts here); every tick
	# after that only ever appends, so nothing already on the card is
	# rewritten and no line is dropped.
	if [ "$snapshot_count" -eq 0 ]; then
		: > "$OUT" 2>/dev/null
		rm -f "$BP_COUNT_FILE" "$BP_FIRST_FILE" 2>/dev/null
	fi

	bp_total=$(printf '%s\n' "$snap" | wc -l 2>/dev/null)
	bp_first=$(printf '%s\n' "$snap" | head -n 1 2>/dev/null)
	bp_done=$(cat "$BP_COUNT_FILE" 2>/dev/null)
	[ -n "$bp_done" ] || bp_done=0
	bp_prev_first=$(cat "$BP_FIRST_FILE" 2>/dev/null)

	# Ring wrap: the oldest line we can still see is not the one we saw last
	# tick, so the kernel discarded lines we may never have written out.  Say
	# so explicitly and resynchronise from the start of the current ring --
	# a gap that is announced is evidence; a gap that is silent is a trap.
	if [ -n "$bp_prev_first" ] && [ "$bp_first" != "$bp_prev_first" ]; then
		echo "=== dmesg ring wrapped before uptime=$(cat /proc/uptime 2>/dev/null); lines above this point may be incomplete ===" >> "$OUT" 2>/dev/null
		bp_done=0
	fi

	{
		echo "=== $(date) uptime=$(cat /proc/uptime 2>/dev/null) ==="
		echo "=== free ==="; free
		# N3DS_BP_MEMDIAG: /data, /tmp and /dev are RAM.  On 2026-09-30 "shared"
		# grew ~1 MB/s to 134 MB and evicted program code until SD reads failed;
		# these three lines say where such growth lives next time.
		echo "mem: $(grep -E '^(MemAvailable|Shmem|AnonPages|Mapped|Cached):' /proc/meminfo 2>/dev/null | tr -s ' ' | tr '\n' ' ')"
		echo "ramfs kB: $(du -skx /data /tmp /dev 2>/dev/null | tr '\n' ' ') top: $(du -skx /data/data/* 2>/dev/null | sort -n | tail -n 3 | tr '\n' ' ')"
		echo "shmem by process kB: $(awk '/^Name:/ { n = $2 } /^RssShmem:/ { if ($2 > 1024) print $2, n }' /proc/[0-9]*/status 2>/dev/null | sort -rn | head -n 4 | tr '\n' ' ')"
		echo "=== loadavg ==="; cat /proc/loadavg 2>/dev/null
		echo "=== ps ==="; ps
		echo "=== PICA200 ==="
		echo "device: $(ls -l /dev/pica200 2>&1)"
		grep -iE 'pica|P3D|PPF|PSC' /proc/interrupts 2>/dev/null
		echo "$snap" | grep -iE 'ctr-pica|PICA200_PROBE'
		echo "=== dmesg lines $((bp_done + 1))..$bp_total ==="
		if [ "$bp_total" -gt "$bp_done" ]; then
			printf '%s\n' "$snap" | tail -n +$((bp_done + 1))
		fi
	} >> "$OUT" 2>/dev/null

	echo "$bp_total" > "$BP_COUNT_FILE" 2>/dev/null
	printf '%s\n' "$bp_first" > "$BP_FIRST_FILE" 2>/dev/null

	# Narrow Wi-Fi/SDIO view, kept separate from boot_progress.txt so the
	# bring-up story stays readable without scrolling the full kernel log.
	# The first snapshot truncates the previous boot's file; later snapshots
	# append a bounded, timestamped stage. Register-dump
	# payload words now carry AR6002 prefixes and are already included by WIFI_RE.
	# Keep the final marker after grep so an empty match still creates a useful
	# trace file.
	if [ "$snapshot_count" -eq 0 ]; then
		if {
			echo "=== $(date) uptime=$(cat /proc/uptime 2>/dev/null) stage=early ==="
			echo "=== filtered dmesg ==="
			if [ "$WIFI_INITIAL_LINES" -gt 0 ]; then
				printf '%s\n' "$snap" | grep -iE "$WIFI_RE" | tail -n "$WIFI_INITIAL_LINES" || true
			else
				printf '%s\n' "$snap" | grep -iE "$WIFI_RE" || true
			fi
			if [ -d /sys/class/net/wlan0 ]; then
				echo "=== wlan0=present ==="
			else
				echo "=== wlan0=absent ==="
			fi
			echo "=== end stage=early ==="
		} > "$WIFI_TMP" 2>/dev/null; then
			mv "$WIFI_TMP" "$WIFI_OUT" 2>/dev/null || true
		fi
	else
		if {
			echo "=== $(date) uptime=$(cat /proc/uptime 2>/dev/null) stage=delayed-$snapshot_count ==="
			printf '%s\n' "$snap" | grep -iE "$WIFI_RE" | tail -n "$WIFI_DELAYED_LINES" || true
			if [ -d /sys/class/net/wlan0 ]; then
				echo "=== wlan0=present ==="
			else
				echo "=== wlan0=absent ==="
			fi
			echo "=== end stage=delayed-$snapshot_count ==="
		} > "$WIFI_SNAPSHOT_TMP" 2>/dev/null; then
			cat "$WIFI_SNAPSHOT_TMP" >> "$WIFI_OUT" 2>/dev/null || true
			rm -f "$WIFI_SNAPSHOT_TMP"
		fi
	fi

	# N3DS_WIFI_TRACE_BRINGUP_SNAPSHOT: one-shot, taken the first interval in
	# which wlan0 exists, so the module-load window survives the sliding tail.
	if [ ! -f "$WIFI_BRINGUP_STAMP" ] && [ -d /sys/class/net/wlan0 ]; then
		if {
			echo "=== $(date) uptime=$(cat /proc/uptime 2>/dev/null) stage=bringup ==="
			printf '%s\n' "$snap" | grep -iE "$WIFI_RE" | tail -n "$WIFI_BRINGUP_LINES" || true
			echo "=== end stage=bringup ==="
		} >> "$WIFI_OUT" 2>/dev/null; then
			: > "$WIFI_BRINGUP_STAMP" 2>/dev/null || true
		fi
	fi

	# Cheap, targeted grep for the register-dump/crash markers so the actual
	# fault (PC/LR, which lines are %pS-resolved to a symbol name when
	# kallsyms has one) is easy to find without scrolling the dump -- and
	# survives even if the crash loop outruns the window above. Keeps its own
	# last-200-matches history rather than a single point-in-time snapshot,
	# since a respawn loop repeats the same report over and over and any one
	# tick could land mid-scroll.
	# N3DS_SD_FAILURE_CAPTURE: keep the narrow transport evidence in the small crash file too.
echo "$snap" | grep -E "N3DS_SD_RECOVERY|blk_update_request|I/O error, dev vda|FAT-fs|N3DS_DALVIK_ABORT|surfaceflinger|Unhandled fault|Code:|r10:|PC is at|LR is at|pc :|lr :|Unable to handle|Internal error|unhandled fatal signal|Comm:|process '.*' (exited|killing)" \
		2>/dev/null | tail -n 200 > "$CRASH_TMP" 2>/dev/null && mv "$CRASH_TMP" "$CRASH_OUT" 2>/dev/null

	# N3DS_BOOT_PROGRESS_FSYNC: without this, every tick after the first one
	# stays in FAT page cache and dies with the machine.  That is not a
	# theory: the 2026-09-12 capture has one tick at uptime=57 and nothing
	# after it, on a boot that ran for minutes -- which is why the
	# supplicant's own "attempt N died after Xs rc=" kmsg, emitted at
	# t~113 s, has never once appeared in a capture.
	fsync_file "$OUT"
	fsync_file "$WIFI_OUT"
	fsync_file "$CRASH_OUT"

	# N3DS_NO_GLOBAL_SYNC: a bare `sync` here blocks until every dirty page on
	# every SD-backed mount is flushed -- not just this script's own temp file.
	# On this storage stack (documented above: dexopt/logcat/writeback have
	# been seen blocked 120s+ on the same virtio-blk/FAT path) that turns a
	# 30s diagnostic tick into a global stall behind whatever else is slow to
	# write, which is exactly the kind of freeze this script exists to survive
	# and report on. The temp-file+rename above already guarantees a reader
	# never sees a half-written snapshot, and the scoped fsync_file() calls
	# above commit this script's own files without ever waiting on anyone
	# else's I/O -- which is the part `sync` gets wrong, not the flushing.
	t1=$(now)

	# SD-latency probe. Goes to /dev/kmsg only -- no card involved -- so it
	# survives exactly the failure it is measuring, and prints to the top
	# screen. A healthy tick is well under a second; the 2026-08-05 boot that
	# froze was, in hindsight, spending minutes here.
	#
	# N3DS_BP_QUIET_SNAPSHOT (#324): a healthy tick goes to dmesg at debug
	# level -- still in every capture, no longer on the top screen.  Only a
	# slow one (5 s or more, the storage path degrading) prints there.
	took=$(echo "$t0 $t1" | awk '{ printf "%.2f", $2 - $1 }')
	if echo "$took" | awk '{ exit !($1 >= 5) }'; then
		kmsg "SLOW snapshot took ${took}s (t=${t1}s)"
	else
		echo "<7>boot-progress: snapshot took ${took}s (t=${t1}s)" \
			> /dev/kmsg 2>/dev/null
	fi

	snapshot_count=$((snapshot_count + 1))
	sleep "$INTERVAL"
done
kmsg "bounded diagnostics complete after $snapshot_count snapshots"
