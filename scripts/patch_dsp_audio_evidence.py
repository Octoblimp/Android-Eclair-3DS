#!/usr/bin/env python3
"""N3DS_DSP_AUDIO_EVIDENCE: stop guessing at the audio state machine.

The 09-12 capture is eight lines long and every one of them is good news
until the last:

  pipe table base: REP2=0x0c9f -> DSP data byte 0x0193e
  pipe 2 dir 1: buf 0x01c5e size 128 rd 0x0000 wr 0x0000 slot 0x05
  audio Initialize written to pipe 2 dir 1
  DSP semaphore 0x8000
  DSP notified slot 0x05 (pipe 2 dir 1)
  audio Wakeup written to pipe 2 dir 1
  DSP semaphore 0x8000
  DSP notified slot 0x05 (pipe 2 dir 1)
  no audio reply on pipe 2 dir 0 after Initialize and Wakeup

The core is running its mailbox service loop and answering within twenty
milliseconds, so this is not a dead DSP.  What the capture does not say is
the one thing that decides where to look next, and it does not say it three
times over:

  * Did the DSP *consume* the message?  Slot 0x05 is the ARM->DSP half of
    pipe 2, so that notification should mean "I advanced your read pointer",
    but the descriptor is never re-read, so rd could still be 0x0000 and the
    slot word could be something else entirely.
  * Did the DSP answer somewhere we are not looking?  Only pipe 2 dir 0 is
    checked afterwards; any of the other fifteen descriptors could have moved.
  * Did we simply give up too early?  ctr_dsp_audio_drain() waits 500 ms for
    the first mailbox word and then only 20 ms for the next, and the reply is
    read exactly once, a few milliseconds after the message went out.

Also removes a real hazard hiding in the second half: the Wakeup escalation
re-writes pipe 2 *without ever draining what the first message produced*, so
if the reply had shown up late it would have been read as a reply to Wakeup
instead -- or, worse, the pipe-full check would have been operating on a
descriptor whose read pointer the DSP was still moving.

None of this sends anything new at the core.  The message sequence is
unchanged; what changes is that the next capture can distinguish "the DSP
never answered" from "the DSP answered and we were not listening", which is
the fork this has been stuck on for four sessions.
"""
from a3ds_paths import A3DS_ROOT
import io
import sys

PATH = (f"{A3DS_ROOT}/third_party/linux/drivers/platform"
        "/nintendo3ds/ctr_dsp.c")

src = io.open(PATH, encoding="utf-8").read()
orig = src

helpers = '''/*
 * N3DS_DSP_AUDIO_EVIDENCE.  Three observations the old handshake never made.
 *
 * A descriptor snapshot is the only way to tell an acknowledged message from
 * an ignored one: the DSP advances the read pointer of pipe 2 dir 1 in its
 * own memory when it consumes, and that pointer is two bytes in a table we
 * can already read.  Printing it before and after each message costs one
 * word-sized port read and settles the question outright.
 */
static void ctr_dsp_pipe_snapshot(struct ctr_dsp *dsp, unsigned int pipe,
				  unsigned int dir, const char *when)
{
	u16 d[5];

	if (ctr_dsp_pipe_fetch(dsp, pipe, dir, d)) {
		dev_warn(dsp->dev, "pipe %u dir %u %s: descriptor unreadable\\n",
			 pipe, dir, when);
		return;
	}
	dev_info(dsp->dev,
		 "pipe %u dir %u %s: rd 0x%04x wr 0x%04x readable %u\\n",
		 pipe, dir, when, d[2], d[3], ctr_dsp_pipe_readable(d));
}

/*
 * The audio structures live at DSP data word 0x8000 and up -- that is what
 * the bit-15 addresses in the reply are, and it is the region the firmware
 * mixes into whether or not anyone is listening.  If those words are not all
 * zero, the audio task has run at least once and the missing piece is the
 * reply path; if they never change, it has not.
 */
static void ctr_dsp_shared_dump(struct ctr_dsp *dsp, const char *when)
{
	u16 w[8];

	if (ctr_dsp_dmem_read(dsp, 0x10000, w, ARRAY_SIZE(w))) {
		dev_warn(dsp->dev, "audio shared region %s: unreadable\\n", when);
		return;
	}
	dev_info(dsp->dev,
		 "audio shared region (DSP word 0x8000) %s: %04x %04x %04x %04x %04x %04x %04x %04x\\n",
		 when, w[0], w[1], w[2], w[3], w[4], w[5], w[6], w[7]);
}

/*
 * Wait for a reply the way something that expects one would: keep draining
 * mailbox 2 (every word of it, not just the first), keep re-reading the
 * descriptor, and only give up on a clock.  The old code read the pipe once,
 * milliseconds after the message went out, which cannot distinguish a core
 * that will never answer from one that answers on its next audio frame --
 * and an audio frame here is 5 ms of samples, not microseconds.
 *
 * Returns whatever ctr_dsp_audio_reply() returned, or 0 if nothing arrived.
 */
static int ctr_dsp_audio_wait_reply(struct ctr_dsp *dsp, unsigned int ms)
{
	unsigned int waited = 0;
	u16 last_rd = 0xffff, last_wr = 0xffff;

	for (;;) {
		u16 d[5];

		ctr_dsp_audio_drain(dsp, 2000);

		if (ctr_dsp_pipe_fetch(dsp, DSP_AUDIO_PIPE, 0, d) == 0) {
			if (d[2] != last_rd || d[3] != last_wr) {
				dev_info(dsp->dev,
					 "pipe %d dir 0 moved at %ums: rd 0x%04x wr 0x%04x readable %u\\n",
					 DSP_AUDIO_PIPE, waited, d[2], d[3],
					 ctr_dsp_pipe_readable(d));
				last_rd = d[2];
				last_wr = d[3];
			}
			if (ctr_dsp_pipe_readable(d))
				return ctr_dsp_audio_reply(dsp);
		}

		if (waited >= ms)
			return 0;
		msleep(20);
		waited += 20;
	}
}

'''

