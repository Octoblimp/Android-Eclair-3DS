#!/usr/bin/env python3
"""N3DS_CAM_MEASURED_MAP: write the sweep down, then aim at what it cannot see.

The #301 capture contains the first real measurement of the CAM block, and it
is currently sitting in boot_progress.txt where the next session will not find
it.  Two findings, both stronger than they look:

  * The CAM port register file is TWENTY-FOUR BYTES.  Six of 2048 offsets
    responded, all of them inside +0x000..+0x016, and the other 4072 bytes
    read zero and take no bits.  The driver header still says the layout is
    unknown; it is not, it is small.
  * 0x10121000 answered the same six offsets with almost the same masks, and
    the mirror probe already proved it is not an alias.  Two ports, one
    design, confirmed twice.

And then the part that decides what to do next.  The sweep writes 0x5aa5 and
0xa55a, which are exact bitwise complements, so `wmask = r1 ^ r2` is exact for
every bit that is both writable and readable -- there is no pattern blind
spot.  A bit missing from wmask is therefore one of exactly four things: not
implemented, write-only, read-only status, or self-clearing.

A capture start bit is self-clearing by construction.  A frame-ready bit is
read-only by construction.  Neither can appear in wmask.  So the six holes in
CAM+000's mask (bits 0, 1, 5, 6, 7, 12) are not noise -- they are the only
place a start bit could be hiding, and the search space for the thing that
blocks this driver just went from 4096 bytes to six bits.

That is testable.  Set each dark bit alone, wait longer than one frame, and
watch the camera-bus interrupt, which is the one observable that says a frame
actually moved and which this driver has never once requested.  The sweep
already wrote both patterns to this register -- setting bits 0, 1, 5, 6, 7 and
12 in combination -- and the machine kept booting, so a single-bit walk adds
no exposure the last boot did not already survive.  Reading the FIFO is still
off the table (docs/CAMERA_RESEARCH.md: a read of an empty FIFO on this bus
can stall it); an interrupt count costs nothing and stalls nothing.
"""
from a3ds_paths import A3DS_ROOT
import io
import sys

LINUX = f"{A3DS_ROOT}/third_party/linux"
CAM = LINUX + "/drivers/platform/nintendo3ds/ctr_cam.c"
DOC = f"{A3DS_ROOT}/docs/CAMERA_RESEARCH.md"

# --------------------------------------------------------------- driver ---
src = io.open(CAM, encoding="utf-8").read()
orig = src

old = """ *    That is enough to power the block and find the sensors. It is NOT
 *  enough to capture a frame: there is no documented start bit, no
 *  frame-ready status and no known FIFO offset. So this driver
 *  deliberately registers no V4L2 device. Advertising a /dev/video0
 *  that can never produce a buffer would be worse than advertising
 *  nothing -- Android would open it and hang.
"""
old = old.replace(" *    That is enough", " *  That is enough")
new = """ *  That is enough to power the block and find the sensors. It is NOT
 *  enough to capture a frame: there is no documented start bit, no
 *  frame-ready status and no known FIFO offset. So this driver
 *  deliberately registers no V4L2 device. Advertising a /dev/video0
 *  that can never produce a buffer would be worse than advertising
 *  nothing -- Android would open it and hang.
 *
 *  Update, kernel #301: the register layout is no longer undocumented,
 *  because it has now been measured. See N3DS_CAM_MEASURED_MAP below.
 *  The port register file is twenty-four bytes, not four kilobytes, and
 *  the only bits that could hold a start or a frame-ready flag are the
 *  six the sweep is structurally unable to see. That is what the
 *  N3DS_CAM_CTRL_BIT_WALK probe goes after.
"""
assert old in src, "header scope-note anchor missing"
src = src.replace(old, new, 1)

