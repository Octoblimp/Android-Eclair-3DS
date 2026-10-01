#!/usr/bin/env python3
"""Wire real microphone capture into ctr_csnd.c.

The MIC block at 0x10162000 is NOT undocumented -- it is the DSi's
MIC_CNT/MIC_DATA pair, and both 3dbrew ("MIC Registers") and GBATEK
("3DS Sound and Microphone" -> "DSi Microphone and SoundExt") give the
complete bit layout:

    0x10162000  u16  REG_MIC_CNT
        0-1   data format   (0=MakeStereo, 2=Normal, 3=None)
        2-3   sampling rate (0..3 = F/1, F/2, F/3, F/4 of the I2S clock)
        8     FIFO empty      (R)
        9     FIFO half-full  (R)
        10    FIFO full       (R)
        11    FIFO overrun    (R)  -- sampling STOPS until cleared
        12    FIFO clear      (W)  -- only honoured while bit15 == 0
        13-14 IRQ enable
        15    enable
    0x10162004  u32  REG_MIC_DATA  -- 16-word FIFO, two s16 samples per word

That explains the kernel #311/#312 survey result exactly: the baseline read
of +0x00 was 0x0100, i.e. bit 8, "FIFO empty", and nothing moved because the
survey is read-only and never set bit 15.

Idempotent: guarded by N3DS_MIC_REAL.
"""
import io
import os
import sys

SRC = os.path.expanduser(
    "~/android3ds/third_party/linux/drivers/platform/nintendo3ds/ctr_csnd.c")

GUARD = "N3DS_MIC_REAL"

TAB = chr(9)
NL = chr(10)


def sub_once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        sys.stderr.write("anchor %r matched %d times (expected 1)" % (what, n))
        sys.stderr.write(NL)
        sys.exit(2)
    return text.replace(old, new)


MIC_REGS = '''/*
 * N3DS_MIC_REAL: the MIC block at 0x10162000.
 *
 * This was carried for three kernels as "undocumented".  It is not: it is the
 * DSi's microphone block, unchanged, and both 3dbrew ("MIC Registers") and
 * GBATEK ("3DS Sound and Microphone", which forwards to "DSi Microphone and
 * SoundExt") give the whole layout.  What the #311 survey saw -- +0x00 reading
 * 0x0100 and nothing ever moving -- is exactly right for a block whose FIFO is
 * empty and whose enable bit was never set, because the survey is read-only.
 *
 * Two registers:
 *
 *   +0x00  u16  REG_MIC_CNT
 *   +0x04  u32  REG_MIC_DATA, a 16-word FIFO; each word is two s16 samples
 *
 * The sample rate is a divider of the I2S clock selected by SNDEXCNT bit 13,
 * which codec_init() leaves at 0 = 32.73 kHz, so the four rates available here
 * are 32730 / 16360 / 10910 / 8180 Hz.  8180 is both the closest to the 8000
 * Hz that AudioStreamInGeneric demands and the one that fills the 32-sample
 * FIFO slowest (3.9 ms), which is what makes polling viable at all.
 *
 * Three preconditions, all met before this file was touched:
 *   - SNDEXCNT bit 31 (I2S clock) and bit 15 set   -- codec_init()
 *   - the codec's mic path unmuted                 -- codec_power_on_adc()
 *   - the FIFO drained before it overruns          -- mic_drain()
 */
#define MIC_BASE@@0x10162000
#define MIC_REGS_BYTES@@8
#define MIC_SURVEY_BYTES@32

#define MIC_CNT@@@0x00@/* u16 */
#define MIC_DATA@@0x04@/* u32 */

#define MIC_FMT_MAKE_STEREO@0u
#define MIC_FMT_NORMAL@@2u@/* one s16 per halfword, mono */
#define MIC_FMT_NONE@@3u
#define MIC_CNT_RATE(n)@@(((n) & 3u) << 2)@/* F/1 .. F/4 */
#define MIC_CNT_FIFO_EMPTY@(1u << 8)
#define MIC_CNT_FIFO_HALF@(1u << 9)
#define MIC_CNT_FIFO_FULL@(1u << 10)
#define MIC_CNT_FIFO_OVERRUN@(1u << 11)
#define MIC_CNT_FIFO_CLEAR@(1u << 12)@/* W, needs bit 15 clear */
#define MIC_CNT_ENABLE@@(1u << 15)

/* Hardware rates for SNDEXCNT.bit13 == 0, indexed by MIC_CNT bits 2-3. */
static const u32 mic_hw_rates[4] = { 32730, 16360, 10910, 8180 };

/* 16 words of FIFO is 32 samples; at 8180 Hz that is 3.91 ms to overrun.
 * Poll at half that and a late timer still finds the data intact. */
#define MIC_POLL_US@@2000
/* When nobody has read for this long, stop the block and idle the timer. */
#define MIC_IDLE_MS@@400
#define MIC_IDLE_JIFFIES@msecs_to_jiffies(MIC_IDLE_MS)
#define MIC_IDLE_POLL_US@20000

/*
 * AudioStreamInGeneric fixes the capture format: 8000 Hz, mono, signed 16-bit
 * LE, 320 bytes (160 samples, 20 ms) per read.  Those are not negotiable, so
 * they are constants rather than parameters.  They live up here rather than
 * beside the read path because mic_drain()'s resampler needs CAP_RATE.
 */
#define CAP_RATE@@8000
#define CAP_BYTES_PER_SAMPLE@2

/* 5.11 has ms_to_ktime() and ns_to_ktime() but no us_to_ktime(). */
static inline ktime_t mic_us(u32 us)
{
	return ns_to_ktime((u64)us * NSEC_PER_USEC);
}

/* Half a second of 8 kHz mono: enough to ride out a scheduling hiccup without
 * letting capture latency grow without bound. */
#define CAP_RING_SAMPLES@4096
#define CAP_RING_MASK@@(CAP_RING_SAMPLES - 1)
'''

