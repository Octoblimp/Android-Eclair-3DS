#!/usr/bin/env python3
"""Add a capture path to /dev/eac so the Android mic stack works.

AudioHardwareGeneric opens /dev/eac exactly once, O_RDWR, in its constructor
and hands that one fd to both the output and the input stream.  So read() has
to work on the same struct file as write(), independently of it.  The input
contract is fixed by AudioStreamInGeneric::set(): 8000 Hz, mono, PCM_16_BIT,
320-byte buffers.  Anything else is rejected before a byte moves.

What is real here and what is not:

  - The pacing, the fop, the 8 kHz mono S16 framing and the codec ADC /
    MICBIAS bring-up are real.  AudioRecord, MediaRecorder and anything built
    on them get a stream that starts, runs at exactly real time, and stops.
  - The sample source is NOT real yet.  The TSC2117 is an AIC3xxx-family
    codec: its ADC output goes out on I2S, and the control bus has no
    "read me a sample" register, so there is no way to get audio out of it
    over NSPI no matter how it is programmed.  Capture on this SoC goes
    through the MIC block at 0x10162000, which is as undocumented as the CAM
    block and gets the same treatment -- no bit-guessing on hardware.
    cap_fill() is the seam; it returns paced silence and says so once.

  - mic_survey=1 does a read-only sweep of the MIC block's first 32 bytes and
    dumps it, so the next session starts from data instead of recall.  Off by
    default, and it deliberately does not touch anything that looks like a
    FIFO -- an empty-FIFO read can stall the bus, which is the documented
    hazard for the derived CAM FIFOs.

Idempotent: guarded by N3DS_MIC_CAPTURE.
"""
from a3ds_paths import A3DS_ROOT

import io
import sys

SRC = (f"{A3DS_ROOT}/third_party/linux/drivers/platform/"
       "nintendo3ds/ctr_csnd.c")

with io.open(SRC, "r", encoding="utf-8") as f:
    src = f.read()

if "N3DS_MIC_CAPTURE" in src:
    print("  - ctr_csnd.c: capture path already present (skipped)")
    sys.exit(0)

# ------------------------------------------------------------ 1. struct fields
anchor = """	u32			rate;
	u32			underruns;
};"""
if anchor not in src:
    sys.exit("struct ctr_csnd: anchor not found")
src = src.replace(anchor, """	u32			rate;
	u32			underruns;

	/* N3DS_MIC_CAPTURE: input side.  Independent of the output side --
	 * AudioHardwareGeneric shares one fd between them. */
	struct mutex		cap_lock;
	bool			cap_on;
	ktime_t			cap_t0;		/* when capture started */
	u64			cap_delivered;	/* mono samples handed out */
	bool			cap_warned;	/* "no sample source" said once */
};""", 1)

# ------------------------------------------------------------ 2. module params
anchor = """static int pcm_rate = 44100;
module_param(pcm_rate, int, 0644);"""
if anchor not in src:
    sys.exit("pcm_rate: anchor not found")
src = src.replace(anchor, """static int mic_survey;
module_param(mic_survey, int, 0644);
MODULE_PARM_DESC(mic_survey,
	"read-only dump of the MIC block at 0x10162000 at probe (default off)");

static int pcm_rate = 44100;
module_param(pcm_rate, int, 0644);""", 1)

# ------------------------------------------------ 3. capture helpers + read fop
anchor = """static const struct file_operations ctr_csnd_fops = {"""
if anchor not in src:
    sys.exit("fops: anchor not found")