# ------------------------------------------------- measured map + probe ---
mapdoc = '''/*
 * N3DS_CAM_MEASURED_MAP.
 *
 * The #301 writable-bit sweep is the first measurement of this block that
 * exists anywhere, and it is much more informative than its six lines of
 * output suggest.  Both camera ports, verbatim:
 *
 *     CAM +000 wmask=ef1c reset=0010     CAM1+000 wmask=ef0c reset=0000
 *     CAM +006 wmask=003f                CAM1+006 wmask=003f
 *     CAM +010 wmask=03fe                CAM1+010 wmask=03fe
 *     CAM +012 wmask=01ff                CAM1+012 wmask=01ff
 *     CAM +014 wmask=03fe                CAM1+014 wmask=03fe
 *     CAM +016 wmask=01ff                CAM1+016 wmask=01ff
 *     CAM: 6 of 2048 registers responded, CAM1: 6 of 2048
 *
 * fixed=0000 everywhere, and every other offset in both 4 KB apertures read
 * zero and took no bits.  Three things follow.
 *
 * The port register file is 0x18 bytes.  Not "mostly unmapped" -- 4072 of
 * 4096 bytes do not decode at all, and the sweep would have caught a
 * register that merely read as a constant, because it logs any offset whose
 * reset value is nonzero.  Whatever else this block needs, it is not asking
 * for it through this window.  That is consistent with the DMA path in
 * docs/CAMERA_RESEARCH.md: pixels leave through the FIFO at 0x10320000 under
 * CDMA peripheral 0x2/0x3, so no buffer address or length register is
 * expected here in the first place.
 *
 * +010/+014 take bits 1..9 and +012/+016 take bits 0..8: even X in 0..1022,
 * any Y in 0..511.  A 640x480 sensor needs 0..639 and 0..479, and a YUV 4:2:2
 * crop must begin and end on a chroma pair, which is exactly an even X.  The
 * fit is too tight to be coincidence, and it lines up register-for-register
 * with the only crop call the service API has -- four signed 16-bit values,
 * xStart, yStart, xEnd, yEnd.  Named accordingly below; still an inference,
 * flagged as one.
 *
 * +000 differs between the two ports in exactly one bit: bit 4 is writable on
 * port 0 and is set at reset there, and on port 1 it neither reads nor takes
 * a write.  A bit that exists on one port and not the other is not a format
 * or a size field.  Left unnamed on purpose.
 *
 * What the sweep CANNOT see, which is the useful part.  0x5aa5 and 0xa55a are
 * bitwise complements, so every bit gets written both ways and wmask = r1 ^ r2
 * is exact -- there is no pattern-dependent blind spot.  A bit absent from
 * wmask is therefore implemented-but-invisible, write-only, read-only status,
 * or self-clearing.  A capture trigger is self-clearing by construction and a
 * frame-ready flag is read-only by construction: neither one can ever appear
 * in wmask.  So the holes in CAM+000 -- bits 0, 1, 5, 6, 7 and 12, mask
 * 0x10e3 -- are precisely where the missing capture control has to live, and
 * they are the last six bits in the block that have not been accounted for.
 */
#define CAM_CTRL		0x000	/* control; dark bits are the target */
#define CAM_UNK006		0x006	/* six-bit field, unidentified */
#define CAM_TRIM_X0		0x010	/* inferred crop window, see above */
#define CAM_TRIM_Y0		0x012
#define CAM_TRIM_X1		0x014
#define CAM_TRIM_Y1		0x016
#define CAM_FILE_BYTES		0x018	/* measured extent of one port */
#define CAM_FILE_WORDS		(CAM_FILE_BYTES / 2)

/*
 * Longer than one frame at the MT9V113's default 30 fps, with room for the
 * sensor's own pipeline delay.  Six dark bits per port, two ports: this is
 * about 1.5 s of boot, against roughly 15 s for the aperture sweep it
 * replaces.
 */
#define CAM_FRAME_WAIT_MS	120

/*
 * An edge-triggered line with no status register to acknowledge is the
 * screaming-interrupt hazard the probe function has always named as its
 * reason for leaving these unrequested.  The hazard is real; the answer is a
 * counter and a muzzle, not permanent blindness.  Sixty-four is comfortably
 * more than the two or three edges a single frame can produce and far less
 * than a wedged line delivers in 120 ms.
 */
#define CAM_IRQ_STORM_LIMIT	64

static void ctr_cam_file_snapshot(void __iomem *base, u16 *w)
{
	unsigned int i;

	for (i = 0; i < CAM_FILE_WORDS; i++)
		w[i] = ioread16(base + i * 2);
}

static irqreturn_t ctr_cam_irq_handler(int irq, void *data)
{
	struct ctr_cam_irq_probe *p = data;

	if (atomic_inc_return(&p->count) > CAM_IRQ_STORM_LIMIT && !p->muzzled) {
		p->muzzled = true;
		disable_irq_nosync(irq);
	}
	return IRQ_HANDLED;
}

static void ctr_cam_irq_probe_start(struct ctr_cam *cam)
{
	static const char * const names[] = { "cam-bus0", "cam-bus1", "cam-y2r" };
	int irqs[3];
	unsigned int i;

	irqs[0] = cam->irq_bus0;
	irqs[1] = cam->irq_bus1;
	irqs[2] = cam->irq_y2r;

	for (i = 0; i < ARRAY_SIZE(names); i++) {
		struct ctr_cam_irq_probe *p = &cam->irqp[i];

		p->name = names[i];
		p->irq = irqs[i];
		p->muzzled = false;
		p->requested = false;
		atomic_set(&p->count, 0);

		if (p->irq <= 0) {
			dev_info(cam->dev, "%s: no irq in the DT, not watched\\n",
				 p->name);
			continue;
		}
		if (request_irq(p->irq, ctr_cam_irq_handler, 0, p->name, p)) {
			dev_warn(cam->dev, "%s: irq %d request failed\\n",
				 p->name, p->irq);
			continue;
		}
		p->requested = true;
	}
}

static void ctr_cam_irq_probe_stop(struct ctr_cam *cam)
{
	unsigned int i;

	for (i = 0; i < ARRAY_SIZE(cam->irqp); i++) {
		struct ctr_cam_irq_probe *p = &cam->irqp[i];

		if (!p->requested)
			continue;

		dev_info(cam->dev, "%s: %d interrupts during the walk%s\\n",
			 p->name, atomic_read(&p->count),
			 p->muzzled ? " (line muzzled at the storm limit)" : "");

		/* Balance the depth disable_irq_nosync() took before freeing. */
		if (p->muzzled)
			enable_irq(p->irq);
		free_irq(p->irq, p);
		p->requested = false;
	}
}

/*
 * N3DS_CAM_CTRL_BIT_WALK.
 *
 * Set one dark bit of CAM+000 at a time, hold it for longer than a frame,
 * and look at three things the previous sweep threw away: whether the bit
 * reads back at all, whether it is still set after the wait, and whether the
 * camera-bus interrupt fired while it was set.
 *
 * The third is the one that matters.  Every other signal here is ambiguous --
 * a bit that reads 0 might be unimplemented or might be a trigger that has
 * already done its job -- but an edge on cam-bus0 means the receiver moved
 * data, and nothing in this driver has ever caused one.  A single line saying
 * "bit 5: irq bus0+2" would be the capture path.
 *
 * Bounded the same way the sweep is: the walk restores CAM+000 within
 * microseconds of every write, the sweep immediately before it already wrote
 * all six of these bits at once and the boot survived, and both interrupt
 * lines are freed before probe returns, so the driver goes back to its
 * steady state of touching nothing.
 */
static void ctr_cam_ctrl_bit_walk(struct ctr_cam *cam, void __iomem *base,
				  const char *what)
{
	u16 idle[CAM_FILE_WORDS], now[CAM_FILE_WORDS];
	u16 saved, r1, r2, wmask, dark;
	unsigned int bit, i;

	saved = ioread16(base + CAM_CTRL);
	iowrite16(0x5aa5, base + CAM_CTRL);
	r1 = ioread16(base + CAM_CTRL);
	iowrite16(0xa55a, base + CAM_CTRL);
	r2 = ioread16(base + CAM_CTRL);
	iowrite16(saved, base + CAM_CTRL);

	wmask = r1 ^ r2;
	dark = (u16)~wmask;

	ctr_cam_file_snapshot(base, idle);

	dev_info(cam->dev,
		 "%s ctrl walk: reset=%04x wmask=%04x dark=%04x (%u bits to try)\\n",
		 what, saved, wmask, dark, hweight16(dark));

	for (bit = 0; bit < 16; bit++) {
		u16 one = BIT(bit), back;
		int c0, c1, cy;

		if (!(dark & one))
			continue;

		c0 = atomic_read(&cam->irqp[0].count);
		c1 = atomic_read(&cam->irqp[1].count);
		cy = atomic_read(&cam->irqp[2].count);

		iowrite16(saved | one, base + CAM_CTRL);
		back = ioread16(base + CAM_CTRL);
		msleep(CAM_FRAME_WAIT_MS);
		ctr_cam_file_snapshot(base, now);
		iowrite16(saved, base + CAM_CTRL);

		c0 = atomic_read(&cam->irqp[0].count) - c0;
		c1 = atomic_read(&cam->irqp[1].count) - c1;
		cy = atomic_read(&cam->irqp[2].count) - cy;

		dev_info(cam->dev,
			 "%s+000 bit %2u: wrote %04x read %04x  irq bus0+%d bus1+%d y2r+%d\\n",
			 what, bit, (u16)(saved | one), back, c0, c1, cy);

		/*
		 * A trigger that clears when its transfer finishes clears
		 * during the wait, not during the readback above.
		 */
		if (now[0] != back)
			dev_info(cam->dev,
				 "    %s+000 settled %04x -> %04x over %u ms -- self-clearing\\n",
				 what, back, now[0], CAM_FRAME_WAIT_MS);

		for (i = 1; i < CAM_FILE_WORDS; i++)
			if (now[i] != idle[i])
				dev_info(cam->dev,
					 "    %s+%03x changed %04x -> %04x while bit %u was set\\n",
					 what, i * 2, idle[i], now[i], bit);
	}

	dev_info(cam->dev, "%s ctrl walk done, register file restored\\n", what);
}

static void ctr_cam_start_probe(struct ctr_cam *cam)
{
	ctr_cam_irq_probe_start(cam);
	ctr_cam_ctrl_bit_walk(cam, cam->base, "CAM");
	if (cam->mirror)
		ctr_cam_ctrl_bit_walk(cam, cam->mirror, "CAM1");
	ctr_cam_irq_probe_stop(cam);
}

'''