STRUCT_OLD = '''@/* N3DS_MIC_CAPTURE: input side.  Independent of the output side --
@ * AudioHardwareGeneric shares one fd between them. */
@struct mutex@@cap_lock;
@bool@@@cap_on;
@ktime_t@@@cap_t0;@@/* when capture started */
@u64@@@cap_delivered;@/* mono samples handed out */
@bool@@@cap_warned;@/* "no sample source" said once */
@void __iomem@@*mic;@@/* MIC block, mapped read-only */
};
'''

STRUCT_NEW = '''@/* N3DS_MIC_CAPTURE: input side.  Independent of the output side --
@ * AudioHardwareGeneric shares one fd between them. */
@struct mutex@@cap_lock;
@bool@@@cap_on;
@ktime_t@@@cap_t0;@@/* when capture started */
@u64@@@cap_delivered;@/* mono samples handed out */
@bool@@@cap_warned;@/* one-line banner said once */
@void __iomem@@*mic;@@/* MIC block */

@/*
@ * N3DS_MIC_REAL: the FIFO holds 32 samples, 3.9 ms at 8180 Hz, and a
@ * recorder asks for 20 ms at a time -- so the FIFO cannot be drained from
@ * read().  A timer drains it into this ring instead.
@ *
@ * Single producer (cap_timer), single consumer (read()), so no lock: the
@ * producer owns cap_head, the consumer owns cap_tail, and the two are
@ * published to each other with release/acquire.  Both are free-running and
@ * masked at use, so neither ever needs wrapping.
@ */
@struct hrtimer@@cap_timer;
@s16@@@*cap_ring;
@u32@@@cap_head;@/* producer */
@u32@@@cap_tail;@/* consumer */
@u32@@@cap_phase;@/* 8180 -> 8000 resampler */
@unsigned long@@cap_last_read;@/* jiffies; drives the idle stop */
@bool@@@cap_hw_on;@/* owned by cap_timer only */
@u32@@@cap_overruns;@/* FIFO overran, samples lost */
@u32@@@cap_ring_full;@/* consumer too slow */
@u32@@@cap_underruns;@/* consumer starved, padded */
@bool@@@cap_seen_data;@/* first-sample banner printed */
@u32@@@cap_dry_ticks;@/* ticks with an empty FIFO */
};
'''

