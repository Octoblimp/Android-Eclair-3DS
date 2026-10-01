/* SPDX-License-Identifier: MIT
 *
 * dsp_chime -- best-effort boot chime over the ctr_dsp misc device.
 *
 * WHAT THIS DOES, EXACTLY: it opens /dev/ctr_dsp0, queries
 * CTR_DSP_IOC_GET_READY (which reflects whether ctr_dsp.c's firmware boot
 * handshake in ctr_dsp_upload_firmware() actually completed on this boot),
 * and reports the answer.  It writes nothing.  Until 2026-09-12 it also
 * pushed a synthesized waveform into DSP data WRAM at word address 0; see
 * N3DS_DSP_CHIME_NO_LONGER_POKES below for why that had to stop.
 *
 * WHAT THIS DOES *NOT* CLAIM: that anything is audible.  The ARM11-to-DSP
 * pipe protocol has since been transcribed out of the Horizon dsp sysmodule
 * and implemented in ctr_dsp.c, so the transport and the handshake are no
 * longer guesswork -- but a firmware that answers an Initialize is still not
 * a speaker that makes a noise.  Audible playback is UNVERIFIED until someone
 * captures it on hardware.
 *
 * SAFETY CONTRACT: this must never fail, hang, or delay boot. Every
 * failure path below -- missing device node, DSP never became ready, any
 * ioctl error -- is logged (to stderr, which boot scripts redirect to
 * /dev/kmsg) and treated as a silent no-op. This program always exits 0.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#include <linux/ctr_dsp.h>

int main(void)
{
	int fd;
	__u32 ready = 0;

	fd = open("/dev/ctr_dsp0", O_RDWR | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr,
			"dsp_chime: /dev/ctr_dsp0 unavailable (%s); no chime, boot continues\n",
			strerror(errno));
		return 0;
	}

	if (ioctl(fd, CTR_DSP_IOC_GET_READY, &ready) < 0) {
		fprintf(stderr,
			"dsp_chime: GET_READY failed (%s); no chime, boot continues\n",
			strerror(errno));
		close(fd);
		return 0;
	}

	if (!ready) {
		fprintf(stderr,
			"dsp_chime: DSP not ready (firmware boot handshake did not complete); no chime\n");
		close(fd);
		return 0;
	}

	/*
	 * N3DS_DSP_CHIME_NO_LONGER_POKES.
	 *
	 * This used to synthesize a square wave and push 800 words into DSP
	 * data WRAM at word address 0.  That was defensible while nothing was
	 * known about the firmware's memory layout and nothing else was using
	 * the core.  It is not defensible now.
	 *
	 * The 2026-09-12 capture parsed a real pipe table at DSP data byte
	 * 0x0193e, with eight descriptors and sixteen contiguous 128-byte
	 * buffers above it, and the kernel now completes an audio Initialize
	 * handshake with the running firmware during probe.  Words 0..0x31f --
	 * precisely what this wrote over -- sit below every data segment the
	 * firmware image loads, which on a Teak build is where the stack and
	 * scratch live.  Dropping a waveform there at t=44s is not a chime.
	 * It is corruption of a core that is now doing real work, and it would
	 * make every later audio result unreproducible.
	 *
	 * The transport it exercised is no longer unproven either: the driver
	 * reads and writes DSP data space over this same FIFO port on every
	 * boot, and the pipe layer depends on it.  So there is nothing left
	 * for a poke to demonstrate, and a running firmware to lose by it.
	 *
	 * Audible output stays UNVERIFIED, and for the same reason as before:
	 * a completed handshake is not a sound.  What changed is where the
	 * next step belongs -- in ctr_dsp.c, driven by the structure addresses
	 * the firmware itself returns, not in a userspace poke at a guessed
	 * address.
	 */
	fprintf(stderr,
		"dsp_chime: DSP ready -- firmware booted and the pipe transport is live. "
		"No memory poke is performed: audible playback is UNVERIFIED and the "
		"audio path is driven from the kernel now, not from here\n");
	close(fd);
	return 0;
}
