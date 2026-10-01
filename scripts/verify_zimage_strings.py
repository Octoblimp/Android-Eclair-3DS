#!/usr/bin/env python3
"""Prove a kernel probe actually shipped, by reading the zImage in the zip.

Written because the obvious check is wrong here.  Confirming kernel #302 found
ctr_dsp_pipe_buffer_dump nowhere in the shipped System.map -- and all three of
its dev_info strings present in the kernel.  gcc had inlined it; the same map
carries ctr_dsp_swram_dump.part.0 and ctr_dsp_upload_firmware_once.part.0,
which is the compiler saying plainly that it partial-inlines the static helpers
in these files.

A format string cannot be inlined away: it is in .rodata either way.  So a
symbol being present proves the code shipped, and a symbol being absent proves
nothing at all.  A session that reads the map, concludes its probe did not
ship, and rebuilds is chasing a defect that does not exist.

This reads the zip the user actually flashes rather than the build tree, so it
also catches a stale pack -- the failure mode that cost two days in
project_sdcard_zip_packer.

Usage:
    verify_zimage_strings.py [zip-or-zImage] [string ...]

With no arguments it checks the release zip for the kernel #302 probes.
Exit status is 0 only if every string is present.
"""
import gzip
import io
import os
import sys
import zipfile
import zlib

from a3ds_paths import A3DS_WIN

DEFAULT_ZIP = os.path.join(A3DS_WIN, "sdcard.zip")