PARAM_OLD = '''static int mic_data_off = -1;
module_param(mic_data_off, int, 0644);
MODULE_PARM_DESC(mic_data_off,
@"halfword offset of the sample register inside the MIC block, once "
@"mic_survey has identified one; -1 (default) delivers silence");
'''

PARAM_NEW = '''/*
 * N3DS_MIC_REAL: which MIC_CNT rate divider to use.  3 is F/4 = 8180 Hz with
 * the 32.73 kHz I2S clock codec_init() selects, which is the closest rate to
 * the 8000 Hz AudioStreamInGeneric insists on and the one that fills the
 * 32-sample FIFO slowest.  0..2 are 32730 / 16360 / 10910 Hz and are here for
 * measuring the block, not for recording -- capture resamples to 8000 either
 * way, and the faster the rate the sooner a late timer tick costs audio.
 */
static int mic_rate_idx = 3;
module_param(mic_rate_idx, int, 0644);
MODULE_PARM_DESC(mic_rate_idx,
@"MIC_CNT rate divider 0..3 (F/1..F/4 of the 32.73 kHz I2S clock); "
@"3 = 8180 Hz, the default");

/*
 * SNDEXCNT bit 12, "Enable Microphone timing".  GBATEK says the microphone
 * needs bit 31 plus one or both of bit 15 / bit 12, and bit 15 has always
 * been set here for the DAC.  Setting bit 12 as well is the documented belt
 * and braces -- but it shares a register with a speaker path that is
 * hardware-confirmed working, so it is a parameter rather than a constant: if
 * analog OUTPUT ever regresses, boot with ctr_csnd.mic_i2s_timing=0 before
 * suspecting anything else in this file.
 */
static int mic_i2s_timing = 1;
module_param(mic_i2s_timing, int, 0644);
MODULE_PARM_DESC(mic_i2s_timing,
@"set SNDEXCNT bit 12 (mic timing) alongside bit 15 (default on)");
'''

SURVEY_TAIL_OLD = '''@@dev_info(cs->dev,
@@@ "mic_survey: %d halfword(s) move; set ctr_csnd.mic_data_off "
@@@ "to the byte offset of the sample register to feed capture "
@@@ "from it!n", movers);
}
'''

