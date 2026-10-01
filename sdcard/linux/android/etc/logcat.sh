#!/bin/sh
# Persist Android's own log to the SD card.
#
# The real /system/bin/app_process links the real liblog, which writes every
# ALOG*/Log.i/Slog call to /dev/log/main -- a kernel char device (Phase 3's
# ported drivers/staging/android/logger.c), not stdout and not dmesg. There
# was no reader for it in this image at all, which is why every earlier boot
# had to use app_process_debug (liblog_fake, FAKE_LOG_DEVICE=1) and funnel
# stderr into a file just to see anything. That arrangement wrote an
# unbounded file into /tmp, i.e. tmpfs, i.e. unreclaimable RAM on a 256 MB
# device with no swap, for as long as system_server ran.
#
# logcat reads the device properly and rotates, so the cost is bounded and
# the data survives a lockup.
#
#   -v time   timestamps (the default "brief" format has none, and every
#             question we ask of this log is "what happened just before X")
#   -f/-r/-n  7 x 1 MB rotating files: logcat.txt, .1 .. .6.
#             It used to be 4 x 256 KB, and that was not enough history:
#             the Browser died at uptime 318 s on 2026-09-13 and by the
#             time the card was read, nine minutes later, the trace had
#             already been rotated out -- so the crash left nothing behind
#             but a kernel line saying a process had gone.  Rotation size
#             does not change how much is written, only how long it is
#             kept, so this costs SD space and nothing else.
#   *:I       persist INFO and above. The native stack deliberately keeps
#             NDEBUG off for bring-up visibility, which means Dalvik emits
#             thousands of V/JNI registration and class-link messages even
#             without -verbose:jni/class. Persisting those messages saturated
#             the already-slow FAT/virtio path and delayed the UI for minutes.
#             W/E/F diagnostics and normal I-level boot milestones remain;
#             temporarily remove this filter only for a targeted debug boot.
#
# Not oneshot, no exec-into-a-pipeline: logcat runs for the life of the boot
# and init restarts it if it dies.

LOGDIR=/mnt/sd/linux
BIN=/system/bin/logcat

if [ ! -x "$BIN" ]; then
	echo "logcat: $BIN missing -- Android logs will be invisible" \
		> /dev/kmsg 2>/dev/null
	# Don't respawn-loop init: sleep forever instead of exiting instantly.
	while true; do sleep 3600; done
fi

# /mnt/sd is mounted by the initramfs init.rc's "on init" block, but this
# service can be started before the mount settles on a slow card. Wait for
# it rather than writing into the (tmpfs) mountpoint underneath.
i=0
while [ $i -lt 30 ] && ! grep -q ' /mnt/sd ' /proc/mounts; do
	sleep 1
	i=$((i + 1))
done

if ! grep -q ' /mnt/sd ' /proc/mounts; then
	echo "logcat: /mnt/sd never mounted -- logging to /tmp instead" \
		> /dev/kmsg 2>/dev/null
	LOGDIR=/tmp
fi

echo "logcat: writing $LOGDIR/logcat.txt (7 x 1M rotating)" \
	> /dev/kmsg 2>/dev/null

exec "$BIN" -v time -f "$LOGDIR/logcat.txt" -r 1024 -n 6 "*:I"