helpers = r'''/* ------------------------------------------------------------------ *
 * N3DS_MIC_CAPTURE -- input path
 *
 * AudioStreamInGeneric fixes the format: 8000 Hz, mono, signed 16-bit LE,
 * 320 bytes (160 samples, 20 ms) per read.  Those are not negotiable, so
 * they are constants here rather than parameters.
 * ------------------------------------------------------------------ */

#define CAP_RATE		8000
#define CAP_BYTES_PER_SAMPLE	2

/* The MIC block.  Undocumented; only ever read, and only when asked. */
#define MIC_BASE		0x10162000
#define MIC_SURVEY_BYTES	32

/*
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
	if (!cs->cap_warned) {
		cs->cap_warned = true;
		dev_info(cs->dev,
			 "capture: front end is live but there is no sample source yet "
			 "(MIC block at 0x%08x undocumented); delivering paced silence "
			 "at %u Hz mono\n", MIC_BASE, CAP_RATE);
	}
	memset(dst, 0, (size_t)n * CAP_BYTES_PER_SAMPLE);
}

static ssize_t ctr_csnd_dev_read(struct file *filp, char __user *ubuf,
				 size_t count, loff_t *ppos)
{
	struct ctr_csnd *cs = container_of(filp->private_data,
					   struct ctr_csnd, misc);
	u32 want, avail;
	u64 due;
	s64 elapsed_us;
	s16 *buf;
	ssize_t ret;

	if (count < CAP_BYTES_PER_SAMPLE)
		return -EINVAL;

	want = count / CAP_BYTES_PER_SAMPLE;

	mutex_lock(&cs->cap_lock);

	if (!cs->cap_on) {
		cs->cap_on = true;
		cs->cap_t0 = ktime_get();
		cs->cap_delivered = 0;
		codec_power_on_adc(cs);
	}

	/*
	 * Pace against the monotonic clock.  A recorder that reads flat out
	 * must not outrun real time, or a 10-second recording comes back
	 * containing 10 seconds of samples captured in 40 ms.  Sleep until
	 * enough sample slots have actually elapsed.
	 */
	for (;;) {
		elapsed_us = ktime_to_us(ktime_sub(ktime_get(), cs->cap_t0));
		if (elapsed_us < 0)
			elapsed_us = 0;
		due = div_u64((u64)elapsed_us * CAP_RATE, 1000000);

		if (due > cs->cap_delivered) {
			avail = (u32)min_t(u64, due - cs->cap_delivered, want);
			break;
		}

		mutex_unlock(&cs->cap_lock);
		if (filp->f_flags & O_NONBLOCK)
			return -EAGAIN;
		/* One sample period is 125 us; sleeping a whole buffer's
		 * worth (20 ms) is both kinder to the scheduler and exactly
		 * the cadence the caller expects. */
		usleep_range(2000, 4000);
		if (signal_pending(current))
			return -ERESTARTSYS;
		mutex_lock(&cs->cap_lock);
		if (!cs->cap_on) {	/* released under us */
			mutex_unlock(&cs->cap_lock);
			return 0;
		}
	}

	buf = kmalloc((size_t)avail * CAP_BYTES_PER_SAMPLE, GFP_KERNEL);
	if (!buf) {
		mutex_unlock(&cs->cap_lock);
		return -ENOMEM;
	}

	cap_fill(cs, buf, avail);
	cs->cap_delivered += avail;

	mutex_unlock(&cs->cap_lock);

	if (copy_to_user(ubuf, buf, (size_t)avail * CAP_BYTES_PER_SAMPLE))
		ret = -EFAULT;
	else
		ret = (ssize_t)avail * CAP_BYTES_PER_SAMPLE;

	kfree(buf);
	return ret;
}

'''

src = src.replace(anchor, helpers + anchor, 1)

# ------------------------------------------------------------- 4. wire the fop
anchor = """	.write		= ctr_csnd_dev_write,
	.llseek		= no_llseek,"""
if anchor not in src:
    sys.exit("fops body: anchor not found")
src = src.replace(anchor, """	.write		= ctr_csnd_dev_write,
	.read		= ctr_csnd_dev_read,
	.llseek		= no_llseek,""", 1)

# ------------------------------------------------- 5. codec ADC / MICBIAS init
anchor = """static int codec_init(struct ctr_csnd *cs)"""
if anchor not in src:
    sys.exit("codec_init: anchor not found")