SURVEY_TAIL_NEW = '''@@dev_info(cs->dev,
@@@ "mic_survey: %d halfword(s) move while the ADC runs!n",
@@@ movers);
}

/* ------------------------------------------------------------------ *
 * N3DS_MIC_REAL -- the MIC block itself
 * ------------------------------------------------------------------ */

static u16 mic_cnt_base(void)
{
@int idx = mic_rate_idx;

@if (idx < 0 || idx > 3)
@@idx = 3;
@return (u16)(MIC_FMT_NORMAL | MIC_CNT_RATE(idx));
}

static u32 mic_hw_rate(void)
{
@int idx = mic_rate_idx;

@if (idx < 0 || idx > 3)
@@idx = 3;
@return mic_hw_rates[idx];
}

/*
 * Start sampling.  The order is load-bearing: the FIFO-clear bit is only
 * honoured while the enable bit is clear, so it takes one write to disable,
 * one to clear and one to enable.  That is also exactly the sequence for
 * recovering from an overrun, which is why mic_hw_start() is the overrun
 * recovery too.
 */
static void mic_hw_start(struct ctr_csnd *cs)
{
@u16 base = mic_cnt_base();

@if (!cs->mic)
@@return;

@iowrite16(0, cs->mic + MIC_CNT);
@iowrite16(base | MIC_CNT_FIFO_CLEAR, cs->mic + MIC_CNT);
@iowrite16(base | MIC_CNT_ENABLE, cs->mic + MIC_CNT);
}

static void mic_hw_stop(struct ctr_csnd *cs)
{
@if (cs->mic)
@@iowrite16(0, cs->mic + MIC_CNT);
}

/*
 * Move everything the FIFO has into the ring, resampling the hardware rate
 * down to the 8000 Hz the caller was promised.
 *
 * The resampler is a phase accumulator, not a filter: it keeps 8000 of every
 * 8180 samples.  At 2.2 % decimation the dropped sample is 45 samples from
 * its neighbours, so there is nothing to alias that the 8 kHz band does not
 * already contain.  Anything better than that belongs above the driver.
 *
 * Runs in hrtimer (softirq) context, and is bounded by the FIFO depth -- at
 * most 17 register reads -- so it cannot become the kind of unbounded
 * interrupt-context loop that has caused soft lockups on this board before.
 * MIC_CNT is re-read every iteration and the FIFO is never read while bit 8
 * says it is empty: an empty-FIFO read is the documented stall hazard on the
 * derived CAM block and is assumed to apply here too.
 */
static void mic_drain(struct ctr_csnd *cs)
{
@u32 hw = mic_hw_rate();
@u32 head = cs->cap_head;
@u32 head0 = head;
@u32 tail = smp_load_acquire(&cs->cap_tail);
@unsigned int word;
@u16 cnt = 0;

@/* 16 words is the whole FIFO; the 17th iteration is what lets the loop
@ * notice it has gone empty instead of exiting with data still queued. */
@for (word = 0; word < 17; word++) {
@@u32 pair;
@@int half;

@@cnt = ioread16(cs->mic + MIC_CNT);
@@if (cnt & MIC_CNT_FIFO_EMPTY)
@@@break;

@@pair = ioread32(cs->mic + MIC_DATA);

@@for (half = 0; half < 2; half++) {
@@@s16 s = (s16)(half ? (pair >> 16) : (pair & 0xFFFF));

@@@cs->cap_phase += CAP_RATE;
@@@if (cs->cap_phase < hw)
@@@@continue;@/* decimated away */
@@@cs->cap_phase -= hw;

@@@if (head - tail >= CAP_RING_SAMPLES) {
@@@@cs->cap_ring_full++;
@@@@continue;
@@@}
@@@cs->cap_ring[head & CAP_RING_MASK] = s;
@@@head++;
@@}
@}

@/*
@ * One line, once, the first time samples actually come out of the
@ * block, and one line if they never do.  This is the whole difference
@ * between "the microphone does not work" and a diagnosis, and it costs
@ * two branches per tick.
@ */
@if (head != head0) {
@@cs->cap_dry_ticks = 0;
@@if (!cs->cap_seen_data) {
@@@cs->cap_seen_data = true;
@@@dev_info(cs->dev,
@@@@ "mic: first samples out of the FIFO -- MIC_CNT 0x%04x, %u kept, first four %d %d %d %d!n",
@@@@ cnt, head - head0,
@@@@ cs->cap_ring[head0 & CAP_RING_MASK],
@@@@ cs->cap_ring[(head0 + 1) & CAP_RING_MASK],
@@@@ cs->cap_ring[(head0 + 2) & CAP_RING_MASK],
@@@@ cs->cap_ring[(head0 + 3) & CAP_RING_MASK]);
@@}
@} else if (!cs->cap_seen_data && ++cs->cap_dry_ticks == 500) {
@@/* 500 ticks at 2 ms is one second of enabled, empty FIFO. */
@@dev_warn(cs->dev,
@@@ "mic: FIFO still empty one second after enabling -- MIC_CNT reads 0x%04x (wrote 0x%04x); the block is not sampling!n",
@@@ cnt, mic_cnt_base() | MIC_CNT_ENABLE);
@}

@smp_store_release(&cs->cap_head, head);

@/*
@ * Overrun latches and stops sampling until the FIFO is cleared, so this
@ * is not cosmetic: without the restart the microphone goes permanently
@ * silent after the first missed deadline.
@ */
@if (cnt & MIC_CNT_FIFO_OVERRUN) {
@@cs->cap_overruns++;
@@mic_hw_start(cs);
@}
}

static enum hrtimer_restart mic_tick(struct hrtimer *t)
{
@struct ctr_csnd *cs = container_of(t, struct ctr_csnd, cap_timer);
@u32 period_us;

@/* ioremap or the ring allocation failed at probe: there is nothing to
@ * drain and nowhere to put it, so do not come back. */
@if (!cs->mic || !cs->cap_ring)
@@return HRTIMER_NORESTART;

@if (time_after(jiffies,
@@       READ_ONCE(cs->cap_last_read) + MIC_IDLE_JIFFIES)) {
@@/*
@@ * Nobody is recording.  Park the block and back the poll right
@@ * off, rather than waking 500 times a second for the rest of the
@@ * boot because one app once opened an AudioRecord -- mediaserver
@@ * holds /dev/eac open from its constructor to shutdown, so
@@ * release() is not a reliable stop.
@@ */
@@if (cs->cap_hw_on) {
@@@mic_hw_stop(cs);
@@@cs->cap_hw_on = false;
@@}
@@period_us = MIC_IDLE_POLL_US;
@} else {
@@if (!cs->cap_hw_on) {
@@@cs->cap_phase = 0;
@@@cs->cap_dry_ticks = 0;
@@@mic_hw_start(cs);
@@@cs->cap_hw_on = true;
@@}
@@mic_drain(cs);
@@period_us = MIC_POLL_US;
@}

@hrtimer_forward_now(t, mic_us(period_us));
@return HRTIMER_RESTART;
}
'''