anchor = "static int ctr_cam_probe(struct platform_device *pdev)\n"
assert anchor in src, "probe anchor missing"
assert "ctr_cam_ctrl_bit_walk" not in src, "walk already present"
src = src.replace(anchor, mapdoc + anchor, 1)

# ------------------------------------------------------------- plumbing ---
old = """struct ctr_cam {
	struct device *dev;
"""
new = """struct ctr_cam;

/* One per watched line; `data` for the shared handler below. */
struct ctr_cam_irq_probe {
	const char *name;
	int irq;
	bool requested;
	bool muzzled;
	atomic_t count;
};

struct ctr_cam {
	struct device *dev;
"""
assert old in src, "struct ctr_cam anchor missing"
src = src.replace(old, new, 1)

old = """	bool sensor0_present;
	bool sensor1_present;
};
"""
new = """	bool sensor0_present;
	bool sensor1_present;
	struct ctr_cam_irq_probe irqp[3];	/* bus0, bus1, y2r */
};
"""
assert old in src, "struct ctr_cam tail anchor missing"
src = src.replace(old, new, 1)

old = """#include <linux/io.h>
#include <linux/init.h>
"""
new = """#include <linux/io.h>
#include <linux/init.h>
#include <linux/atomic.h>
#include <linux/interrupt.h>
"""
assert old in src, "include anchor missing"
src = src.replace(old, new, 1)

