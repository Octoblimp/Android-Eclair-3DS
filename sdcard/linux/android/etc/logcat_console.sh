#!/bin/sh
# Live mirror of Android's log straight to the top-screen debug console
# (/dev/tty0, fb0), so a session can be diagnosed by reading the physical
# screen instead of having to pull logcat.txt off the SD card afterwards.
#
# This is a SECOND, independent logcat process from the one in logcat.sh --
# the logger char device (/dev/log/main) supports multiple concurrent
# readers, each with its own position, so this does not steal or duplicate
# what the SD-card-writing instance sees.
#
# Unlike the old app_process_debug/liblog_fake arrangement this does not
# reintroduce the unbounded-tmpfs-file bug: nothing here is written to a
# file at all, only to a tty, so there is no memory-growth risk.
#
# WHY the "*:W" filter (2026-08-05 freeze evidence): the real cost here is
# CPU -- fbcon=rotate:1 software-rotates every glyph and full-redraws on
# scroll, and heartbeat.sh (pure /dev/kmsg, no SD, no Android) stopped
# advancing at t~67s while the scheduler was still fine (ps worked at
# t~70s), pinning the stall in the printk/fbcon console path rather than
# the SD card. Every dalvikvm/asset/System.out V+I line goes through this
# mirror and burns a full glyph rotate + redraw on a 240x400 rotated
# console on one CPU. Filtering to W (warning) and above keeps errors
# readable on screen while dropping the classlink/parse firehose.
# Re-enable full verbosity only on demand for a specific debug boot; if a
# lockup reappears after that, this service is the first thing to disable.
#
# Not oneshot: runs for the life of the boot, init restarts it if it dies.

BIN=/system/bin/logcat

if [ ! -x "$BIN" ]; then
	echo "logcat_console: $BIN missing" > /dev/kmsg 2>/dev/null
	while true; do sleep 3600; done
fi

# N3DS_NO_TTY0_ECHO (#325): the VT keyboard handler feeds the console's own
# buttons into tty0, and while this redirect holds tty0 open the line
# discipline echoes every press onto the top screen. Nobody reads tty0's
# input, so turn its echo off.
/usr/bin/busybox stty -F /dev/tty0 -echo -icanon 2>/dev/null \
	|| stty -F /dev/tty0 -echo -icanon 2>/dev/null \
	|| echo "logcat_console: stty -echo failed" > /dev/kmsg 2>/dev/null

exec "$BIN" -v time "*:W" > /dev/tty0 2>&1