CAPFILL_OLD = '''/*
 * Fill n mono samples.
 *
 * This is the seam for real capture.  The codec cannot be the source: the
 * TSC2117's ADC feeds I2S, and its control bus has no sample register, so
 * NSPI can program the front end but can never read audio back through it.
 * Real samples have to come from the MIC block's DMA, whose register layout
 * is not documented and has not been established on hardware yet.  Until it
 * is, hand back silence -- correctly paced, so every caller above behaves
 * exactly as it will once the source is wired up.
 */
static void cap_fill(struct ctr_csnd *cs, s16 *dst, u32 n)
{
@u32 i;

@/*
@ * mic_data_off is set once mic_survey has identified a moving
@ * halfword.  Reading it n times per buffer is not a DMA transfer and
@ * will alias badly if the block is not actually producing 8 kHz
@ * samples -- it is here so that the identification can be confirmed
@ * on hardware in one boot instead of one rebuild.
@ */
@if (cs->mic && mic_data_off >= 0 &&
@    mic_data_off + 2 <= MIC_SURVEY_BYTES) {
@@if (!cs->cap_warned) {
@@@cs->cap_warned = true;
@@@dev_info(cs->dev,
@@@@ "capture: reading MIC +0x%02x as the sample register!n",
@@@@ mic_data_off);
@@}
@@for (i = 0; i < n; i++) {
@@@dst[i] = (s16)ioread16(cs->mic + mic_data_off);
@@@ndelay(100);
@@}
@@return;
@}

@if (!cs->cap_warned) {
@@cs->cap_warned = true;
@@dev_info(cs->dev,
@@@ "capture: front end is live but there is no sample source yet "
@@@ "(MIC block at 0x%08x undocumented); delivering paced silence "
@@@ "at %u Hz mono!n", MIC_BASE, CAP_RATE);
@}
@memset(dst, 0, (size_t)n * CAP_BYTES_PER_SAMPLE);
}
'''

