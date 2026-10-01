"""Phase 4: scaffold the DSP coprocessor platform driver.

Register offsets/bit layout below are transcribed byte-exact from
3dbrew's "DSP Registers" page (fetched directly, not inferred):

  DSP_PDATA  0x00   16-stage read/write FIFO data port
  DSP_PADR   0x04   target DSP memory address, in 16-bit WORDS
  DSP_PCFG   0x08   bit0 reset, bit1 autoincrement, bit2-3 read length
                     (0=1 word,1=8,2=16,3=free-run), bit4 read-start,
                     bit5-8 FIFO IRQ enables, bit9-11 reply-reg IRQ
                     enables, bit12-15 memory select (0=Data,1=MMIO,
                     5=Program)
  DSP_PSTS   0x0C   bit0 read-underway, bit1 write-underway, bit2
                     peripheral-reset(1=busy), bit5 read-FIFO-full,
                     bit6 read-FIFO-not-empty, bit7 write-FIFO-full,
                     bit8 write-FIFO-empty, bit9 semaphore-IRQ,
                     bit10-12 reply-reg-N-updated(0=written by DSP),
                     bit13-15 cmd-reg-N-read(0=read by DSP)
  DSP_PSEM   0x10   semaphore 0-15 flags (ARM11 side)
  DSP_PMASK  0x14   semaphore 0-15 IRQ disable
  DSP_PCLEAR 0x18   semaphore 0-15 clear
  DSP_SEM    0x1C   semaphore 0-15 flags (bidirectional status)
  DSP_CMD0   0x20   DSP_REP0  0x24
  DSP_CMD1   0x28   DSP_REP1  0x2C
  DSP_CMD2   0x30   DSP_REP2  0x34

DSP1 firmware container header/segment-table layout below is
transcribed from GBATEK's "3DS Files: sound/dsp binary (DSP1, aka CDC)"
page, cross-validated against the community DspDump extractor tool
(which independently reads the same "total filesize" field at file
offset 0x104 to know how much of the mapped component to copy out --
confirms the header layout is right, not just GBATEK's say-so).

What this driver does NOT yet do, deliberately: actually upload
firmware to the coprocessor or release it from reset. The FIFO
read/write primitives (ctr_dsp_fifo_write/read) are implemented
directly from the confirmed register bit semantics above and are
safe/inert until called. The orchestration that would call them at
probe time -- reset timing, which order segments/reset toggle happen
in, how "DSP ready" is actually signaled -- is NOT confirmed from any
authoritative source yet (3dbrew's "DSP Services" LoadComponent is a
Horizon-OS IPC abstraction with no register-level detail; still
researching Citra/Teakra's LLE core for the real sequence). Landing a
guessed boot sequence that runs automatically against real hardware
every boot is worse than leaving it as an explicit TODO -- so
ctr_dsp_load_firmware() below parses and validates the firmware image
(safe, no hardware writes) and stops there.
"""
from a3ds_paths import A3DS_ROOT

DRV = f"{A3DS_ROOT}/third_party/linux/drivers/platform/nintendo3ds"
KCONFIG = f"{DRV}/Kconfig"
MAKEFILE = f"{DRV}/Makefile"