old = """MODULE_PARM_DESC(sweep_bytes,
		 "bytes of each aperture to writable-bit sweep (default 4096, max 4096)");
"""
new = """MODULE_PARM_DESC(sweep_bytes,
		 "bytes of each aperture to writable-bit sweep (default 4096, max 4096)");

/* N3DS_CAM_CTRL_BIT_WALK, gated separately from dump_regs because it is the
 * cheap one: about 1.5 s against the sweep's 15 s, and it is the only probe
 * here that can produce a positive result rather than another map. */
static bool start_probe;
module_param(start_probe, bool, 0444);
MODULE_PARM_DESC(start_probe,
		 "walk the dark bits of CAM+000 with the camera interrupts watched (default off)");
"""
assert old in src, "sweep_bytes param anchor missing"
src = src.replace(old, new, 1)

# ------------------------------------------------------------ call site ---
old = """	} else {
		dev_info(cam->dev,
			 "register dump disabled; boot with ctr_cam.dump_regs=1 to collect one\\n");
	}
"""
new = """	} else {
		dev_info(cam->dev,
			 "register dump disabled; boot with ctr_cam.dump_regs=1 to collect one\\n");
	}

	if (start_probe)
		ctr_cam_start_probe(cam);
	else
		dev_info(cam->dev,
			 "control-bit walk disabled; boot with ctr_cam.start_probe=1 to run it\\n");
"""
assert old in src, "dump_regs else-branch anchor missing"
src = src.replace(old, new, 1)