CAPFILL_NEW = '''/*
 * Fill n mono samples from the ring the capture timer is feeding.
 *
 * Underrun is padded with silence rather than short-read: AudioFlinger's
 * RecordThread treats a short read as an error and tears the track down, and
 * the caller is already clock-paced, so a pad here is a few hundred
 * microseconds of quiet rather than a drift.
 */
static void cap_fill(struct ctr_csnd *cs, s16 *dst, u32 n)
{
@u32 tail, head, have, i;

@if (!cs->mic || !cs->cap_ring) {
@@if (!cs->cap_warned) {
@@@cs->cap_warned = true;
@@@dev_warn(cs->dev,
@@@@ "capture: MIC block at 0x%08x is not mapped; "
@@@@ "delivering paced silence at %u Hz mono!n",
@@@@ MIC_BASE, CAP_RATE);
@@}
@@memset(dst, 0, (size_t)n * CAP_BYTES_PER_SAMPLE);
@@return;
@}

@if (!cs->cap_warned) {
@@cs->cap_warned = true;
@@dev_info(cs->dev,
@@@ "capture: MIC block sampling at %u Hz, resampled to %u Hz mono "
@@@ "(MIC_CNT = 0x%04x)!n",
@@@ mic_hw_rate(), CAP_RATE, ioread16(cs->mic + MIC_CNT));
@}

@tail = cs->cap_tail;
@head = smp_load_acquire(&cs->cap_head);
@have = head - tail;
@if (have > n)
@@have = n;

@for (i = 0; i < have; i++)
@@dst[i] = cs->cap_ring[(tail + i) & CAP_RING_MASK];

@smp_store_release(&cs->cap_tail, tail + have);

@if (have < n) {
@@cs->cap_underruns += n - have;
@@memset(dst + have, 0,
@@       (size_t)(n - have) * CAP_BYTES_PER_SAMPLE);
@}
}
'''

READ_START_OLD = '''@if (!cs->cap_on) {
@@cs->cap_on = true;
@@cs->cap_t0 = ktime_get();
@@cs->cap_delivered = 0;
@@codec_power_on_adc(cs);
@}
'''

READ_START_NEW = '''@if (!cs->cap_on) {
@@cs->cap_on = true;
@@cs->cap_t0 = ktime_get();
@@cs->cap_delivered = 0;
@@codec_power_on_adc(cs);
@@/* N3DS_MIC_REAL: the timer owns the block from here until
@@ * release().  It idles itself out when nobody reads. */
@@WRITE_ONCE(cs->cap_last_read, jiffies);
@@hrtimer_start(&cs->cap_timer, mic_us(MIC_POLL_US),
@@@      HRTIMER_MODE_REL);
@} else if (time_after(jiffies,
@@@      cs->cap_last_read + MIC_IDLE_JIFFIES)) {
@@/*
@@ * N3DS_MIC_REAL: AudioHardwareGeneric keeps one fd open for the
@@ * life of mediaserver, so release() is not the end of a
@@ * recording -- a gap in read() is.  Restart the clock and throw
@@ * away whatever the ring still holds, or the first buffer of
@@ * every recording after the first is the tail of the one before.
@@ */
@@cs->cap_t0 = ktime_get();
@@cs->cap_delivered = 0;
@@smp_store_release(&cs->cap_tail,
@@@@  smp_load_acquire(&cs->cap_head));
@}
@WRITE_ONCE(cs->cap_last_read, jiffies);
'''

RELEASE_OLD = '''@mutex_lock(&cs->cap_lock);
@cs->cap_on = false;
@mutex_unlock(&cs->cap_lock);
@return 0;
}
'''