adc = r'''/*
 * N3DS_MIC_CAPTURE: bring up the analog capture front end.
 *
 * These are documented TSC2117 / AIC3xxx-family registers, unlike anything in
 * the MIC block.  Powering the ADC and MICBIAS here means that once a sample
 * source exists the signal is already there, and it costs nothing if it is
 * never used -- the ADC idles.
 *
 * Page 1 reg 51: MICBIAS control, 0x40 = powered from AVDD.
 * Page 1 reg 52/54: MIC PGA P/M input routing, 0x40 = MIC1LP/MIC1LM at 10k.
 * Page 1 reg 59: MIC PGA gain, 0x20 = +16 dB, unmuted.
 * Page 0 reg 81: ADC power, 0x80 = ADC on.
 * Page 0 reg 82: ADC fine gain / mute, 0x00 = unmuted.
 */
#define CDC_ADC_POWER		CDC(0, 81)
#define CDC_ADC_MUTE		CDC(0, 82)
#define CDC_MICBIAS		CDC(1, 51)
#define CDC_MICPGA_P		CDC(1, 52)
#define CDC_MICPGA_M		CDC(1, 54)
#define CDC_MICPGA_GAIN		CDC(1, 59)

static void codec_power_on_adc(struct ctr_csnd *cs)
{
	if (!cs->codec_ok)
		return;

	cdc_write(cs, CDC_MICBIAS,	0x40);
	cdc_write(cs, CDC_MICPGA_P,	0x40);
	cdc_write(cs, CDC_MICPGA_M,	0x40);
	cdc_write(cs, CDC_MICPGA_GAIN,	0x20);
	cdc_write(cs, CDC_ADC_POWER,	0x80);
	cdc_write(cs, CDC_ADC_MUTE,	0x00);

	dev_info(cs->dev, "codec: ADC + MICBIAS powered (readback p0.81 = 0x%02x)\n",
		 cdc_read(cs, CDC_ADC_POWER) & 0xFF);
}

/*
 * Read-only sweep of the MIC block, for discovery only.  Off by default.
 * Deliberately limited to the first 32 bytes: that covers a control register
 * file on every other block on this SoC, and stops well short of anything
 * that might be a FIFO -- reading an empty FIFO can stall the bus, which is
 * the same hazard already documented for the derived CAM FIFOs.
 */
static void mic_block_survey(struct ctr_csnd *cs)
{
	void __iomem *mic;
	int i;

	mic = ioremap(MIC_BASE, MIC_SURVEY_BYTES);
	if (!mic) {
		dev_warn(cs->dev, "mic_survey: ioremap(0x%08x) failed\n", MIC_BASE);
		return;
	}

	for (i = 0; i < MIC_SURVEY_BYTES; i += 2)
		dev_info(cs->dev, "mic_survey: +0x%02x = 0x%04x\n",
			 i, ioread16(mic + i));

	iounmap(mic);
}

'''
src = src.replace(anchor, adc + anchor, 1)

# ----------------------------------------------------- 6. init lock + survey
anchor = """	cs->misc.minor = MISC_DYNAMIC_MINOR;"""
if anchor not in src:
    sys.exit("probe misc: anchor not found")
src = src.replace(anchor, """	mutex_init(&cs->cap_lock);

	if (mic_survey)
		mic_block_survey(cs);

	cs->misc.minor = MISC_DYNAMIC_MINOR;""", 1)

# ---------------------------------------------- 7. stop capture on release
anchor = """	mutex_lock(&cs->lock);
	ctr_csnd_arm_drain(cs);
	mutex_unlock(&cs->lock);
	return 0;
}"""
if anchor not in src:
    sys.exit("release: anchor not found")
src = src.replace(anchor, """	mutex_lock(&cs->lock);
	ctr_csnd_arm_drain(cs);
	mutex_unlock(&cs->lock);

	mutex_lock(&cs->cap_lock);
	cs->cap_on = false;
	mutex_unlock(&cs->cap_lock);
	return 0;
}""", 1)

# --------------------------------------------------- 8. advertise in the banner
anchor = '"CSND audio ready: /dev/eac accepts 16-bit stereo PCM at %u Hz\\n"'
if anchor in src:
    src = src.replace(
        anchor,
        '"CSND audio ready: /dev/eac accepts 16-bit stereo PCM at %u Hz, '
        'and returns 16-bit mono at 8000 Hz on read\\n"', 1)

with io.open(SRC, "w", encoding="utf-8", newline="\n") as f:
    f.write(src)

print("  - ctr_csnd.c: capture fop, pacing, codec ADC bring-up, opt-in MIC survey")
