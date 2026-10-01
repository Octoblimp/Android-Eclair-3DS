#!/bin/sh
# Catch a lockup in the act and get the evidence off the device.
#
# Every lockup this project has hit has been diagnosed from a *photograph of
# the top screen*, because the two things that would actually answer the
# question -- the per-CPU backtraces the watchdog prints right after the
# one-line "BUG: soft lockup" summary -- scroll off the console immediately
# and the only dmesg capture ran either far too early (dump_bootlog.sh,
# ~50s) or on a fixed 320s delay that a wedged machine never reaches
# (bootlog_late.sh, now deleted).
#
# This polls dmesg instead and dumps everything the moment a lockup
# signature appears. Combined with kernel.softlockup_all_cpu_backtrace=1
# (set in init.rc's "on boot"), the dump contains a stack for *every* CPU,
# not just the ones the watchdog happened to name -- which is the missing
# piece: in lockup.jpg three of four CPUs are reported stuck and the fourth
# is silent, and the silent one is the one holding whatever they are all
# waiting on.
#
# 2026-08-05: a real trigger finally landed (uptime ~600s, first-ever
# boot to reach system_server's Binder round-trip with servicemanager) and
# the write to lockup_dump.txt got cut off at exactly 98304 bytes -- some
# further, total freeze killed the write itself mid-dmesg, before it ever
# reached the actual signature line (dmesg was still printing ~70s-old
# driver-probe chatter when it died, nowhere near the ~600s-uptime fault).
# One giant `dmesg > file` redirect means byte order in the ring buffer
# decides what survives a mid-write freeze, and the ring buffer's oldest
# surviving content is exactly what's least useful. Fixed by writing a
# small, cheap, high-value file FIRST (with its own fsync via `sync`)
# before ever starting the large unbounded full-ring-buffer dump, so a
# freeze during the big dump still leaves the compact signature intact on
# disk. The two are now separate files/redirects, not sections of one.
#
# Writes sd:/linux/lockup_dump.txt (compact, high-value, written+synced
# first) and sd:/linux/lockup_dump_full.txt (full ring buffer, best
# effort, written second) -- both always overwriting, no numbered-fallback
# spam (see dump_bootlog.sh's own postmortem on that).

# 2026-08-05 (later): two bugs found by reading the evidence this script
# actually produced on 2026-08-05.
#
# 1. The pattern only caught the ARM die() paths that print the literal string
#    "Oops" -- i.e. __do_kernel_fault()'s "Unable to handle kernel paging
#    request". A kernel-mode *external* abort does not go through there: it
#    goes do_DataAbort -> "Unhandled fault: ..." -> arm_notify_die -> die("")
#    -> "Internal error: : 1406", which contains none of the old keywords.
#    Given every DataAbort this port has captured lands on a dsb() inside a
#    TLB flush (the classic signature of an *imprecise* external abort being
#    synchronised by the barrier rather than reported at the offending store),
#    that was very likely the exact case being missed. Added "Internal error",
#    "Unhandled fault", "Unhandled prefetch abort" and "8<--- cut here".
#
# 2. `blocked for more than` (the hung-task warning) was in the same list as
#    the hard signatures, and any match made the watcher dump *and exit*. On
#    the 2026-08-05 boot a perfectly survivable 120s hung-task warning on
#    boot_progress.sh writing to FAT fired at t=369s, the watcher dumped and
#    quit, and nothing was armed for the rest of the boot. Hung tasks are now
#    a soft signature: they dump to their own file and the watcher stays up.
DUMP=/mnt/sd/linux/lockup_dump.txt
DUMP_FULL=/mnt/sd/linux/lockup_dump_full.txt
DUMP_SOFT=/mnt/sd/linux/hungtask_dump.txt
PATTERN='soft lockup|rcu_sched self-detected|rcu_sched detected|rcu: INFO: rcu|BUG: |Oops|Unable to handle kernel|Internal error|Unhandled fault|Unhandled prefetch abort|8<--- cut here|Kernel panic'
SOFT_PATTERN='blocked for more than'

kmsg() {
	echo "lockup-watch: $1" > /dev/kmsg 2>/dev/null
}

# Wait for the SD card before claiming we can write anything.
i=0
while [ $i -lt 60 ] && ! grep -q ' /mnt/sd ' /proc/mounts; do
	sleep 1
	i=$((i + 1))