RELEASE_NEW = '''@mutex_lock(&cs->cap_lock);
@if (cs->cap_on) {
@@cs->cap_on = false;
@@/* N3DS_MIC_REAL: stop the timer before touching MIC_CNT -- while
@@ * it runs it is the only writer of that register.  It busy-waits
@@ * rather than sleeping, and mic_tick() never takes cap_lock, so
@@ * cancelling under the mutex cannot deadlock. */
@@hrtimer_cancel(&cs->cap_timer);
@@mic_hw_stop(cs);
@@cs->cap_hw_on = false;
@@if (cs->cap_overruns || cs->cap_ring_full || cs->cap_underruns)
@@@dev_info(cs->dev,
@@@@ "capture stopped: %u FIFO overruns, %u ring-full drops, %u samples padded!n",
@@@@ cs->cap_overruns, cs->cap_ring_full,
@@@@ cs->cap_underruns);
@@cs->cap_overruns = 0;
@@cs->cap_ring_full = 0;
@@cs->cap_underruns = 0;
@}
@mutex_unlock(&cs->cap_lock);
@return 0;
}
'''

PROBE_OLD = '''@/*
@ * Read-only mapping of the MIC block.  It is not a reg entry in the
@ * DT node -- nothing about this block is documented well enough to
@ * claim it -- so it is mapped here without requesting the region, the
@ * same way PDN_CAMERA_CNT is reached from ctr_cam.c.
@ */
@cs->mic = ioremap(MIC_BASE, MIC_SURVEY_BYTES);
@if (!cs->mic)
@@dev_warn(dev, "MIC block at 0x%08x could not be mapped; capture will be silent!n",
@@@ MIC_BASE);

@if (mic_survey)
@@mic_block_survey(cs);
'''

PROBE_NEW = '''@/*
@ * The MIC block is not a reg entry in the DT node, so it is mapped here
@ * without requesting the region, the same way PDN_CAMERA_CNT is reached
@ * from ctr_cam.c.  MIC_SURVEY_BYTES rather than MIC_REGS_BYTES so that
@ * mic_survey=1 still has something to sweep.
@ */
@cs->mic = ioremap(MIC_BASE, MIC_SURVEY_BYTES);
@if (!cs->mic)
@@dev_warn(dev, "MIC block at 0x%08x could not be mapped; capture will be silent!n",
@@@ MIC_BASE);
@else
@@mic_hw_stop(cs);@@/* N3DS_MIC_REAL: known state */

@if (mic_survey)
@@mic_block_survey(cs);

@/* N3DS_MIC_REAL */
@hrtimer_init(&cs->cap_timer, CLOCK_MONOTONIC, HRTIMER_MODE_REL);
@cs->cap_timer.function = mic_tick;
@cs->cap_ring = devm_kcalloc(dev, CAP_RING_SAMPLES,
@@@@    sizeof(*cs->cap_ring), GFP_KERNEL);
@if (!cs->cap_ring)
@@dev_warn(dev, "no capture ring; the microphone will be silent!n");
'''

REMOVE_OLD = '''@cancel_delayed_work_sync(&cs->drain);
@csnd_stop(cs);
'''

REMOVE_NEW = '''@cancel_delayed_work_sync(&cs->drain);
@hrtimer_cancel(&cs->cap_timer);@@/* N3DS_MIC_REAL */
@mic_hw_stop(cs);
@csnd_stop(cs);
'''

CAPDEFS_OLD = ''' * N3DS_MIC_CAPTURE -- input path
 *
 * AudioStreamInGeneric fixes the format: 8000 Hz, mono, signed 16-bit LE,
 * 320 bytes (160 samples, 20 ms) per read.  Those are not negotiable, so
 * they are constants here rather than parameters.
 * ------------------------------------------------------------------ */

#define CAP_RATE@@8000
#define CAP_BYTES_PER_SAMPLE@2
'''

CAPDEFS_NEW = ''' * N3DS_MIC_CAPTURE -- input path
 *
 * The format AudioStreamInGeneric fixes -- 8000 Hz, mono, signed 16-bit LE,
 * 320 bytes per read -- is CAP_RATE / CAP_BYTES_PER_SAMPLE, defined beside
 * the MIC register map because mic_drain()'s resampler needs CAP_RATE.
 * ------------------------------------------------------------------ */
'''