# The evidence probes of kernel #305.  Update alongside the driver, or pass
# your own strings on the command line.
#
# Two of the #303 probes are deliberately gone rather than merely absent.
# "ctrl walk done, register file restored" asserted a walk that tried single
# bits and printed one line each; #305 classifies the bits first and then
# tries pairs, so it reports a trial count and a hit count instead, and the
# old sentence could only pass by the new code carrying a string it no longer
# means.  "audio replied only at flags 2" asserted the flags-halfword theory,
# which the #303 capture retired: Initialize with flags 2 drew no reply
# either.  Both were replaced, not dropped -- the lines below assert what
# took their place.
DEFAULT_STRINGS = [
    # ctr_dsp: the libctru semaphore kick, the whole point of #305
    "DSP semaphore kick",
    "reply consumed",
    # ctr_dsp: the two-step reply read that kick is supposed to earn
    "audio reply truncated",
    "(flags %u) written to pipe",
    # ctr_dsp pipe buffer readback -- where the audio message actually landed
    "buffer after Initialize",
    "buffer after Wakeup",
    "reply buffer, pointers ignored",
    # ctr_cam #314 (N3DS_CAM_CAPTURE): the bring-up walk is gone; the driver
    # follows GBATEK's CAM register map and streams through the FIFO window.
    # These are the lines that tell each failure apart on the next capture:
    #   "sensor streaming"      -- the MT9V113 init list ran and SEQ_STATE
    #   "first FIFO data"       -- the receiver is being fed
    #   "no FIFO data 2 s"      -- it is not; CNT/STAT and the sensor state
    #   "frame gap after"       -- frame sync found (or "no inter-frame gap")
    #   "slowing the pixel clock" -- PIO overran and P1 was raised
    "capture driver ready (N3DS_CAM_CAPTURE)",
    "sensor streaming",
    "first FIFO data",
    "no FIFO data 2 s after start",
    "frame gap after",
    "no inter-frame gap",
    "slowing the pixel clock",
    "last gap-to-gap",
    # #315: a stream that gets no data climbs a recovery ladder (receiver
    # reset, sensor re-init, clock cycle) and says which step worked; the
    # AE cap and P1 0 that took QVGA preview from ~1 fps are in the
    # "sensor streaming" line.
    "no-data recovery step",
    "(N3DS_CAM_FRAME_RATE)",
    # ctr_dsp #306: the frame counter is written now, not only read
    "ARM11 stores into DSP data memory",
    "frame counter armed",
    "the audio pipeline is MIXING",
    # ctr_csnd capture: /dev/eac grew a .read, and this banner is the
    # contract AudioStreamInGeneric::set() demands -- 8000 Hz, mono, S16.
    # If this string moves, the recorder gets -EINVAL and nothing records.
    "returns 16-bit mono at 8000 Hz on read",
    # The analog front end, at the CTR codec's registers (libn3ds
    # microphoneInit + GBATEK), not the TLV320AIC32x4 numbers used before
    # #314 that left MICBIAS off and the PGA unrouted.  The line prints the
    # readback of every register it wrote.
    "mic front end up (N3DS_MIC_FRONTEND)",
    # ctr_csnd #313: the MIC block at 0x10162000 is REG_MIC_CNT/REG_MIC_DATA,
    # the DSi's microphone block, documented by 3dbrew and GBATEK.  The three
    # strings below are the whole diagnosis path for capture, and between
    # them they distinguish every outcome:
    #
    #   "first samples out of the FIFO"  -- the block is sampling; if the
    #       recording is still silent the problem is the analog front end
    #       or the resampler, not the transport.
    #   "FIFO still empty one second"    -- MIC_CNT was written and the
    #       block did not answer; that is an SNDEXCNT / codec question.
    #   "is not mapped"                  -- ioremap failed at probe.
    #
    # Losing any of them puts the next session back to guessing from a
    # recording that is quiet, which is exactly how this cost three kernels.
    "first samples out of the FIFO",
    "FIFO still empty one second after enabling",
    "capture: MIC block documented at",
    # The FIFO overran and was restarted, rather than latching off forever.
    "FIFO overruns",
    # #315: min/max/mean and the 0000h/FFFFh share of the raw samples --
    # "the mic doesn't work" arrives with the numbers that say whether the
    # block delivered silence, DC or signal.  #316: once per recording, at
    # its end, never from the drain timer mid-stream (that overran the FIFO).
    "(N3DS_MIC_STATS)",
    # #316: read() returns whole buffers.  Eclair's RecordThread counts any
    # read() >= 0 as a full buffer, so #315's ~20-sample paced reads became
    # 160-sample buffers of mostly stale memory: static, 8x fast.
    "(N3DS_MIC_FULL_READS)",
    # #317: I2S line 2 at 32.73 kHz, not libn3ds's (GBA-mode) 47.61 kHz.
    # mictest.wav from #316 had the same nine bit pairs equal in every FIFO
    # word -- 16 captured bits per 11 sent, exactly 47.61/32.73: the MIC
    # block shifted on the wrong clock and every sample was smeared.
    "(N3DS_MIC_CLOCK_32K)",
    # #317: the block's words/s, dead halves and bit layout are measured at
    # every start instead of assumed, and reported with the first 64 raw
    # FIFO words once the recording ends.  The next "mic still broken"
    # arrives with the evidence that decides it.
    "mic: probe (N3DS_MIC_PROBE)",
    "mic: probe bits (N3DS_MIC_PROBE)",
    "mic: raw (N3DS_MIC_RAW)",
    # #326: ctr_navkey translates START to KEY_MENU (N3DS_START_IS_MENU);
    # Eclair drops raw BTN_* scancodes, so without it nothing sends MENU.
    "START=MENU",
    # ctr_spi #315: the IRQ now acks INT_STAT and wakes the uninterruptible
    # waiter.  Without it every codec access slept 100 ms, the mic front end
    # took ~10 s inside the first read(), and touch polled under 10 Hz.
    "(N3DS_SPI_WAKE)",
    # ctr_csnd #318: the power-on clip was heard as "DRO-" while the driver
    # logged it as played in full.  The output stage is now read back at
    # init, re-checked while a stream plays and re-armed if a power bit
    # drops; each long stream ends with its own stats (per stream now, not
    # per boot), the output stage against init, and CSND ch0's register
    # block beside the estimated play cursor.  Those four lines decide
    # between "the amp went down" and "the DMA runs behind the estimate".
    "(N3DS_CSND_OUTPUT_REARM)",
    "(N3DS_CSND_STREAM_STATS)",
    "output stage at finish",
    "CSND ch0 at finish",
    # #319 read CSND ch0 SAD as the play cursor and trimmed the divider to
    # it; the speaker then played 3x fast.  SAD runs at 1/3 of the real
    # rate.  #320: both are parameters that default OFF (see FORBIDDEN below
    # for the #319 defaults), stock divider, elapsed-time accounting.
    "(N3DS_CSND_HW_CURSOR)",
    "(N3DS_CSND_RATE_TRIM)",
    "(N3DS_CSND_NOMINAL_RATE)",
    # #320: /dev/eac consumes every byte; a split frame waits for the next
    # write() instead of returning 0 (busybox head spun on that forever).
    "(N3DS_CSND_WHOLE_WRITES)",
    # #320: p100.37 (DAC/speaker-driver power flags) traced per stream, to
    # tell a clip that went quiet from a speaker driver that dropped out.
    "(N3DS_CSND_FLAG_TRACE)",
    # #319: the IPI-stall report ends with a one-line summary so a
    # photo of the top screen names both CPUs and the function.
    "(N3DS_CSD_SUMMARY_LAST)",
    # #320: the Browser page-load hang.  VFP11 bounced vfp_save_state's
    # FSTMIAD at a context switch with FPEXC.EX pending -- a fatal
    # kernel-mode undef with IRQs off.  EX is cleared before the save.
    "(N3DS_VFP11_EX_SAVE)",
    # #321: the kernel clock ran 3x fast on the KTR -- the TWD counts
    # PERIPHCLK = core/2 = 402 MHz, the DTS refclk says 134 MHz.
    "(N3DS_TWD_PERIPHCLK)",
    # #321: the AR6014 IRQ fallback keeps its proven 3.3 ms real cadence.
    "(N3DS_SDIO_POLL_REALTIME)",
    # #322: the circle pad is its own trackball input device (REL_X/REL_Y +
    # BTN_MOUSE), fed from the touch poll's FIFO read; the rest-centre line
    # names the marker.
    "Android3DS Circle Pad",
    "(N3DS_CIRCLEPAD_TRACKBALL)",
    # #323: the console is for real events.  The 5 s touch/circle-pad probe
    # line is opt-in (probe_log), and a healthy long stream no longer prints
    # five lines of "0 underruns ... 0 re-arms -- same as init"; anomalies
    # still do (stream_evidence=1 restores the full set).
    "(N3DS_TOUCH_PROBE_LOG)",
    "(N3DS_CSND_QUIET_FINISH)",
    # #324: the MCU interrupt controller probes (I2C NACK retry), so the
    # HOME button exists; X joins B as the recent-apps key.
    "MCU interrupts ready (HOME button)",
    "B/X=RECENTS",
]

