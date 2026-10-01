#!/bin/sh
#
# N3DS_BOOT_SOUND: play the power-on clip once, from its first sample to its
# last.
#
# It used to be a backgrounded `cat` inside bootanim.sh.  That tied the sound
# to the boot animation's lifetime -- SurfaceFlinger::bootFinished() does
# `setprop ctl.stop bootanim` and init kills that service the moment the first
# frame of UI is ready, which lands inside a 1.78 s clip.  As its own oneshot
# service the sound owns its own lifetime and finishes however long userspace
# takes to come up.
#
# It is also declared ahead of mediaserver in init.rc so that it reaches
# /dev/eac first.  AudioHardwareGeneric opens /dev/eac from its constructor,
# and before kernel #311 that open stopped the channel and zeroed the ring:
# the clip restarted from wherever this script had got to, which is why only
# its tail was ever heard.  The driver now refuses to reset a channel another
# writer has claimed, so the ordering here is belt and braces rather than the
# fix.
#
# The whole Android media stack is deliberately bypassed: this runs long before
# zygote, so there is no AudioFlinger to ask and no MediaPlayer to construct.
# /dev/eac is the ctr_csnd misc device and takes raw headerless 16-bit
# little-endian stereo PCM at the driver's pcm_rate (44100), which is exactly
# what scripts/build_audio_assets.sh writes into bootsound.pcm.

BOOT_PCM=/system/media/bootsound.pcm
LEAD=/sys/module/ctr_csnd/parameters/lead_ms
# The clip is 78336 frames and the ring holds 131072, so the whole thing fits
# with room to spare.
BOOT_LEAD_MS=2000
# How long to hold the channel after the last byte is written.  The clip is
# 1.78 s and it is written in well under a second, so the DMA is still playing
# when the writer finishes; ctr_csnd adds a 250 ms drain margin on top.  Four
# seconds covers the whole of that with room for an SD stall, and costs
# nothing -- init does not wait on a oneshot service.  Five since the silent
# tail below added a second to what is queued.
DRAIN_S=5
# N3DS_BOOT_SOUND_TAIL: one second of silence written after the clip, at 44100
# Hz stereo 16-bit, so the drain's stop can only ever land on silence.  The
# ring holds 2.97 s; clip plus tail is 2.78 s.
#
# N3DS_BOOT_SOUND_WHOLE_FRAMES (#320): the tail is written by dd in blocks that
# are whole stereo frames -- 10 x 17640 bytes = 44100 frames = 176400 bytes.
# It used to be `head -c 176400 /dev/zero`: busybox head flushes 1024 + 1 bytes
# per writev(), ctr_csnd returned 0 for the odd byte, and stdio retried that
# byte forever.  #318 and #319 both queued exactly 1024 bytes of tail and this
# script never reached "finished".  The kernel now keeps a split frame for the
# next write() as well (N3DS_CSND_WHOLE_WRITES); this keeps it from mattering.
TAIL_BS=17640
TAIL_COUNT=10

log() {
	echo "bootsound: $1" > /dev/kmsg 2>/dev/null
}

if [ ! -c /dev/eac ]; then
	log "no /dev/eac; silent boot"
	exit 0
fi
if [ ! -s "$BOOT_PCM" ]; then
	log "no $BOOT_PCM; silent boot"
	exit 0
fi

# Raise the write-ahead budget for the duration.  ctr_csnd's interactive
# default is 200 ms, which is right for a dialer keytone and wrong here: the SD
# card is being hammered by servicemanager, surfaceflinger and mediaserver at
# this exact moment, and a read stall longer than the lead lets the play cursor
# run past the writer and eat the middle of the clip.  At 2000 ms the entire
# file is buffered ahead of the cursor and no stall can underrun it.
OLD_LEAD=

# N3DS_BOOT_SOUND_PREWARM: read the clip once into the page cache before the
# channel is claimed, so the `cat` that feeds /dev/eac never waits on the SD
# card.  The lead above covers a stall *after* playback starts; this means
# there is nothing left to stall on.  313 KB, well under a second.
cat "$BOOT_PCM" > /dev/null 2>&1

if [ -w "$LEAD" ]; then
	OLD_LEAD=$(cat "$LEAD" 2>/dev/null)
	echo "$BOOT_LEAD_MS" > "$LEAD" 2>/dev/null
fi

# Open /dev/eac here and keep it open, rather than letting `cat` own the
# descriptor.
#
# ctr_csnd gives the channel to the first process that writes to it and holds
# that claim until the file is closed, which is what stops mediaserver
# resetting the ring mid-clip.  `cat` closes the moment the last byte is
# written -- about a second before the audio has actually been heard -- and
# the claim would have ended there, in the middle of the sound.  The clip is
# written through this inherited descriptor instead, so the claim belongs to
# this script and lasts until the drain below is over.  The kernel keeps the
# tail safe on its own now as well; this simply means it never has to.
exec 3> /dev/eac 2>/dev/null

log "playing $BOOT_PCM"

# N3DS_BOOT_SOUND_NO_KILL: no watchdog.  The rule (2026-09-30): the clip plays
# to its last sample and ends by itself; nothing may cut it short.  The old
# `sleep 15; kill -KILL` could only ever fire on a slow write -- exactly when
# audio was still owed -- and #318 hit it: "bootsound: finished" landed
# 20 s after "playing", i.e. the 15 s cap plus the 5 s drain.
# Nothing needs it.  ctr_csnd bounds every wait on the play cursor, so write()
# cannot block forever, and init does not wait on a oneshot service, so the
# boot never depends on this script finishing.
{ cat "$BOOT_PCM"; dd if=/dev/zero bs="$TAIL_BS" count="$TAIL_COUNT"; } >&3 2>/dev/null

# The channel plays on for as long as the queued audio lasts plus ctr_csnd's
# drain margin.  Hold both the descriptor and the raised budget until it has
# finished, rather than handing the tail back mid-clip.
sleep "$DRAIN_S"
exec 3>&-

if [ -n "$OLD_LEAD" ] && [ -w "$LEAD" ]; then
	echo "$OLD_LEAD" > "$LEAD" 2>/dev/null
fi
log "finished"
exit 0