def fix(s):
    """@ is a tab, ! before n is a backslash (heredoc-safe authoring)."""
    return s.replace("@", TAB).replace("!n", chr(92) + "n")


def main():
    src = io.open(SRC, encoding="utf-8").read()
    if GUARD in src:
        print("already patched (%s present)" % GUARD)
        return 0

    steps = [
        ("hrtimer/jiffies includes",
         "#include <linux/dma-mapping.h>" + NL,
         "#include <linux/dma-mapping.h>" + NL +
         "#include <linux/hrtimer.h>" + NL +
         "#include <linux/jiffies.h>" + NL),

        ("I2S1_MIC_TIMING define",
         fix("#define I2S1_EN@@@(1u << 15)" + NL),
         fix("#define I2S1_EN@@@(1u << 15)" + NL +
             '/* N3DS_MIC_REAL: SNDEXCNT bit 12, "Enable Microphone timing".' + NL +
             " * Writable only while bit 31 (I2S2_EN) is still clear, which is why" + NL +
             " * codec_init() writes I2S1_CNT before I2S2_CNT.  Do not reorder. */" + NL +
             "#define I2S1_MIC_TIMING@@(1u << 12)" + NL)),

        ("I2S1_CNT write",
         fix("@iowrite16(I2S1_EN | I2S1_MCLK1_16MHZ | I2S1_FREQ_32KHZ |" + NL +
             "@@  I2S1_LGY_VOL(32) | I2S1_DSP_VOL(0), cs->i2s + I2S1_CNT);" + NL),
         fix("@iowrite16(I2S1_EN | I2S1_MCLK1_16MHZ | I2S1_FREQ_32KHZ |" + NL +
             "@@  (mic_i2s_timing ? I2S1_MIC_TIMING : 0) |" + NL +
             "@@  I2S1_LGY_VOL(32) | I2S1_DSP_VOL(0), cs->i2s + I2S1_CNT);" + NL)),

        ("MIC register map",
         fix("/* The MIC block.  Undocumented; only ever read, and only when asked. */" + NL +
             "#define MIC_BASE@@0x10162000" + NL +
             "#define MIC_SURVEY_BYTES@32" + NL),
         fix(MIC_REGS)),

        ("struct ctr_csnd capture fields", fix(STRUCT_OLD), fix(STRUCT_NEW)),
        ("mic module parameters", fix(PARAM_OLD), fix(PARAM_NEW)),
        ("mic_survey default",
         "static int mic_survey = 1;" + NL,
         fix("static int mic_survey;@@/* the block is documented now; "
             "off by default */" + NL)),
        ("survey verdict + MIC block code", fix(SURVEY_TAIL_OLD), fix(SURVEY_TAIL_NEW)),
        ("capture format constants", fix(CAPDEFS_OLD), fix(CAPDEFS_NEW)),
        ("cap_fill", fix(CAPFILL_OLD), fix(CAPFILL_NEW)),
        ("read() capture start", fix(READ_START_OLD), fix(READ_START_NEW)),
        ("release() capture stop", fix(RELEASE_OLD), fix(RELEASE_NEW)),
        ("probe ioremap", fix(PROBE_OLD), fix(PROBE_NEW)),
        ("remove() teardown", fix(REMOVE_OLD), fix(REMOVE_NEW)),
        ("module description",
         'MODULE_DESCRIPTION("Nintendo 3DS CSND PCM mixer and CTR codec output");',
         'MODULE_DESCRIPTION("Nintendo 3DS CSND PCM mixer, CTR codec output and '
         'MIC capture");'),
    ]

    for what, old, new in steps:
        src = sub_once(src, old, new, what)
        print("  ok: %s" % what)

    io.open(SRC, "w", encoding="utf-8", newline=NL).write(src)
    print("patched %s" % SRC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