done
if ! grep -q ' /mnt/sd ' /proc/mounts; then
	kmsg "/mnt/sd never mounted -- cannot save a dump, exiting"
	exit 0
fi

# 2026-08-05 (this session): 2s -> 5s. This loop reads the *entire* kernel
# ring buffer into a shell variable and forks two greps over it on every
# poll. At 2s that is 30 full ring-buffer reads a minute on a 268 MHz core,
# on top of boot_progress.sh doing the same thing and writing 50 KB to a FAT
# card every 3s. That boot's hung-task warning named boot_progress.sh stuck
# in fat_alloc_clusters, and this script then needed 45 s to commit a
# 130-byte header (lockup_dump.txt: kmsg trigger at t=370.0, header written
# at t=415.5, machine dead at t~416). A lockup that takes seconds to develop
# is still caught at 5s; the point of this watcher is to be *alive* when it
# fires, not to poll fast.
POLL=5

kmsg "armed (watching dmesg for lockups every ${POLL}s)"

soft_seen=0

while true; do
	# Snapshot the ring buffer ONCE per poll and match against the snapshot.
	# The old code ran `dmesg` again inside the dump to re-find the matching
	# lines, and on 2026-08-05 that produced a lockup_dump.txt whose
	# "matched signature lines" section was *empty*: between the detecting
	# grep and the dumping grep the ring buffer had wrapped the evidence
	# away. (The dyndbg firehose that made it wrap that fast is gone now,
	# but re-reading a ring buffer you have already matched is wrong
	# regardless.)
	snap=$(dmesg 2>/dev/null)

	if echo "$snap" | grep -qE "$SOFT_PATTERN"; then
		if [ "$soft_seen" = 0 ]; then
			soft_seen=1
			kmsg "hung-task warning seen -- $DUMP_SOFT (still watching)"
			{
				echo "=== hung task (soft signature, NOT a lockup) ==="
				echo "date: $(date)"
				echo "uptime: $(cat /proc/uptime 2>/dev/null)"
				echo
				echo "$snap" | grep -A25 -E "$SOFT_PATTERN" | tail -n 300
				echo; echo "=== ps ==="; ps
			} > "$DUMP_SOFT" 2>&1
			sync
		fi
	fi

	if echo "$snap" | grep -qE "$PATTERN"; then
		kmsg "LOCKUP SIGNATURE DETECTED -- dumping to $DUMP"

		# Small + high-value first, its own redirect, synced immediately --
		# this is the part that must survive even a freeze a fraction of a
		# second later.
		{
			echo "=== lockup_watch triggered ==="
			echo "date: $(date)"
			echo "uptime: $(cat /proc/uptime 2>/dev/null)"
			echo
			echo "=== matched signature lines + following 30 (last 400) ==="
			echo "$snap" | grep -A30 -E "$PATTERN" | tail -n 400
			echo
			echo "=== ps ==="
			ps
			echo
			echo "=== /proc/loadavg ==="; cat /proc/loadavg 2>/dev/null
			echo; echo "=== free ==="; free
			echo; echo "=== /proc/meminfo ==="; cat /proc/meminfo 2>/dev/null
			echo; echo "=== /proc/interrupts ==="; cat /proc/interrupts 2>/dev/null
			echo; echo "=== /proc/sched_debug (runqueues) ==="
			cat /proc/sched_debug 2>/dev/null
			echo
			echo "=== per-task state + kernel stack (R and D only) ==="
			for p in /proc/[0-9]*; do
				st=$(awk '/^State:/ {print $2}' "$p/status" 2>/dev/null)
				case "$st" in
				D|R)
					echo "--- $p state=$st comm=$(cat "$p/comm" 2>/dev/null)"
					cat "$p/stack" 2>/dev/null
					echo "  wchan: $(cat "$p/wchan" 2>/dev/null)"
					;;
				esac
			done
		} > "$DUMP" 2>&1
		sync
		kmsg "wrote $DUMP (compact) -- attempting full dmesg dump to $DUMP_FULL"

		# Large, unbounded, best-effort -- may still get cut off by the same
		# freeze, but the compact file above is already safe on disk by now.
		{
			echo "=== dmesg (full ring buffer) ==="
			dmesg
		} > "$DUMP_FULL" 2>&1
		sync
		kmsg "wrote $DUMP_FULL -- watcher exiting"
		exit 0
	fi
	sleep "$POLL"
done