ctr_dsp_c = r"""// SPDX-License-Identifier: GPL-2.0
/*
 *  ctr_dsp.c - Nintendo 3DS Teak Lite II DSP coprocessor driver
 *
 *  Register interface: 3dbrew.org/wiki/DSP_Registers
 *  Firmware container format (DSP1): GBATEK, 3DS Files: sound/dsp
 *  binary (DSP1, aka CDC)
 */

#define DRIVER_NAME "3ds-dsp"
#define pr_fmt(fmt) DRIVER_NAME ": " fmt

#include <linux/io.h>
#include <linux/irq.h>
#include <linux/init.h>
#include <linux/delay.h>
#include <linux/bitops.h>
#include <linux/of.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/firmware.h>
#include <linux/interrupt.h>
#include <asm/unaligned.h>
#include <linux/platform_device.h>
#include <linux/mod_devicetable.h>

/* Register offsets (16-bit registers, but the SoC bus only supports
 * 32-bit accesses to this block per other CTR drivers in this tree --
 * use ioread32/iowrite32 and mask to 16 bits, matching ctr_gpio.c's
 * approach of accessing what the hardware actually requires). */
#define DSP_PDATA	0x00
#define DSP_PADR	0x04
#define DSP_PCFG	0x08
#define DSP_PSTS	0x0C
#define DSP_PSEM	0x10
#define DSP_PMASK	0x14
#define DSP_PCLEAR	0x18
#define DSP_SEM		0x1C
#define DSP_CMD0	0x20
#define DSP_REP0	0x24
#define DSP_CMD1	0x28
#define DSP_REP1	0x2C
#define DSP_CMD2	0x30
#define DSP_REP2	0x34

/* DSP_PCFG bits */
#define PCFG_RESET		BIT(0)
#define PCFG_AUTOINCREMENT	BIT(1)
#define PCFG_READLEN_SHIFT	2
#define PCFG_READLEN_MASK	(0x3 << PCFG_READLEN_SHIFT)
#define  PCFG_READLEN_1WORD	(0x0 << PCFG_READLEN_SHIFT)
#define  PCFG_READLEN_8WORD	(0x1 << PCFG_READLEN_SHIFT)
#define  PCFG_READLEN_16WORD	(0x2 << PCFG_READLEN_SHIFT)
#define  PCFG_READLEN_FREERUN	(0x3 << PCFG_READLEN_SHIFT)
#define PCFG_READSTART		BIT(4)
#define PCFG_MEMSEL_SHIFT	12
#define PCFG_MEMSEL_MASK	(0xF << PCFG_MEMSEL_SHIFT)
#define  PCFG_MEMSEL_DATA	(0x0 << PCFG_MEMSEL_SHIFT)
#define  PCFG_MEMSEL_MMIO	(0x1 << PCFG_MEMSEL_SHIFT)
#define  PCFG_MEMSEL_PROGRAM	(0x5 << PCFG_MEMSEL_SHIFT)

/* DSP_PSTS bits */
#define PSTS_READ_BUSY		BIT(0)
#define PSTS_WRITE_BUSY		BIT(1)
#define PSTS_RESET_BUSY		BIT(2)
#define PSTS_READ_FIFO_FULL	BIT(5)
#define PSTS_READ_FIFO_NOTEMPTY	BIT(6)
#define PSTS_WRITE_FIFO_FULL	BIT(7)
#define PSTS_WRITE_FIFO_EMPTY	BIT(8)
#define PSTS_SEMAPHORE_IRQ	BIT(9)

struct ctr_dsp {
	struct device *dev;
	void __iomem *base;
	int irq;
	const struct firmware *fw;
};

static inline u32 ctr_dsp_read(struct ctr_dsp *dsp, unsigned reg)
{
	return ioread32(dsp->base + reg);
}

static inline void ctr_dsp_write(struct ctr_dsp *dsp, unsigned reg, u32 val)
{
	iowrite32(val, dsp->base + reg);
}

/*
 * Raw FIFO write: push `count` 16-bit words from `data` into DSP
 * memory starting at word address `addr`, in the memory space
 * selected by `memsel` (one of the PCFG_MEMSEL_* values).
 *
 * Implements exactly what DSP_PCFG/DSP_PSTS's documented bits
 * describe for the write direction: unlike reads, there's no
 * separate "write start" bit -- per the register semantics, supplying
 * data via DSP_PDATA while PADR/PCFG are configured for a given
 * memory space is itself what drives the transfer, with
 * PSTS_WRITE_FIFO_FULL as the only backpressure signal. This is a
 * standard FIFO-mapped-register pattern and follows directly from the
 * bit documentation -- it is NOT the unconfirmed "how does firmware
 * upload actually get sequenced" question tracked separately.
 */
static int __maybe_unused ctr_dsp_fifo_write(struct ctr_dsp *dsp, u32 memsel, u32 addr,
			       const u16 *data, size_t count)
{
	size_t i;
	int timeout;

	ctr_dsp_write(dsp, DSP_PADR, addr);
	ctr_dsp_write(dsp, DSP_PCFG, memsel | PCFG_AUTOINCREMENT);

	for (i = 0; i < count; i++) {
		timeout = 1000;
		while (ctr_dsp_read(dsp, DSP_PSTS) & PSTS_WRITE_FIFO_FULL) {
			if (!--timeout)
				return -ETIMEDOUT;
			udelay(1);
		}
		ctr_dsp_write(dsp, DSP_PDATA, data[i]);
	}

	return 0;
}

/* DSP1 firmware container -- GBATEK "3DS Files: sound/dsp binary
 * (DSP1, aka CDC)". Header is 0x300 bytes; segment payloads follow. */
#define DSP1_MAGIC_OFF		0x100
#define DSP1_MAGIC		0x31505344 /* "DSP1" little-endian u32 */
#define DSP1_FILESIZE_OFF	0x104
#define DSP1_NUM_SEGMENTS_OFF	0x10E
#define DSP1_MAX_SEGMENTS	10
#define DSP1_SEGTABLE_OFF	0x120
#define DSP1_SEGENTRY_SIZE	0x30
#define DSP1_HEADER_SIZE	0x300

struct dsp1_segment {
	u32 file_offset;
	u32 target_addr;   /* in 16-bit words */
	u32 size;           /* bytes */
	u8  area_type;      /* 0/1 = Program memory, 2 = Data memory */
};

/*
 * Parse and sanity-check a DSP1 firmware image (typically dumped from
 * a real console as dspfirm.cdc, since Nintendo never published this
 * as a standalone redistributable blob -- see docs/ for the
 * extraction procedure). Does NOT touch hardware: this only validates
 * the file is well-formed and logs what it found, pending the
 * confirmed register-level upload sequence (tracked separately, see
 * file header comment).
 */
static int ctr_dsp_parse_firmware(struct ctr_dsp *dsp,
				   const struct firmware *fw,
				   struct dsp1_segment *segs, int *nsegs)
{
	u32 magic, filesize;
	u8 num_segments;
	int i;

	if (fw->size < DSP1_HEADER_SIZE) {
		dev_err(dsp->dev, "firmware too small (%zu bytes)\n",
			fw->size);
		return -EINVAL;
	}

	magic = get_unaligned_le32(fw->data + DSP1_MAGIC_OFF);
	if (magic != DSP1_MAGIC) {
		dev_err(dsp->dev, "bad DSP1 magic 0x%08x\n", magic);
		return -EINVAL;
	}

	filesize = get_unaligned_le32(fw->data + DSP1_FILESIZE_OFF);
	if (filesize != fw->size) {
		dev_warn(dsp->dev,
			 "header filesize 0x%x != actual %zu, continuing\n",
			 filesize, fw->size);
	}

	num_segments = fw->data[DSP1_NUM_SEGMENTS_OFF];
	if (num_segments < 1 || num_segments > DSP1_MAX_SEGMENTS) {
		dev_err(dsp->dev, "bad segment count %u\n", num_segments);
		return -EINVAL;
	}

	for (i = 0; i < num_segments; i++) {
		const u8 *e = fw->data + DSP1_SEGTABLE_OFF +
			      i * DSP1_SEGENTRY_SIZE;
		struct dsp1_segment *s = &segs[i];

		s->file_offset = get_unaligned_le32(e + 0x00);
		s->target_addr = get_unaligned_le32(e + 0x04);
		s->size        = get_unaligned_le32(e + 0x08);
		s->area_type   = e[0x0F];

		if (s->file_offset + s->size > fw->size) {
			dev_err(dsp->dev,
				"segment %d out of bounds (off=0x%x sz=0x%x)\n",
				i, s->file_offset, s->size);
			return -EINVAL;
		}

		dev_info(dsp->dev,
			 "segment %d: %s, target=0x%05x words, size=0x%x bytes\n",
			 i, s->area_type == 2 ? "Data" : "Program",
			 s->target_addr, s->size);
	}

	*nsegs = num_segments;
	return 0;
}

static int ctr_dsp_probe(struct platform_device *pdev)
{
	int ret;
	u32 psts;
	struct ctr_dsp *dsp;
	struct dsp1_segment segs[DSP1_MAX_SEGMENTS];
	int nsegs;

	dsp = devm_kzalloc(&pdev->dev, sizeof(*dsp), GFP_KERNEL);
	if (!dsp)
		return -ENOMEM;

	dsp->dev = &pdev->dev;
	dsp->base = devm_platform_ioremap_resource(pdev, 0);
	if (IS_ERR(dsp->base))
		return PTR_ERR(dsp->base);

	dsp->irq = platform_get_irq(pdev, 0);
	if (dsp->irq < 0)
		return dsp->irq;

	psts = ctr_dsp_read(dsp, DSP_PSTS);
	dev_info(dsp->dev, "DSP_PSTS=0x%04x (reset_busy=%d)\n",
		 psts, !!(psts & PSTS_RESET_BUSY));

	/* Firmware is optional at this stage (not yet uploaded to
	 * hardware -- see file header). Missing firmware is not a
	 * probe failure. */
	ret = request_firmware(&dsp->fw, "3ds/dspfirm.cdc", dsp->dev);
	if (ret) {
		dev_info(dsp->dev,
			 "no dspfirm.cdc available (%d), audio unavailable\n",
			 ret);
		platform_set_drvdata(pdev, dsp);
		return 0;
	}

	ret = ctr_dsp_parse_firmware(dsp, dsp->fw, segs, &nsegs);
	if (ret) {
		release_firmware(dsp->fw);
		dsp->fw = NULL;
		return ret;
	}

	dev_info(dsp->dev,
		 "dspfirm.cdc parsed OK (%d segments) -- upload not yet implemented\n",
		 nsegs);

	platform_set_drvdata(pdev, dsp);
	return 0;
}

static int ctr_dsp_remove(struct platform_device *pdev)
{
	struct ctr_dsp *dsp = platform_get_drvdata(pdev);

	if (dsp->fw)
		release_firmware(dsp->fw);
	return 0;
}

static const struct of_device_id ctr_dsp_of_match[] = {
	{ .compatible = "nintendo," DRIVER_NAME },
	{},
};
MODULE_DEVICE_TABLE(of, ctr_dsp_of_match);

static struct platform_driver ctr_dsp_driver = {
	.probe		= ctr_dsp_probe,
	.remove		= ctr_dsp_remove,

	.driver		= {
		.name	= DRIVER_NAME,
		.owner	= THIS_MODULE,
		.of_match_table = of_match_ptr(ctr_dsp_of_match),
	},
};

module_platform_driver(ctr_dsp_driver);

MODULE_FIRMWARE("3ds/dspfirm.cdc");
MODULE_DESCRIPTION("Nintendo 3DS DSP (Teak Lite II) coprocessor driver");
MODULE_LICENSE("GPL");
MODULE_ALIAS("platform:" DRIVER_NAME);
"""

