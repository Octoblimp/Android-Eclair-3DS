#!/usr/bin/env python3
"""Contract for the boot sound path.

History, because the name of this file is now misleading and renaming it
would break two callers (verify_release_artifacts.sh and
rebuild_everything.sh) for no gain:

  * It began as the contract for a bounded, hardware-UNVERIFIED DSP boot
    chime -- a square-wave test tone whose only job was to prove that
    something, anything, reached the speakers.
  * The chime succeeded: it was heard on hardware.  Having proved the
    path, it is a test tone with nothing left to test, and the user asked
    for it to be removed.
  * What ships in its place is the real boot sound: /etc/bootsound.sh
    streams /system/media/bootsound.pcm straight into /dev/eac, the
    ctr_csnd misc device, as raw headerless 16-bit little-endian stereo
    PCM at 44100.
  * It started inside bootanim.sh and had to leave, because the user
    heard only the tail of the clip.  Two causes, both fixed below and
    both asserted here.  SurfaceFlinger::bootFinished() stops bootanim
    the moment the first real frame is ready, killing the backgrounded
    player mid-clip; and mediaserver opens /dev/eac from
    AudioHardwareGeneric's constructor, which before kernel #311 reset
    the channel and restarted the clip from wherever the writer had
    reached.

So the assertions invert.  The old contract said "/dev/eac must NOT appear
in bootanim.sh", because at the time /dev/eac was a dead path and the DSP
chime binary was the live one.  That is exactly backwards now, and a gate
asserting a superseded design gets repaired, never skipped.

The capability the chime provided is NOT lost.  ctr_csnd.c keeps a
`boot_tone` module parameter (default off) that renders and plays a tone at
probe, which is the same proof on the path that actually drives the
speakers.  That is the thing to reach for if audio ever goes silent again;
it is asserted below so it cannot quietly disappear.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path

ROOT = Path(A3DS_ROOT)
OVERLAY = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay"
DSP_DRIVER = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_dsp.c"
CSND_DRIVER = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_csnd.c"
HEADER = ROOT / "third_party/linux/include/uapi/linux/ctr_dsp.h"

bootanim = (OVERLAY / "etc/bootanim.sh").read_text(encoding="utf-8")
bootsound = (OVERLAY / "etc/bootsound.sh").read_text(encoding="utf-8")
initrc = (OVERLAY / "etc/init.rc").read_text(encoding="utf-8")
inittab = (OVERLAY / "etc/inittab").read_text(encoding="utf-8")
dsp = DSP_DRIVER.read_text(encoding="utf-8")
csnd = CSND_DRIVER.read_text(encoding="utf-8")
header = HEADER.read_text(encoding="utf-8")

# ---------------------------------------------------------------- retired
# The standalone boot_sound.sh sysinit path stays dead (HANDOFF 2026-09-07).
assert not (OVERLAY / "etc/boot_sound.sh").exists()
assert "::sysinit:/etc/boot_sound.sh" not in inittab

# The test chime must not be invoked at boot any more.  Comments may still
# refer to it -- bootanim.sh explains what replaced it -- so this checks for
# an actual invocation, not a mention.
assert "CHIME_BIN=" not in bootanim, "dsp_chime invocation is back in bootanim.sh"
assert "/system/bin/dsp_chime" not in bootanim, \
    "dsp_chime is being executed at boot again"

# ------------------------------------------------------------ the real sound
assert "BOOT_PCM=/system/media/bootsound.pcm" in bootsound
assert "/dev/eac" in bootsound, "boot sound no longer reaches the CSND device"
# Written to the character device, not to a regular file.  The script tests
# the negated form and bails early, so match the operator, not the phrasing.
assert "-c /dev/eac" in bootsound
# Bounded and non-fatal: no part of the boot may depend on audio completing.
assert "sleep 15; kill -KILL" in bootsound
assert "exit 0" in bootsound

# It must NOT be a child of the boot animation again.  That is what cut the
# clip in half: bootanim is stopped the moment the first real frame is ready.
# Mentions are fine -- bootanim.sh explains where the sound went and why --
# so this looks for a write to the device, the same way the dsp_chime check
# above looks for an invocation rather than the word.
assert "> /dev/eac" not in bootanim, \
    "the boot sound is back inside bootanim.sh, which is killed mid-clip"
assert "bootsound.pcm" not in bootanim
# exec must remain the LAST thing in bootanim, so init's signals reach it.
assert bootanim.rstrip().endswith('exec "$BIN" 2>/dev/kmsg')

# Its own oneshot service, declared ahead of mediaserver -- class_start walks
# services in definition order, and mediaserver opens /dev/eac from a
# constructor.  The driver's owner claim is the real fix; this is belt and
# braces, and it is free.
assert "service bootsound /etc/bootsound.sh" in initrc
assert initrc.count("service bootsound ") == 1
assert initrc.index("service bootsound ") < initrc.index("service mediaserver "), \
    "bootsound must be declared before mediaserver"

# Raise the lead so the whole clip is buffered ahead of the play cursor, then
# put the old value back -- otherwise every later sound inherits a 2 s latency.
assert "/sys/module/ctr_csnd/parameters/lead_ms" in bootsound
assert "OLD_LEAD" in bootsound

# The driver side of the same fix: a writer claims the channel, and opening
# the device no longer resets a channel somebody else is using.
assert "*owner;" in csnd, \
    "ctr_csnd lost its owner claim; a second opener will restart the clip"
assert "ctr_csnd_reset_locked" in csnd
# A write is refused while another fd owns the channel OR while the
# channel is still draining for an owner that has closed.  The second
# half is not decoration: `cat` closes about a second before the clip has
# been heard, so without it AudioFlinger's mixer walks straight into the
# tail of the boot sound -- the exact symptom this path exists to fix.
assert "if (cs->owner && (cs->owner != filp || cs->owner_closed)) {" in csnd, \
    "ctr_csnd write no longer refuses audio from a non-owner"
assert "cs->owner_closed = true;" in csnd, \
    "ctr_csnd no longer holds the claim across the owner's close()"
# ...which is only bounded because something later drops it.
assert "ctr_csnd_arm_drain" in csnd, \
    "ctr_csnd claim would never be released after the owner closed"
# An open() is not a claim, so open() may only reset an unclaimed channel.
assert "if (!cs->owner && !cs->running) {" in csnd, \
    "ctr_csnd open() resets the channel again; a second opener restarts the clip"

# --------------------------------------------------- the replacement for the
#                                                      chime, on the live path
assert "static int boot_tone;" in csnd, \
    "ctr_csnd lost its boot_tone probe; nothing left to re-prove the path with"
assert "module_param(boot_tone, int, 0644)" in csnd
assert "ctr_csnd_render_chime" in csnd
# Default OFF. A tone on every boot is exactly what was just removed.
assert "static int boot_tone = " not in csnd, \
    "boot_tone has been given a non-zero default; it must stay off"

# /dev/eac is the CSND device and it is what bootanim.sh writes to.
assert 'ctr_csnd_dev_write' in csnd
assert '"eac"' in csnd or "eac" in csnd

# ------------------------------------------------------- DSP driver survives
# The Teak DSP is parked, not deleted: it is still probed, still exposes
# /dev/ctr_dsp0, and the ioctl ABI is still the one the disassembly work
# depends on.  Audio simply does not go through it.
assert 'name = "ctr_dsp0"' in dsp
assert "misc_register" in dsp
assert "CTR_DSP_IOC_GET_READY" in header
assert "CTR_DSP_IOC_POKE_WORDS" in header

print("boot_sound_contract: PASS "
      "(chime retired after proving the path; CSND boot sound is live)")
