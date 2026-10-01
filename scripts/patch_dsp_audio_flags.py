#!/usr/bin/env python3
"""Kernel #303: the pipe-2 audio message carries a flags halfword, not padding.

Recovered from the ARM11 `dsp` sysmodule disassembly in
scratch/dsp-code-analysis/corpus/, three linked sites:

  FUN_00104b28 @ 0x00104f44  the WriteProcessPipe IPC dispatcher
        ldr  r1,[r4,#0x4]         pipe number from the request
        ldr  r2,[r4,#0x10]        the caller's buffer
        cmp  r1,#0x2
        beq  0x00104f64
        cmp  r1,#0x3
        bne  0x00104f80
    0x00104f64 (pipe 2)  ldr r12,[0x1054b0]  ldrh r12,[r12,#0]
                         strh r12,[r2,#0x2]      <- bytes 2-3 of the message
    0x00104f74 (pipe 3)  same value
                         strh r12,[r2,#0x6]      <- bytes 6-7 of the message
        bl   0x00106794           then WriteProcessPipe

  literal 0x1054b0 = 0x00109002, a u16 global.

  FUN_00100700 @ 0x0010074c  module init, the only writer of that global
        bl   0x00100ce8
        cmp  r0,#0x0
        movne r0,#0x2
        strh r0,[r4,#0x2]         r4 = 0x00109000

  FUN_00100ce8 / FUN_00101208 / FUN_001016e4  a once-cached console property:
        one 0-argument IPC, header 0x040A0000, result byte taken from
        cmdbuf[2] and cached at 0x00109084.

So the audio message is not {state, 0, 0, 0} with three pad bytes.  It is a
u16 state followed by a u16 flags, and the shipping sysmodule sends flags = 0
or flags = 2 depending on that cached byte.  Both are legitimate values a real
console puts on the wire; we have been sending one of the two and have no way
to know which one this unit's firmware expects.

This adds the other one as a bounded last escalation, after Initialize and
Wakeup at flags 0 have both gone unanswered.  It is not a guess about the
protocol shape -- it is the same message the same firmware accepts from
Horizon on some hardware -- and it costs one more 4-byte write on a boot that
has already failed.
"""
from a3ds_paths import A3DS_ROOT
import io
import sys

PATH = (f"{A3DS_ROOT}/third_party/linux/drivers/platform/"
        "nintendo3ds/ctr_dsp.c")

src = io.open(PATH, encoding="utf-8").read()
orig = src

if "N3DS_DSP_AUDIO_FLAGS" in src:
    sys.exit("already patched")

# ---------------------------------------------------------------- 1. the msg
OLD_MSG = """#define DSP_AUDIO_PIPE\t\t2

static int ctr_dsp_audio_msg(struct ctr_dsp *dsp, u8 state, const char *name)
{
\tu8 msg[4] = { state, 0, 0, 0 };
\tint ret;
"""

NEW_MSG = """#define DSP_AUDIO_PIPE\t\t2

/*
 * N3DS_DSP_AUDIO_FLAGS.  The four bytes are not a state byte and three pads.
 * FUN_00104b28, the sysmodule's WriteProcessPipe dispatcher, overwrites bytes
 * 2-3 of every pipe-2 message (and bytes 6-7 of every pipe-3 message) with a
 * u16 it caches at 0x00109002:
 *
 *   0x00104f64  ldr r12,[0x1054b0]   ; -> 0x00109002
 *               ldrh r12,[r12,#0x0]
 *               strh r12,[r2,#0x2]   ; r2 = the caller's buffer
 *
 * and FUN_00100700, the only writer of that global, sets it at module init to
 * 2 or 0 and nothing else:
 *
 *   0x0010074c  bl 0x00100ce8        ; one cached console property, a byte
 *               cmp r0,#0x0
 *               movne r0,#0x2
 *               strh r0,[r4,#0x2]    ; r4 = 0x00109000
 *
 * So the message is { u16 state, u16 flags } and a real console sends flags 0
 * or flags 2.  Which one depends on a property this driver cannot query --
 * the answer comes back over an IPC to a service that does not exist here --
 * so the value is a parameter rather than a constant, and the handshake tries
 * the other one rather than assuming.
 */
#define DSP_AUDIO_FLAGS_A\t0
#define DSP_AUDIO_FLAGS_B\t2

static int ctr_dsp_audio_msg(struct ctr_dsp *dsp, u8 state, u16 flags,
\t\t\t     const char *name)
{
\tu8 msg[4] = { state, 0, flags & 0xff, flags >> 8 };
\tint ret;
"""