anchor = "static void ctr_dsp_audio_handshake(struct ctr_dsp *dsp)\n"
assert anchor in src, "handshake anchor missing"
if "ctr_dsp_audio_wait_reply" not in src:
    src = src.replace(anchor, helpers + anchor, 1)

old = '''	if (ctr_dsp_audio_msg(dsp, DSP_AUDIO_INITIALIZE, "Initialize"))
		return;
	ctr_dsp_audio_drain(dsp, 500000);
	n = ctr_dsp_audio_reply(dsp);

	/*
	 * One escalation, and only one.  If the firmware came up in its low
	 * power state it acknowledges Initialize without producing the address
	 * list, and Wakeup is the documented way out of that.  If neither
	 * produces a reply then the state machine is not where we think it is,
	 * and the next step is evidence, not more messages.
	 */
	if (n <= 0) {
		if (ctr_dsp_audio_msg(dsp, DSP_AUDIO_WAKEUP, "Wakeup"))
			return;
		ctr_dsp_audio_drain(dsp, 500000);
		n = ctr_dsp_audio_reply(dsp);
	}

	if (n <= 0) {
		dev_warn(dsp->dev,
			 "no audio reply on pipe %d dir 0 after Initialize and Wakeup; pipe transport is proven, the audio state machine is not\\n",
			 DSP_AUDIO_PIPE);
		return;
	}
'''

new = '''	ctr_dsp_shared_dump(dsp, "before Initialize");

	if (ctr_dsp_audio_msg(dsp, DSP_AUDIO_INITIALIZE, "Initialize"))
		return;
	/*
	 * The acknowledgement we care about is not the mailbox word, it is the
	 * read pointer of the pipe we just wrote.  If the DSP consumed the
	 * message, rd catches up with wr here; if it did not, wr has moved and
	 * rd has not, and the next message would stack up behind this one.
	 */
	ctr_dsp_audio_drain(dsp, 500000);
	ctr_dsp_pipe_snapshot(dsp, DSP_AUDIO_PIPE, 1, "after Initialize");
	n = ctr_dsp_audio_wait_reply(dsp, 1000);

	/*
	 * One escalation, and only one.  If the firmware came up in its low
	 * power state it acknowledges Initialize without producing the address
	 * list, and Wakeup is the documented way out of that.  If neither
	 * produces a reply then the state machine is not where we think it is,
	 * and the next step is evidence, not more messages.
	 */
	if (n <= 0) {
		if (ctr_dsp_audio_msg(dsp, DSP_AUDIO_WAKEUP, "Wakeup"))
			return;
		ctr_dsp_audio_drain(dsp, 500000);
		ctr_dsp_pipe_snapshot(dsp, DSP_AUDIO_PIPE, 1, "after Wakeup");
		n = ctr_dsp_audio_wait_reply(dsp, 1000);
	}

	if (n <= 0) {
		dev_warn(dsp->dev,
			 "no audio reply on pipe %d dir 0 after Initialize and Wakeup; pipe transport is proven, the audio state machine is not\\n",
			 DSP_AUDIO_PIPE);
		/*
		 * Everything that could still be true, printed once.  The
		 * descriptor table says whether the core answered on a pipe
		 * nobody was watching -- eight of the sixteen have never been
		 * looked at after a message -- and the shared region says
		 * whether the audio task ever ran at all.  Between them the
		 * next capture picks the branch instead of guessing at it.
		 */
		ctr_dsp_pipes_report(dsp);
		ctr_dsp_shared_dump(dsp, "after Initialize and Wakeup");
		return;
	}
'''
assert old in src, "handshake body anchor missing"
src = src.replace(old, new, 1)

if src == orig:
    sys.stderr.write("no changes made\n")
    sys.exit(1)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + PATH)
