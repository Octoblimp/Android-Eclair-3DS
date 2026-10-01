#!/bin/sh
# Run one bounded diagnostic supplicant invocation.
#
# Keep the daemon's normal service lifetime and exit status, but avoid an
# unbounded -d append to the FAT-backed diagnostic file.  Live output stays in
# tmpfs and a bounded snapshot is committed occasionally.  In particular, do
# not open/close a FAT file for every debug line: that amplified one Wi-Fi
# attempt into enough SD traffic to expose a dirty volume as repeated I/O
# errors and request-beyond-EOF spam.
#
# N3DS_WPA_SUPPLICANT_EARLY_EXEC: exec the real wpa_supplicant FIRST, before
# any /mnt/sd (FAT) touch. init reports this service "running" the instant it
# is forked, and Android's WifiMonitor opens the ctrl socket within
# milliseconds of that -- it does not wait for wpa_supplicant to actually be
# alive. The old script did mkdir/tail/mv log rotation against /mnt/sd/linux
# (known to stall for seconds under SD contention, see the SD write path
# collapse notes) before ever exec'ing the daemon, so the framework's connect
# attempt reliably lost the race with "No such file or directory" and Wi-Fi
# never associated. All SD-card diagnostic bookkeeping now happens only after
# the daemon is already forked and its ctrl socket is being created.
#
# N3DS_WPA_SUPPLICANT_BOOT_RETRY: at boot the daemon dies within a second of
# being forked and the framework reports "Failed to start supplicant daemon."
# exactly 6 s after wlan0 appears -- 5 s of which was this script's old
# "sleep 5" before its first health check, so the real lifetime was under a
# second. The same binary and the same config associate fine when started by
# hand minutes later, which is the signature of a bring-up race: ath6kl
# registers wlan0 before the target is ready to answer nl80211, and
# wpa_driver_nl80211_init() fails fatally instead of waiting. Rather than
# guess at the exact readiness gate, retry the daemon a few times whenever it
# dies in under SETTLE_SECONDS, and copy the tail of its output to /dev/kmsg
# so the reason survives even when the FAT card is never flushed.

LOG=/mnt/sd/linux/wpa_supplicant.log
PREV=/mnt/sd/linux/wpa_supplicant.log.prev
PREV_TMP=/mnt/sd/linux/.wpa_supplicant.log.prev.tmp
STATUS=/tmp/wpa_supplicant.status.$$
LIVE=/tmp/wpa_supplicant.live.$$
ROTATE_TMP=/tmp/wpa_supplicant.rotate.$$
SNAP_TMP=/mnt/sd/linux/.wpa_supplicant.log.tmp
PREV_BYTES=64512
LIVE_MAX_BYTES=196608
LIVE_KEEP_BYTES=131072
SNAPSHOT_SECONDS=30

# Bring-up retry budget. Worst case is
# MAX_ATTEMPTS * SETTLE_SECONDS + (MAX_ATTEMPTS - 1) * RETRY_GAP_SECONDS
# seconds = 8 s, which must stay under the 10 s that one
# libhardware_legacy wifi_start_supplicant_once() attempt is willing to wait
# (N3DS_WIFI_SUPPLICANT_START_RETRY).  If this budget ever exceeds that one,
# the HAL declares a timeout while this script is still retrying and then
# kills it, so the two retry loops fight instead of nesting.
SETTLE_SECONDS=2
MAX_ATTEMPTS=3
RETRY_GAP_SECONDS=1
KMSG_TAIL_LINES=20

# N3DS_WPA_SUPPLICANT_KEY_LOG: the live log is rotated and then snapshotted as
# a tail, so only the last ~100 s of a boot ever reaches the SD card.  Both
# associations in the 2026-09-01 capture happened well before that window and
# were lost.  This second file is selected by content instead of position: it
# holds the association / authentication / EAPOL / state / control-event /
# disconnect / failure lines for the whole boot, is never rotated, and stops
# growing once full.
KEY=/tmp/wpa_supplicant.key.$$
KEY_LOG=/mnt/sd/linux/wpa_supplicant.key.log
KEY_TMP=/mnt/sd/linux/.wpa_supplicant.key.tmp
KEY_MAX_BYTES=98304
KEY_RE='MLME|CTRL-EVENT|EAPOL|WPA:|RSN:|State:|ssociat|uthentic|eauthentic|isconnect|ignore list|Consecutive|Timeout|timed out|Failed|failed|SME:|nl80211: Connect|wlan0: Trying'
key_committed=0

: > "$LIVE" 2>/dev/null || exit 127
: > "$KEY" 2>/dev/null || exit 127