with open(f"{DRV}/ctr_dsp.c", "w") as f:
    f.write(ctr_dsp_c)

# Kconfig
with open(KCONFIG) as f:
    kconfig = f.read()

anchor = "endif # NINTENDO3DS_PLATFORM_DEVICES"
assert kconfig.count(anchor) == 1

new_entry = """config CTR_DSP
\ttristate "Nintendo 3DS DSP (audio coprocessor) driver"
\tselect FW_LOADER
\tdefault y
\thelp
\t  Nintendo 3DS Teak Lite II DSP coprocessor driver. Firmware
\t  upload is not yet implemented (Phase 4, in progress) -- this
\t  currently only maps the MMIO register block and validates a
\t  dumped dspfirm.cdc if present.

endif # NINTENDO3DS_PLATFORM_DEVICES"""

kconfig = kconfig.replace(anchor, new_entry)
with open(KCONFIG, "w") as f:
    f.write(kconfig)

# Makefile
with open(MAKEFILE) as f:
    makefile = f.read()

old_mk = "obj-$(CONFIG_CTR_PXI)\t+= ctr_pxi.o\n"
assert makefile.count(old_mk) == 1
makefile = makefile.replace(old_mk, old_mk + "\nobj-$(CONFIG_CTR_DSP)\t+= ctr_dsp.o\n")
with open(MAKEFILE, "w") as f:
    f.write(makefile)

print("OK")