# Strings that must NOT be in the shipped kernel: the #319 module-parameter
# descriptions, which only exist in a build whose defaults trim the CSND
# divider (3x fast audio) and account playback by SAD.
FORBIDDEN_STRINGS = [
    "correct the divider (default 1)",
    "account playback by the CSND play cursor (1) or by elapsed time (0)",
]


def load_zimage(path):
    """Return the zImage bytes, from a zip or from a bare file."""
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith("zImage")]
            if not names:
                sys.stderr.write("no zImage inside " + path + "\n")
                sys.exit(2)
            print("reading %s from %s" % (names[0], os.path.basename(path)))
            return z.read(names[0])
    return io.open(path, "rb").read()


def inflate(blob):
    """zImage is an ARM self-decompressing stub plus a gzip stream.

    The stream has no accurate trailer here, so a strict gzip read raises at the
    end after having produced the whole kernel.  Take the partial result: for a
    string search the decompressed prefix is the entire point.
    """
    start = 0
    while True:
        at = blob.find(b"\x1f\x8b\x08", start)
        if at < 0:
            return None, -1
        try:
            return gzip.GzipFile(fileobj=io.BytesIO(blob[at:])).read(), at
        except (OSError, EOFError, zlib.error):
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            try:
                part = d.decompress(blob[at:])
            except zlib.error:
                part = b""
            if len(part) > 1024 * 1024:
                return part, at
            start = at + 3


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_ZIP
    wanted = argv[2:] if len(argv) > 2 else DEFAULT_STRINGS

    blob = load_zimage(path)
    print("zImage: %d bytes" % len(blob))

    raw, at = inflate(blob)
    if raw is None:
        sys.stderr.write("no usable gzip member found in the zImage\n")
        return 2
    print("gzip member at offset %d -> %d bytes of kernel" % (at, len(raw)))

    missing = []
    for s in wanted:
        hits = raw.count(s.encode("utf-8"))
        print("  %-44s %s" % (s, ("present x%d" % hits) if hits else "MISSING"))
        if not hits:
            missing.append(s)

    present = []
    if len(argv) <= 2:
        for s in FORBIDDEN_STRINGS:
            hits = raw.count(s.encode("utf-8"))
            print("  %-44s %s" % (s[:44], ("FORBIDDEN x%d" % hits) if hits else "absent (good)"))
            if hits:
                present.append(s)
        # N3DS_SCRUB_BUILD_PATHS: nor may it name the build machine's home.
        from scrub_build_paths import PREFIXES
        for home, _ in PREFIXES:
            hits = raw.count(home)
            print("  %-44s %s" % ("build-machine home directory",
                                  ("FORBIDDEN x%d" % hits) if hits else "absent (good)"))
            if hits:
                present.append("build-machine home directory")

    if missing:
        sys.stderr.write("MISSING FROM SHIPPED KERNEL: "
                         + ", ".join(missing) + "\n")
        return 1
    if present:
        sys.stderr.write("FORBIDDEN IN SHIPPED KERNEL: "
                         + ", ".join(present) + "\n")
        return 1
    print("all evidence probes present in the shipped zImage")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