kmsg()
{
	# /dev/kmsg is the only sink that cannot be lost to an unflushed FAT
	# volume: it reaches dmesg, the top-screen console and boot_progress.
	echo "wpa_supplicant: $1" > /dev/kmsg 2>/dev/null || true
}

# Nothing between here and the first fork touches /mnt/sd; all of these live
# on ramfs/tmpfs.
{
	echo "=== wpa_supplicant start ==="
	echo "config=/data/misc/wifi/wpa_supplicant.conf verbosity=-d"
	echo "identity=$(id 2>&1)"
	grep '^ctrl_interface=' /data/misc/wifi/wpa_supplicant.conf 2>&1 || true
	ls -ld /data/misc/wifi /data/misc/wifi/sockets \
		/data/system/wpa_supplicant 2>&1 || true
	if [ -d /sys/class/net/wlan0 ]; then
		echo "wlan0=present at diag start"
	else
		echo "wlan0=absent at diag start"
	fi
} >> "$LIVE"

# N3DS_WPA_PREFORK_KMSG: $LIVE is tmpfs and is only copied to /mnt/sd at the
# very end of this script.  A supplicant that dies in under two seconds means
# that copy never carries anything useful, so every pre-fork fact has been
# invisible in the captures so far.  /dev/kmsg survives an unflushed volume.
while IFS= read -r _line; do
	kmsg "prefork| $_line"
done < "$LIVE"

if [ ! -r /data/misc/wifi/wpa_supplicant.conf ]; then
	kmsg "FATAL: /data/misc/wifi/wpa_supplicant.conf missing or unreadable"
fi
[ -d /sys/class/net/wlan0 ] || kmsg "WARNING: wlan0 absent at diag start"

start_logger()
{
	(
		/usr/sbin/wpa_supplicant -Dnl80211 -d -t -iwlan0 \
			-c/data/misc/wifi/wpa_supplicant.conf 2>&1
		rc=$?
		echo "$rc" > "$STATUS"
		exit "$rc"
	) | awk -v out_path="$LIVE" -v tmp_path="$ROTATE_TMP" \
		-v max="$LIVE_MAX_BYTES" -v keep="$LIVE_KEEP_BYTES" \
		-v key_path="$KEY" -v key_max="$KEY_MAX_BYTES" -v key_re="$KEY_RE" \
		-v bytes="0" '
	{
		print $0 >> out_path
		close(out_path)
		bytes += length($0) + 1
		if (key_bytes < key_max && $0 ~ key_re) {
			print $0 >> key_path
			close(key_path)
			key_bytes += length($0) + 1
		}
		if (bytes > max) {
			cmd = "tail -c " keep " " out_path " > " tmp_path \
			      " && mv -f " tmp_path " " out_path
			if (system(cmd) == 0)
				bytes = keep
			close(out_path)
		}
	}' &

	logger_pid=$!
}

report_failure_to_kmsg()
{
	kmsg "--- attempt $1: last $KMSG_TAIL_LINES lines ---"
	tail -n "$KMSG_TAIL_LINES" "$LIVE" 2>/dev/null | while IFS= read -r _line; do
		kmsg "| $_line"
	done
	kmsg "--- attempt $1: end ---"
}

# N3DS_WPA_PREFLIGHT: these two used to happen only *between* retries, which
# is useless on the autostart path -- attempt 1 is the one that has to work.
# wlan0 can be registered and still administratively down when the framework
# starts us (ath6kl brings the netdev up from its own worker), and
# /data/system/wpa_supplicant only exists because init.rc made it, so a /data
# that was recreated after init ran leaves the control interface with nowhere
# to bind.  Both are cheap and idempotent; do them before the first fork.
mkdir -p /data/system/wpa_supplicant 2>/dev/null || true
chown wifi:wifi /data/system/wpa_supplicant 2>/dev/null || \
	chown wifi.wifi /data/system/wpa_supplicant 2>/dev/null || true
chmod 0770 /data/system/wpa_supplicant 2>/dev/null || true
ifconfig wlan0 up 2>/dev/null || true
if [ -r /sys/class/net/wlan0/flags ]; then
	kmsg "preflight wlan0 flags=$(cat /sys/class/net/wlan0/flags 2>/dev/null) operstate=$(cat /sys/class/net/wlan0/operstate 2>/dev/null)"
else
	kmsg "preflight wlan0 has no sysfs entry"
fi

