#!/usr/bin/env python3
"""N3DS_DSP_PIPE_BUFFER_READBACK: prove where the message actually landed.

The transport has now been checked twice against the real sysmodule, and the
third check settled the last open question in its favour: FUN_00105ed8 really
does write at `(desc[0] * 2) + write_offset`, so desc[0] is a DSP data *word*
address while the pointers beside it are byte offsets.  The arithmetic is
right.  What has never been shown is that the bytes arrive.

Every write in this path goes out over the PADR/PDATA port, and the only
evidence that port has ever written DSP data memory correctly is the
descriptor pointer writeback -- two bytes, at an address derived a completely
different way (from pipe_base, not from desc[0]).  If desc[0] is being
resolved wrong, or if the FIFO write drops a burst, the DSP would read four
zero bytes out of its buffer, acknowledge slot 5 exactly as the capture shows,
and produce no reply, because state 0 with no follow-up is not a command it
owes an answer to.  That is indistinguishable, in every capture so far, from a
firmware that simply ignores us.

Two reads settle it, and reads are free:

  * Read back the four bytes at the pipe 2 dir 1 write cursor.  If they are
    the message we sent, the ARM->DSP write path is proven end to end and the
    problem is the firmware's audio state machine.  If they are zeroes, the
    problem is the port, and every conclusion drawn from "the DSP ignored the
    message" for the last four sessions was drawn from a message the DSP never
    received.
  * Dump the head of the pipe 2 dir 0 buffer.  A reply the core wrote without
    advancing a pointer we can see -- or advanced in a field we are reading
    from the wrong offset -- shows up here as message-shaped bytes in a buffer
    the pointers still call empty.

Neither read touches a pointer, sends a mailbox word, or changes what the
core is asked to do.
"""
from a3ds_paths import A3DS_ROOT
import io
import sys

PATH = (f"{A3DS_ROOT}/third_party/linux/drivers/platform"
        "/nintendo3ds/ctr_dsp.c")

src = io.open(PATH, encoding="utf-8").read()
orig = src

helper = '''/*
 * N3DS_DSP_PIPE_BUFFER_READBACK.  The pipe buffers themselves, read straight
 * out of DSP data memory at the address the descriptor names, bypassing every
 * pointer the two sides disagree about.  `at` is a byte offset into the
 * buffer; the caller passes the cursor it cares about.
 */
static void ctr_dsp_pipe_buffer_dump(struct ctr_dsp *dsp, unsigned int pipe,
				     unsigned int dir, u16 at, size_t nbytes,
				     const char *what)
{
	u8 buf[16];
	u16 d[5];
	u32 addr;

	if (nbytes > sizeof(buf))
		nbytes = sizeof(buf);

	if (ctr_dsp_pipe_fetch(dsp, pipe, dir, d)) {
		dev_warn(dsp->dev, "pipe %u dir %u %s: descriptor unreadable\\n",
			 pipe, dir, what);
		return;
	}

	addr = (u32)d[0] * 2 + (at & 0x7fff);
	if (ctr_dsp_dmem_read_bytes(dsp, addr, buf, nbytes)) {
		dev_warn(dsp->dev,
			 "pipe %u dir %u %s: buffer at 0x%05x unreadable\\n",
			 pipe, dir, what, addr);
		return;
	}

	dev_info(dsp->dev, "pipe %u dir %u %s: DSP byte 0x%05x = %*ph\\n",
		 pipe, dir, what, addr, (int)nbytes, buf);
}

'''

anchor = "static void ctr_dsp_pipe_snapshot(struct ctr_dsp *dsp, unsigned int pipe,\n"
assert anchor in src, "snapshot anchor missing"
if "ctr_dsp_pipe_buffer_dump" not in src:
    src = src.replace(anchor, helper + anchor, 1)

# --- after Initialize: did our four bytes land where the DSP reads them? ----
old = '''	ctr_dsp_pipe_snapshot(dsp, DSP_AUDIO_PIPE, 1, "after Initialize");
	n = ctr_dsp_audio_wait_reply(dsp, 1000);
'''
new = '''	ctr_dsp_pipe_snapshot(dsp, DSP_AUDIO_PIPE, 1, "after Initialize");
	/*
	 * Offset 0, not the write cursor: the pipe started empty, so the
	 * message we just sent begins at the top of the buffer whether or not
	 * the DSP has since consumed it and moved the read pointer past it.
	 * Expect 00 00 00 00 for Initialize -- which is why the second read
	 * below, taken after Wakeup, is the one that proves the write path:
	 * Wakeup is state 2, and a buffer that reads back 02 is a buffer the
	 * ARM demonstrably wrote.
	 */
	ctr_dsp_pipe_buffer_dump(dsp, DSP_AUDIO_PIPE, 1, 0, 8,
				 "buffer after Initialize");
	ctr_dsp_pipe_buffer_dump(dsp, DSP_AUDIO_PIPE, 0, 0, 16,
				 "buffer after Initialize");
	n = ctr_dsp_audio_wait_reply(dsp, 1000);
'''
assert old in src, "post-Initialize anchor missing"
src = src.replace(old, new, 1)

# --- after Wakeup: state 2 is a value zeroed memory cannot fake -------------
old = '''		ctr_dsp_pipe_snapshot(dsp, DSP_AUDIO_PIPE, 1, "after Wakeup");
		n = ctr_dsp_audio_wait_reply(dsp, 1000);
'''
new = '''		ctr_dsp_pipe_snapshot(dsp, DSP_AUDIO_PIPE, 1, "after Wakeup");
		ctr_dsp_pipe_buffer_dump(dsp, DSP_AUDIO_PIPE, 1, 0, 8,
					 "buffer after Wakeup");
		n = ctr_dsp_audio_wait_reply(dsp, 1000);
'''
assert old in src, "post-Wakeup anchor missing"
src = src.replace(old, new, 1)

# --- the failure branch: the reply buffer, regardless of the pointers -------
old = '''		ctr_dsp_pipes_report(dsp);
		ctr_dsp_shared_dump(dsp, "after Initialize and Wakeup");
'''
new = '''		ctr_dsp_pipes_report(dsp);
		ctr_dsp_pipe_buffer_dump(dsp, DSP_AUDIO_PIPE, 0, 0, 16,
					 "reply buffer, pointers ignored");
		ctr_dsp_shared_dump(dsp, "after Initialize and Wakeup");
'''
assert old in src, "failure branch anchor missing"
src = src.replace(old, new, 1)

if src == orig:
    sys.stderr.write("no changes made\n")
    sys.exit(1)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + PATH)