assert OLD_MSG in src, "audio_msg prologue not found"
src = src.replace(OLD_MSG, NEW_MSG, 1)

OLD_LOG = """\tdev_info(dsp->dev, "audio %s written to pipe %d dir 1\\n",
\t\t name, DSP_AUDIO_PIPE);
\treturn 0;
}"""
NEW_LOG = """\tdev_info(dsp->dev, "audio %s (flags %u) written to pipe %d dir 1\\n",
\t\t name, flags, DSP_AUDIO_PIPE);
\treturn 0;
}"""
assert OLD_LOG in src, "audio_msg log line not found"
src = src.replace(OLD_LOG, NEW_LOG, 1)

# ------------------------------------------------------- 2. the two callers
OLD_INIT = ("\tif (ctr_dsp_audio_msg(dsp, DSP_AUDIO_INITIALIZE, "
            '"Initialize"))\n\t\treturn;')
NEW_INIT = ("\tif (ctr_dsp_audio_msg(dsp, DSP_AUDIO_INITIALIZE,\n"
            "\t\t\t      DSP_AUDIO_FLAGS_A, \"Initialize\"))\n\t\treturn;")
assert OLD_INIT in src, "Initialize call not found"
src = src.replace(OLD_INIT, NEW_INIT, 1)

OLD_WAKE = ('\t\tif (ctr_dsp_audio_msg(dsp, DSP_AUDIO_WAKEUP, "Wakeup"))\n'
            "\t\t\treturn;")
NEW_WAKE = ("\t\tif (ctr_dsp_audio_msg(dsp, DSP_AUDIO_WAKEUP,\n"
            "\t\t\t\t      DSP_AUDIO_FLAGS_A, \"Wakeup\"))\n"
            "\t\t\treturn;")
assert OLD_WAKE in src, "Wakeup call not found"
src = src.replace(OLD_WAKE, NEW_WAKE, 1)

# --------------------------------------------- 3. the flags-2 escalation
OLD_GIVEUP = """\tif (n <= 0) {
\t\tdev_warn(dsp->dev,
\t\t\t "no audio reply on pipe %d dir 0 after Initialize and Wakeup; pipe transport is proven, the audio state machine is not\\n",
\t\t\t DSP_AUDIO_PIPE);"""

NEW_GIVEUP = """\t/*
\t * The last thing that is still a transcription rather than a guess: the
\t * same Initialize, with the flags halfword the sysmodule would have
\t * patched in on the other kind of console.  If this one answers, the
\t * message body was the whole problem and the transport was never at
\t * fault; if it does not, flags are ruled out for good and the next
\t * capture is about the core, not the wire.
\t */
\tif (n <= 0) {
\t\tif (ctr_dsp_audio_msg(dsp, DSP_AUDIO_INITIALIZE,
\t\t\t\t      DSP_AUDIO_FLAGS_B, "Initialize"))
\t\t\treturn;
\t\tctr_dsp_audio_drain(dsp, 500000);
\t\tctr_dsp_pipe_snapshot(dsp, DSP_AUDIO_PIPE, 1,
\t\t\t\t      "after Initialize flags 2");
\t\tctr_dsp_pipe_buffer_dump(dsp, DSP_AUDIO_PIPE, 1, 0, 8,
\t\t\t\t\t "buffer after Initialize flags 2");
\t\tn = ctr_dsp_audio_wait_reply(dsp, 1000);
\t\tif (n > 0)
\t\t\tdev_info(dsp->dev,
\t\t\t\t "audio replied only at flags 2; the flags halfword is required on this unit\\n");
\t}

\tif (n <= 0) {
\t\tdev_warn(dsp->dev,
\t\t\t "no audio reply on pipe %d dir 0 after Initialize, Wakeup and Initialize flags 2; pipe transport is proven, the audio state machine is not\\n",
\t\t\t DSP_AUDIO_PIPE);"""

assert OLD_GIVEUP in src, "give-up block not found"
src = src.replace(OLD_GIVEUP, NEW_GIVEUP, 1)

assert src != orig, "unchanged"
io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + PATH)