# Fork the real daemon immediately; nothing above this point touches /mnt/sd.
attempt=1
supplicant_alive=0
while : ; do
	: > "$STATUS" 2>/dev/null || true
	start_logger

	waited=0
	while [ "$waited" -lt "$SETTLE_SECONDS" ]; do
		kill -0 "$logger_pid" 2>/dev/null || break
		sleep 1
		waited=$((waited + 1))
	done

	if kill -0 "$logger_pid" 2>/dev/null; then
		supplicant_alive=1
		if [ "$attempt" -gt 1 ]; then
			kmsg "attempt $attempt is alive"
		fi
		break
	fi

	wait "$logger_pid" 2>/dev/null
	if [ -s "$STATUS" ]; then
		early_rc=$(cat "$STATUS")
	else
		early_rc=unknown
	fi
	kmsg "attempt $attempt died after ${waited}s rc=$early_rc"
	report_failure_to_kmsg "$attempt"

	if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
		break
	fi
	attempt=$((attempt + 1))
	# Give the driver another chance to finish bring-up, and make sure the
	# interface is administratively up before the next try.
	ifconfig wlan0 up 2>/dev/null || true
	sleep "$RETRY_GAP_SECONDS"
	echo "=== retrying wpa_supplicant, attempt $attempt ===" >> "$LIVE"
done

if [ "$supplicant_alive" = "0" ]; then
	kmsg "giving up after $MAX_ATTEMPTS attempts"
fi

# Everything below is diagnostic-only and may block on SD I/O without
# delaying the daemon that Android is already racing to connect to.
mkdir -p /mnt/sd/linux 2>/dev/null
if [ -f "$LOG" ]; then
	# Cap any file left by an older unbounded logger before rotating it.
	if tail -c "$PREV_BYTES" "$LOG" > "$PREV_TMP" 2>/dev/null; then
		mv -f "$PREV_TMP" "$PREV" 2>/dev/null || true
	else
		: > "$PREV_TMP"
		mv -f "$PREV_TMP" "$PREV" 2>/dev/null || true
	fi
	rm -f "$LOG"
fi
: > "$LOG" 2>/dev/null || {
	LOG=/tmp/wpa_supplicant.log
	SNAP_TMP=/tmp/wpa_supplicant.log.tmp
}

snapshot_key()
{
	# N3DS_WPA_SUPPLICANT_KEY_LOG: the key log stops growing once it is full,
	# so this writes the card a handful of times per boot and then never
	# again.  Skipping unchanged copies is the whole point -- an SD write on
	# every snapshot is what the tail snapshot already costs.
	key_size=$(wc -c < "$KEY" 2>/dev/null) || return 0
	[ -n "$key_size" ] || return 0
	[ "$key_size" -gt "$key_committed" ] 2>/dev/null || return 0
	if cp "$KEY" "$KEY_TMP" 2>/dev/null; then
		if mv -f "$KEY_TMP" "$KEY_LOG" 2>/dev/null; then
			key_committed=$key_size
		fi
	fi
}

snapshot()
{
	if [ -d /mnt/sd/linux ]; then
		LOG=/mnt/sd/linux/wpa_supplicant.log
		SNAP_TMP=/mnt/sd/linux/.wpa_supplicant.log.tmp
		KEY_LOG=/mnt/sd/linux/wpa_supplicant.key.log
		KEY_TMP=/mnt/sd/linux/.wpa_supplicant.key.tmp
	else
		KEY_LOG=/tmp/wpa_supplicant.key.log
		KEY_TMP=/tmp/wpa_supplicant.key.tmp
	fi
	if tail -c "$LIVE_KEEP_BYTES" "$LIVE" > "$SNAP_TMP" 2>/dev/null; then
		mv -f "$SNAP_TMP" "$LOG" 2>/dev/null || true
	fi
	snapshot_key
}

# Preserve a useful startup trace quickly, then snapshot only occasionally.
# A TERM/HUP from init also gets one final best-effort snapshot.
trap 'snapshot; exit 143' HUP INT TERM

# One snapshot right away: if the daemon never survived bring-up, this is the
# only copy of why, and the monitor loop below would never run.
snapshot
while kill -0 "$logger_pid" 2>/dev/null; do
	sleep "$SNAPSHOT_SECONDS"
	snapshot
done
wait "$logger_pid"

if [ -s "$STATUS" ]; then
	rc=$(cat "$STATUS")
else
	rc=127
fi
echo "=== wpa_supplicant exit status=$rc ===" >> "$LIVE"
snapshot
sync
rm -f "$STATUS" "$ROTATE_TMP" "$LIVE" "$SNAP_TMP" "$KEY" "$KEY_TMP"
exit "$rc"