# The comment above platform_get_irq_optional() now describes the old policy.
old = """	/* Interrupts are recorded but not requested: with no documented
	 * status register there is nothing an ISR could acknowledge, and an
	 * un-acked edge-triggered line would be a screaming-interrupt
	 * hazard. Numbers come from 3dbrew's ARM11 interrupt table. */
"""
new = """	/* Interrupts are recorded here and requested nowhere except inside
	 * ctr_cam_start_probe(), which watches them for the length of the
	 * bit walk and frees them again.  With no documented status register
	 * there is still nothing a long-lived ISR could acknowledge, so the
	 * steady state remains "not requested"; what changed in #302 is that
	 * a counted, muzzled, temporary handler is the only way to tell a
	 * control bit that starts a capture from one that does nothing.
	 * Numbers come from 3dbrew's ARM11 interrupt table. */
"""
assert old in src, "irq comment anchor missing"
src = src.replace(old, new, 1)

old = """	dev_info(cam->dev, "irqs: bus0=%d bus1=%d y2r=%d (not requested)\\n",
"""
new = """	dev_info(cam->dev, "irqs: bus0=%d bus1=%d y2r=%d\\n",
"""
assert old in src, "irq dev_info anchor missing"
src = src.replace(old, new, 1)

assert src != orig, "driver unchanged"
io.open(CAM, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + CAM)

# ------------------------------------------------------------------ doc ---
doc = io.open(DOC, encoding="utf-8").read()
docorig = doc

section = """## Measured register map — the sweep result, kernel #301

No part of this table is documented anywhere. All of it was measured on
hardware by writing `0x5aa5` and `0xa55a` to every 16-bit offset of each
aperture, restoring it, and taking `wmask = r1 ^ r2` (the writable, readable
bits) and `fixed = r1 & ~wmask` (what the rest reads as). The two patterns are
bitwise complements, so `wmask` is exact for every bit — there is no
pattern-dependent blind spot, which is what makes the *gaps* meaningful.

| Offset | CAM `wmask` | CAM1 `wmask` | reset | Reading |
|---|---|---|---|---|
| `+0x000` | `ef1c` | `ef0c` | `0010` / `0000` | control |
| `+0x006` | `003f` | `003f` | `0000` | 6-bit field, unidentified |
| `+0x010` | `03fe` | `03fe` | `0000` | crop `xStart`, even, 0–1022 |
| `+0x012` | `01ff` | `01ff` | `0000` | crop `yStart`, 0–511 |
| `+0x014` | `03fe` | `03fe` | `0000` | crop `xEnd`, even, 0–1022 |
| `+0x016` | `01ff` | `01ff` | `0000` | crop `yEnd`, 0–511 |

`fixed = 0000` at every offset, on both ports.

**The port register file is 24 bytes.** Six of 2048 offsets responded and the
other 4072 bytes read zero and took no bits. That is not "mostly unmapped" —
the sweep logs any offset with a nonzero reset value too, so a read-only
constant would have shown up. It is consistent with the DMA path below:
pixels leave through the FIFO at `0x10320000` under CDMA peripheral `0x2`/`0x3`,
so no buffer-address or length register is expected in this window at all.

**Two ports, one design.** `0x10121000` answered the same six offsets with the
same masks, which together with the alias probe (which it failed — see above)
settles the mirror question: it is camera port 1's own register file. The one
difference is bit 4 of `+0x000`: writable and set at reset on port 0, neither
readable nor writable on port 1. A bit that exists on one port and not the
other is not a format or size field; it is left unnamed.

**The crop window is a fit, not a guess.** `+0x010`/`+0x014` take bits 1–9
(even values, 0–1022) and `+0x012`/`+0x016` take bits 0–8 (0–511). A 640x480
sensor needs 0–639 and 0–479, and a YUV 4:2:2 crop must start and end on a
chroma pair — exactly an even X. Four registers, in `xStart, yStart, xEnd,
yEnd` order, is also the shape of the only trimming call the `cam:u` service
API exposes. Still an inference; marked as one in the driver.

### What the sweep structurally cannot see, and why that is the lead

A bit missing from `wmask` is one of exactly four things: not implemented,
write-only, read-only status, or self-clearing.

A capture trigger is self-clearing **by construction** — written 1, reads back
0. A frame-ready flag is read-only **by construction**. Neither can ever appear
in `wmask`, no matter how good the sweep is.

So the holes in `CAM+0x000` — bits **0, 1, 5, 6, 7, 12**, mask `0x10e3` — are
the only place the missing capture control can be, and they are the last bits
in the block unaccounted for. The search space for the one thing blocking this
driver went from 4096 bytes to six bits.

Kernel #302 tests them (`N3DS_CAM_CTRL_BIT_WALK`, `ctr_cam.start_probe=1`):
set each dark bit alone, hold it 120 ms — longer than one frame at the
MT9V113's default 30 fps — and count camera-bus interrupts while it is set.
The interrupt is the point. Every other signal is ambiguous (a bit reading 0
may be unimplemented or may be a trigger that already fired), but an edge on
cam-bus0 means the receiver moved data, and nothing this driver has ever done
has caused one. The FIFO is still not read: an empty-FIFO read can stall the
bus, and an interrupt count cannot.

"""

anchor = "## Interrupts\n"
assert anchor in doc, "Interrupts anchor missing"
assert "Measured register map" not in doc, "section already present"
doc = doc.replace(anchor, section + anchor, 1)

old = """1. **The entire CAM register layout at `0x10120000`** — no start/stop bit, no
   frame-ready status, no resolution or format fields. This is the blocker,
   and it is now the *only* blocker of the original five.
"""
new = """1. **The capture control bits of `CAM+0x000`** — narrowed, not resolved. The
   register *layout* is no longer unknown: it was measured, it is 24 bytes
   wide, and four of its six registers are a crop window (see the measured
   map above). What is still missing is the start bit and the frame-ready
   flag, and both are necessarily invisible to a write-readback sweep, which
   places them in the six dark bits of `CAM+0x000`. This is still the
   blocker; it is a six-bit blocker instead of a 4096-byte one.
"""
assert old in doc, "unknown-item-1 anchor missing"
doc = doc.replace(old, new, 1)

old = """1. **Disassemble the `cam` sysmodule** from a retail firmware dump. This is
   the only route to the register layout. The tree already has a Ghidra setup
   used for the DSP work.
"""
new = """1. **Run the control-bit walk on hardware** (`ctr_cam.start_probe=1`) and read
   the interrupt counts. This is now first, ahead of disassembly, because it
   costs 1.5 s of one boot and can return a positive result rather than more
   map. See the measured-map section above for what it is testing and why the
   six bits it tries are the only candidates.
2. **Disassemble the `cam` sysmodule** from a retail firmware dump. Blocked as
   of 2026-09-12: there is no cam binary in the tree. `content/code.bin` is
   the **nwm** sysmodule, and `scratch/` holds only the DSP, nwm and PICA
   corpora. This needs a firmware dump that has not been made yet, so it
   cannot be the next step even though it is the most complete one.
"""
assert old in doc, "look-next item-1 anchor missing"
doc = doc.replace(old, new, 1)

old = """2. ~~Azahar / Citra's `core/hw/camera`~~"""
new = """3. ~~Azahar / Citra's `core/hw/camera`~~"""
assert old in doc, "look-next item-2 anchor missing"
doc = doc.replace(old, new, 1)

old = """3. libctru's `cam.h` / `y2r.h`"""
new = """4. libctru's `cam.h` / `y2r.h`"""
assert old in doc, "look-next item-3 anchor missing"
doc = doc.replace(old, new, 1)

assert doc != docorig, "doc unchanged"
io.open(DOC, "w", encoding="utf-8", newline="\n").write(doc)
print("patched " + DOC)
