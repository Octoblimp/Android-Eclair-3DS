#!/usr/bin/env python3
"""Install the first hardware-safe Linux PICA200 ownership driver.

The driver deliberately exposes owned coherent buffers, not raw MMIO.  A
command list is parsed in-kernel before the P3D engine can see it, completion
is IRQ driven, and a bounded timeout forces the command processor back to an
idle state.  This is the kernel boundary required by the Android EGL HAL.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
LINUX = ROOT / "third_party/linux"
PLAT = LINUX / "drivers/platform/nintendo3ds"
DTS = LINUX / "arch/arm/boot/dts/nintendo3ds.dtsi"
KCONFIG = PLAT / "Kconfig"
MAKEFILE = PLAT / "Makefile"
DEFCONFIG = LINUX / "arch/arm/configs/nintendo3ds_defconfig"
UAPI = LINUX / "include/uapi/linux/ctr_pica.h"
DRIVER = PLAT / "ctr_pica.c"


UAPI_TEXT = r'''/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef _UAPI_LINUX_CTR_PICA_H
#define _UAPI_LINUX_CTR_PICA_H

#include <linux/ioctl.h>
#include <linux/types.h>

#define CTR_PICA_IOC_MAGIC 'P'
#define CTR_PICA_ABI_VERSION 3

#define CTR_PICA_FORMAT_RGBA8  0
#define CTR_PICA_FORMAT_RGB8   1
#define CTR_PICA_FORMAT_RGB565 2
#define CTR_PICA_FORMAT_RGB5A1 3
#define CTR_PICA_FORMAT_RGBA4  4

#define CTR_PICA_TRANSFER_FLIP_VERT 0x0001
#define CTR_PICA_TRANSFER_BLOCK32   0x0002

struct ctr_pica_alloc {
	__u32 size;
	__u32 flags;
	__u32 handle;
	__u32 gpu_address;
};

struct ctr_pica_free {
	__u32 handle;
	__u32 reserved;
};

struct ctr_pica_submit {
	__u32 handle;
	__u32 offset;
	__u32 length;
	__u32 timeout_ms;
	__u64 sequence;
};

struct ctr_pica_transfer {
	__u32 src_handle;
	__u32 src_offset;
	__u32 dst_handle;
	__u32 dst_offset;
	__u16 src_width;
	__u16 src_height;
	__u16 dst_width;
	__u16 dst_height;
	__u8 src_format;
	__u8 dst_format;
	__u16 flags;
	__u32 timeout_ms;
	__u64 sequence;
};

struct ctr_pica_info {
	__u32 abi_version;
	__u32 hardware_id;
	__u64 completed_sequence;
	__u32 reset_count;
	__u32 last_error;
	__u32 qualified;
	__u32 stage;
	__u32 wedged;
	__u32 irq_seen;
	__u32 watchdog_armed;
	__u64 ppf_completed_sequence;
};

#define CTR_PICA_IOC_ALLOC  _IOWR(CTR_PICA_IOC_MAGIC, 0x00, struct ctr_pica_alloc)
#define CTR_PICA_IOC_FREE   _IOW(CTR_PICA_IOC_MAGIC,  0x01, struct ctr_pica_free)
#define CTR_PICA_IOC_SUBMIT _IOWR(CTR_PICA_IOC_MAGIC, 0x02, struct ctr_pica_submit)
#define CTR_PICA_IOC_INFO   _IOR(CTR_PICA_IOC_MAGIC,  0x03, struct ctr_pica_info)
#define CTR_PICA_IOC_QUALIFY _IO(CTR_PICA_IOC_MAGIC,  0x04)
#define CTR_PICA_IOC_TRANSFER _IOWR(CTR_PICA_IOC_MAGIC, 0x05, struct ctr_pica_transfer)

#endif
'''


DRIVER_TEXT = r'''// SPDX-License-Identifier: GPL-2.0
/*
 * Nintendo 3DS PICA200 ownership and command-submission driver.
 *
 * N3DS_PICA_IRQ_DMA_OWNERSHIP
 *
 * The userspace ABI never maps GPU registers.  One opener owns PICA, all GPU
 * addresses originate in dma_alloc_coherent(), and every P3D command stream
 * is structurally checked before execution.  This keeps malformed Android GL
 * clients from turning a recoverable render failure into an ARM11 lockup.
 */

#define pr_fmt(fmt) "ctr-pica: " fmt

#include <linux/capability.h>
#include <linux/delay.h>
#include <linux/dma-mapping.h>
#include <linux/fs.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/list.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_address.h>
#include <linux/of_irq.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/wait.h>
#include <linux/workqueue.h>

#include <uapi/linux/ctr_pica.h>

#define PICA_REG_HW_ID              0x0000
#define PICA_REG_CLOCK              0x0004
#define PICA_REG_PSC0_CONTROL       0x001c
#define PICA_REG_PSC1_CONTROL       0x002c
#define PICA_REG_BUSY               0x0034
#define PICA_REG_PPF_CONTROL        0x0c18
#define PICA_REG_PPF_INPUT          0x0c00
#define PICA_REG_PPF_OUTPUT         0x0c04
#define PICA_REG_PPF_OUTPUT_DIM     0x0c08
#define PICA_REG_PPF_INPUT_DIM      0x0c0c
#define PICA_REG_PPF_FLAGS          0x0c10
#define PICA_REG_PPF_UNK            0x0c14
#define PICA_REG_INIT_1000          0x1000
#define PICA_REG_INIT_1080          0x1080
#define PICA_REG_INIT_10C0          0x10c0
#define PICA_REG_INIT_10D0          0x10d0
#define PICA_REG_CMD_SIZE           0x18e0
#define PICA_REG_CMD_ADDRESS        0x18e8
#define PICA_REG_CMD_START          0x18f0
#define PICA_REG_START_DRAW_FUNC0   0x1914

#define PICA_CLOCK_LCD_ONLY         0x00000100
#define PICA_CLOCK_ALL              0x00070100
#define PICA_BUSY_P3D               BIT(31)
#define PICA_BUSY_PPF               BIT(30)
#define PICA_FINALIZE_REG           0x0010
#define PICA_MAX_INTERNAL_REG       0x02ff
#define PICA_DEFAULT_TIMEOUT_MS     500
#define PICA_MAX_TIMEOUT_MS         2000
#define PICA_MAX_BUFFER_SIZE        (8 * 1024 * 1024)

/* The watchdog DT resource begins at the watchdog sub-block (0x17e00620),
 * so these are local offsets, not the combined TWD timer offsets. */
#define PICA_WDOG_LOAD              0x00
#define PICA_WDOG_CONTROL           0x08
#define PICA_WDOG_DISABLE           0x14
#define PICA_WDOG_CONTROL_RESET     0x0000ff09
#define PICA_WDOG_FIVE_SECONDS      2618280

struct ctr_pica_buffer {
	struct list_head node;
	u32 handle;
	size_t size;
	void *cpu;
	dma_addr_t dma;
};

struct ctr_pica;

struct ctr_pica_file {
	struct ctr_pica *pica;
	struct list_head buffers;
	struct mutex buffers_lock;
	u32 next_handle;
};

struct ctr_pica {
	struct device *dev;
	void __iomem *regs;
	void __iomem *watchdog_regs;
	int irq_p3d;
	int irq_ppf;
	bool irq_registered;
	bool ppf_irq_registered;
	struct miscdevice misc;
	struct mutex owner_lock;
	struct mutex submit_lock;
	bool owned;
	wait_queue_head_t wait;
	atomic64_t completed;
	atomic64_t ppf_completed;
	atomic_t resets;
	atomic_t last_error;
	atomic_t submission_armed;
	atomic_t ppf_armed;
	atomic_t irq_seen;
	atomic_t watchdog_armed;
	u32 hardware_id;
	u32 stage;
	bool wedged;
	bool qualified;
};

static inline u32 pica_read(struct ctr_pica *pica, u32 offset)
{
	return readl(pica->regs + offset);
}

static inline void pica_write(struct ctr_pica *pica, u32 offset, u32 value)
{
	writel(value, pica->regs + offset);
}

/* N3DS_PICA_QUALIFICATION_WATCHDOG
 * The ARM11 MPCore watchdog is private to each CPU.  Upstream deleted its old
 * generic driver because userspace could arm one CPU and ping another.  PICA
 * qualification avoids that bug by running both operations on CPU0.  Normal
 * boot never arms this watchdog; it only bounds the explicit risky MMIO
 * window, where START cannot run if the GPU wedges the ARM11 bus. */
static long pica_watchdog_arm_cpu0(void *arg)
{
	struct ctr_pica *pica = arg;

	writel(0x12345678, pica->watchdog_regs + PICA_WDOG_DISABLE);
	writel(0x87654321, pica->watchdog_regs + PICA_WDOG_DISABLE);
	writel(0, pica->watchdog_regs + PICA_WDOG_CONTROL);
	writel(PICA_WDOG_FIVE_SECONDS, pica->watchdog_regs + PICA_WDOG_LOAD);
	wmb();
	writel(PICA_WDOG_CONTROL_RESET,
	       pica->watchdog_regs + PICA_WDOG_CONTROL);
	atomic_set(&pica->watchdog_armed, 1);
	return 0;
}

static long pica_watchdog_disarm_cpu0(void *arg)
{
	struct ctr_pica *pica = arg;

	writel(0x12345678, pica->watchdog_regs + PICA_WDOG_DISABLE);
	writel(0x87654321, pica->watchdog_regs + PICA_WDOG_DISABLE);
	writel(0, pica->watchdog_regs + PICA_WDOG_CONTROL);
	wmb();
	atomic_set(&pica->watchdog_armed, 0);
	return 0;
}

static struct ctr_pica_buffer *pica_find_buffer(struct ctr_pica_file *file,
						 u32 handle)
{
	struct ctr_pica_buffer *buffer;

	list_for_each_entry(buffer, &file->buffers, node)
		if (buffer->handle == handle)
			return buffer;
	return NULL;
}

/* Reject nested command buffers: those six internal registers contain GPU
 * addresses and jump triggers and would bypass this validator completely. */
static bool pica_forbidden_register(u32 reg)
{
	/* N3DS_PICA_RELOCATION_REQUIRED: until submit ABI v3 carries a kernel-
	 * checked handle/offset relocation table, no userspace command may write
	 * any GPU state at all except FINALIZE.  Merely forbidding nested command
	 * buffers is insufficient: texture, framebuffer and vertex registers hold
	 * physical FCRAM addresses and could otherwise escape owned DMA objects. */
	return reg != PICA_FINALIZE_REG;
}

/* N3DS_PICA_COMMAND_VALIDATION
 * Commands are parameter/header pairs followed by 0..255 extra parameters
 * and optional 64-bit alignment padding.  GPUREG_FINALIZE must be the final
 * real command and the whole list must have the hardware-required 16-byte
 * alignment.  Until handle-based address relocation lands, FINALIZE is the
 * only accepted register; this makes the qualification API useful without
 * exposing arbitrary physical-memory DMA. */
static int pica_validate_commands(const u32 *words, size_t bytes)
{
	size_t count = bytes / sizeof(*words);
	size_t i = 0;
	bool finalized = false;

	if (!bytes || bytes > PICA_MAX_BUFFER_SIZE || (bytes & 0xf))
		return -EINVAL;

	while (i < count) {
		u32 header, reg, mask, extra, params, j;

		if (count - i < 2)
			return -EINVAL;
		header = words[i + 1];
		reg = header & 0xffff;
		mask = (header >> 16) & 0xf;
		extra = (header >> 20) & 0xff;
		params = extra + 1;

		if (header & 0x70000000)
			return -EINVAL;
		if (!mask || reg > PICA_MAX_INTERNAL_REG)
			return -EINVAL;
		if (header & BIT(31)) {
			if (reg + extra > PICA_MAX_INTERNAL_REG)
				return -EINVAL;
			for (j = 0; j <= extra; j++)
				if (pica_forbidden_register(reg + j))
					return -EPERM;
		} else if (pica_forbidden_register(reg)) {
			return -EPERM;
		}

		if (i + 2 + extra > count)
			return -EINVAL;
		if (reg == PICA_FINALIZE_REG) {
			if (params != 1 || words[i] == 0)
				return -EINVAL;
			finalized = true;
		}

		i += 2 + extra;
		if (extra & 1) {
			if (i >= count || words[i] != 0)
				return -EINVAL;
			i++;
		}
		if (finalized) {
			/* A second FINALIZE pair is permitted solely as 16-byte padding,
			 * matching libctru GPUCMD_Split(). */
			if (i == count)
				break;
			if (count - i != 2 || words[i] == 0 ||
			    (words[i + 1] & 0xffff) != PICA_FINALIZE_REG ||
			    (words[i + 1] & 0xfff00000))
				return -EINVAL;
			i += 2;
			break;
		}
	}

	return finalized && i == count ? 0 : -EINVAL;
}

static void pica_free_buffer(struct ctr_pica_file *file,
			     struct ctr_pica_buffer *buffer);

static irqreturn_t ctr_pica_p3d_irq(int irq, void *data)
{
	struct ctr_pica *pica = data;

	/* A stale edge must never qualify the engine. */
	if (!atomic_read(&pica->submission_armed))
		return IRQ_NONE;
	atomic_set(&pica->irq_seen, 1);
	atomic64_inc(&pica->completed);
	wake_up_all(&pica->wait);
	return IRQ_HANDLED;
}

static irqreturn_t ctr_pica_ppf_irq(int irq, void *data)
{
	struct ctr_pica *pica = data;
	u32 control;

	if (!atomic_read(&pica->ppf_armed))
		return IRQ_NONE;
	control = pica_read(pica, PICA_REG_PPF_CONTROL);
	if (!(control & BIT(8)))
		return IRQ_NONE;
	/* Acknowledge the level-high completion before waking the submitter. */
	pica_write(pica, PICA_REG_PPF_CONTROL, control & ~BIT(8));
	atomic64_inc(&pica->ppf_completed);
	wake_up_all(&pica->wait);
	return IRQ_HANDLED;
}

/* N3DS_PICA_TIMEOUT_RESET_RECOVERY
 * GX_GPU_CLK is a clock gate shared with display hardware, not a documented
 * reset. On timeout quarantine P3D without further MMIO, preserving scanout
 * and the independent START emergency power path. */
static void pica_recover_locked(struct ctr_pica *pica, int error)
{
	atomic_set(&pica->submission_armed, 0);
	atomic_set(&pica->ppf_armed, 0);
	WRITE_ONCE(pica->qualified, false);
	WRITE_ONCE(pica->wedged, true);
	atomic_inc(&pica->resets);
	atomic_set(&pica->last_error, error);
	dev_err_ratelimited(pica->dev,
		"GPU timeout/error %d; engine quarantined until reboot\n", error);
}

static u32 pica_format_bpp(u32 format)
{
	static const u8 bpp[] = { 4, 3, 2, 2, 2 };

	return format < ARRAY_SIZE(bpp) ? bpp[format] : 0;
}

static bool pica_transfer_conversion_supported(u32 src, u32 dst)
{
	if (src == CTR_PICA_FORMAT_RGBA8)
		return true;
	if (src == CTR_PICA_FORMAT_RGB8)
		return dst == CTR_PICA_FORMAT_RGB8;
	return src <= CTR_PICA_FORMAT_RGBA4 &&
	       dst >= CTR_PICA_FORMAT_RGB565 &&
	       dst <= CTR_PICA_FORMAT_RGBA4;
}

/* N3DS_PICA_PPF_VALIDATED_TRANSFER: PPF only sees addresses derived from two
 * live allocations owned by this file.  Restrict the ABI to documented
 * tiled-to-linear conversions with dimensions known to generate completion;
 * raw-copy, scaling, cropping quirks and arbitrary flags are not exposed. */
static long pica_ioctl_transfer(struct ctr_pica_file *file, unsigned long arg)
{
	struct ctr_pica_transfer request;
	struct ctr_pica_buffer *src, *dst;
	struct ctr_pica *pica = file->pica;
	u64 src_bytes, dst_bytes;
	u64 before;
	u32 src_bpp, dst_bpp, flags, timeout;
	long waited, watchdog_ret;
	int ret = 0;

	if (!READ_ONCE(pica->qualified) || READ_ONCE(pica->wedged))
		return -ENODEV;
	if (copy_from_user(&request, (void __user *)arg, sizeof(request)))
		return -EFAULT;
	if (request.flags & ~(CTR_PICA_TRANSFER_FLIP_VERT |
			      CTR_PICA_TRANSFER_BLOCK32))
		return -EINVAL;
	src_bpp = pica_format_bpp(request.src_format);
	dst_bpp = pica_format_bpp(request.dst_format);
	if (!src_bpp || !dst_bpp ||
	    !pica_transfer_conversion_supported(request.src_format,
						request.dst_format))
		return -EINVAL;
	if (request.src_width < 64 || request.src_height < 16 ||
	    request.dst_width < 64 || request.dst_height < 16 ||
	    request.dst_width > request.src_width ||
	    request.dst_height > request.src_height)
		return -EINVAL;
	if ((request.src_width * src_bpp) &
	    (request.src_format == CTR_PICA_FORMAT_RGB8 ? 15 : 7))
		return -EINVAL;
	if ((request.dst_width * dst_bpp) &
	    (request.dst_format == CTR_PICA_FORMAT_RGB8 ? 15 : 7))
		return -EINVAL;
	if ((request.flags & CTR_PICA_TRANSFER_BLOCK32) &&
	    ((request.src_width | request.src_height |
	      request.dst_width | request.dst_height) & 31))
		return -EINVAL;
	src_bytes = (u64)request.src_width * request.src_height * src_bpp;
	dst_bytes = (u64)request.dst_width * request.dst_height * dst_bpp;
	if ((request.src_offset & 7) || (request.dst_offset & 7) ||
	    request.src_handle == request.dst_handle)
		return -EINVAL;

	mutex_lock(&file->buffers_lock);
	src = pica_find_buffer(file, request.src_handle);
	dst = pica_find_buffer(file, request.dst_handle);
	if (!src || !dst) {
		ret = -ENOENT;
		goto out_buffers;
	}
	if (request.src_offset > src->size ||
	    src_bytes > src->size - request.src_offset ||
	    request.dst_offset > dst->size ||
	    dst_bytes > dst->size - request.dst_offset) {
		ret = -EINVAL;
		goto out_buffers;
	}

	mutex_lock(&pica->submit_lock);
	if (!pica->ppf_irq_registered) {
		pica_write(pica, PICA_REG_PPF_CONTROL,
			   pica_read(pica, PICA_REG_PPF_CONTROL) & ~BIT(8));
		ret = devm_request_irq(pica->dev, pica->irq_ppf,
				       ctr_pica_ppf_irq, 0,
				       "ctr-pica-ppf", pica);
		if (ret)
			goto out_submit;
		pica->ppf_irq_registered = true;
	}
	watchdog_ret = work_on_cpu(0, pica_watchdog_arm_cpu0, pica);
	if (watchdog_ret) {
		ret = watchdog_ret;
		goto out_submit;
	}
	before = atomic64_read(&pica->ppf_completed);
	atomic_set(&pica->ppf_armed, 1);
	flags = (request.src_format << 8) | (request.dst_format << 12);
	if (request.flags & CTR_PICA_TRANSFER_FLIP_VERT)
		flags |= BIT(0);
	if (request.flags & CTR_PICA_TRANSFER_BLOCK32)
		flags |= BIT(16);
	pica_write(pica, PICA_REG_PPF_INPUT,
		   (lower_32_bits(src->dma) + request.src_offset) >> 3);
	pica_write(pica, PICA_REG_PPF_OUTPUT,
		   (lower_32_bits(dst->dma) + request.dst_offset) >> 3);
	pica_write(pica, PICA_REG_PPF_OUTPUT_DIM,
		   request.dst_width | ((u32)request.dst_height << 16));
	pica_write(pica, PICA_REG_PPF_INPUT_DIM,
		   request.src_width | ((u32)request.src_height << 16));
	pica_write(pica, PICA_REG_PPF_FLAGS, flags);
	pica_write(pica, PICA_REG_PPF_UNK, 0);
	wmb();
	pica_write(pica, PICA_REG_PPF_CONTROL, 1);
	timeout = request.timeout_ms ?: PICA_DEFAULT_TIMEOUT_MS;
	timeout = min(timeout, (u32)PICA_MAX_TIMEOUT_MS);
	waited = wait_event_interruptible_timeout(pica->wait,
		atomic64_read(&pica->ppf_completed) != before,
		msecs_to_jiffies(timeout));
	atomic_set(&pica->ppf_armed, 0);
	if (waited <= 0 || (pica_read(pica, PICA_REG_PPF_CONTROL) & BIT(0))) {
		ret = waited < 0 ? waited : (waited ? -EIO : -ETIMEDOUT);
		pica_recover_locked(pica, ret);
	} else {
		request.sequence = atomic64_read(&pica->ppf_completed);
		ret = copy_to_user((void __user *)arg, &request,
				   sizeof(request)) ? -EFAULT : 0;
	}
	watchdog_ret = work_on_cpu(0, pica_watchdog_disarm_cpu0, pica);
	if (watchdog_ret && !ret)
		ret = watchdog_ret;
out_submit:
	mutex_unlock(&pica->submit_lock);
out_buffers:
	mutex_unlock(&file->buffers_lock);
	return ret;
}

static long pica_ioctl_alloc(struct ctr_pica_file *file, unsigned long arg)
{
	struct ctr_pica_alloc request;
	struct ctr_pica_buffer *buffer;
	size_t size;

	/* N3DS_PICA_SOFTWARE_FALLBACK_GATE: never expose a nominal GPU buffer
	 * after the boot probe failed.  ENODEV selects gralloc/libagl fallback. */
	if (!READ_ONCE(file->pica->qualified) || READ_ONCE(file->pica->wedged))
		return -ENODEV;
	if (copy_from_user(&request, (void __user *)arg, sizeof(request)))
		return -EFAULT;
	if (!request.size || request.size > PICA_MAX_BUFFER_SIZE || request.flags)
		return -EINVAL;
	size = PAGE_ALIGN(request.size);
	buffer = kzalloc(sizeof(*buffer), GFP_KERNEL);
	if (!buffer)
		return -ENOMEM;
	buffer->cpu = dma_alloc_coherent(file->pica->dev, size, &buffer->dma,
					 GFP_KERNEL | __GFP_ZERO);
	if (!buffer->cpu) {
		kfree(buffer);
		return -ENOMEM;
	}
	if (upper_32_bits(buffer->dma) || buffer->dma < 0x20000000 ||
	    buffer->dma >= 0x30000000 || (buffer->dma & 7)) {
		dma_free_coherent(file->pica->dev, size, buffer->cpu, buffer->dma);
		kfree(buffer);
		return -ERANGE;
	}
	buffer->size = size;
	mutex_lock(&file->buffers_lock);
	buffer->handle = ++file->next_handle;
	if (!buffer->handle)
		buffer->handle = ++file->next_handle;
	list_add_tail(&buffer->node, &file->buffers);
	mutex_unlock(&file->buffers_lock);
	request.handle = buffer->handle;
	request.size = size;
	request.gpu_address = lower_32_bits(buffer->dma);
	if (copy_to_user((void __user *)arg, &request, sizeof(request))) {
		mutex_lock(&file->buffers_lock);
		pica_free_buffer(file, buffer);
		mutex_unlock(&file->buffers_lock);
		return -EFAULT;
	}
	return 0;
}

static void pica_free_buffer(struct ctr_pica_file *file,
			     struct ctr_pica_buffer *buffer)
{
	list_del(&buffer->node);
	dma_free_coherent(file->pica->dev, buffer->size, buffer->cpu, buffer->dma);
	kfree(buffer);
}

static long pica_ioctl_free(struct ctr_pica_file *file, unsigned long arg)
{
	struct ctr_pica_free request;
	struct ctr_pica_buffer *buffer;

	if (copy_from_user(&request, (void __user *)arg, sizeof(request)))
		return -EFAULT;
	if (request.reserved)
		return -EINVAL;
	mutex_lock(&file->buffers_lock);
	buffer = pica_find_buffer(file, request.handle);
	if (!buffer) {
		mutex_unlock(&file->buffers_lock);
		return -ENOENT;
	}
	pica_free_buffer(file, buffer);
	mutex_unlock(&file->buffers_lock);
	return 0;
}

static long pica_ioctl_submit(struct ctr_pica_file *file, unsigned long arg)
{
	struct ctr_pica_submit request;
	struct ctr_pica_buffer *buffer;
	struct ctr_pica *pica = file->pica;
	void *command_cpu = NULL;
	dma_addr_t command_dma = 0;
	u64 before;
	u32 timeout;
	long waited;
	int ret;

	if (!READ_ONCE(pica->qualified) || READ_ONCE(pica->wedged))
		return -ENODEV;
	if (copy_from_user(&request, (void __user *)arg, sizeof(request)))
		return -EFAULT;
	if ((request.offset & 0xf) || !request.length ||
	    (request.length & 0xf))
		return -EINVAL;
	mutex_lock(&file->buffers_lock);
	buffer = pica_find_buffer(file, request.handle);
	if (!buffer) {
		ret = -ENOENT;
		goto out_buffers;
	}
	if (request.offset > buffer->size || request.length > buffer->size - request.offset) {
		ret = -EINVAL;
		goto out_buffers;
	}
	/* N3DS_PICA_IMMUTABLE_COMMAND_SNAPSHOT: userspace can mmap allocations.
	 * Validate and execute a private coherent copy so a racing client cannot
	 * replace checked words with physical addresses after validation. */
	command_cpu = dma_alloc_coherent(pica->dev, request.length, &command_dma,
					 GFP_KERNEL | __GFP_ZERO);
	if (!command_cpu) {
		ret = -ENOMEM;
		goto out_buffers;
	}
	if (upper_32_bits(command_dma) || command_dma < 0x20000000 ||
	    command_dma >= 0x30000000 || (command_dma & 0xf)) {
		ret = -ERANGE;
		goto out_buffers;
	}
	memcpy(command_cpu, (u8 *)buffer->cpu + request.offset, request.length);
	ret = pica_validate_commands(command_cpu, request.length);
	if (ret)
		goto out_buffers;

	timeout = request.timeout_ms ?: PICA_DEFAULT_TIMEOUT_MS;
	timeout = min(timeout, (u32)PICA_MAX_TIMEOUT_MS);
	mutex_lock(&pica->submit_lock);
	before = atomic64_read(&pica->completed);
	atomic_set(&pica->irq_seen, 0);
	atomic_set(&pica->submission_armed, 1);
	pica_write(pica, PICA_REG_CMD_SIZE, request.length >> 3);
	pica_write(pica, PICA_REG_CMD_ADDRESS,
		   lower_32_bits(command_dma) >> 3);
	wmb();
	pica_write(pica, PICA_REG_CMD_START, 1);
	waited = wait_event_interruptible_timeout(pica->wait,
		atomic64_read(&pica->completed) != before,
		msecs_to_jiffies(timeout));
	atomic_set(&pica->submission_armed, 0);
	if (waited == 0) {
		pica_recover_locked(pica, -ETIMEDOUT);
		ret = -ETIMEDOUT;
	} else if (waited < 0) {
		pica_recover_locked(pica, waited);
		ret = waited;
	} else if (pica_read(pica, PICA_REG_CMD_START) & 1) {
		pica_recover_locked(pica, -EIO);
		ret = -EIO;
	} else {
		atomic_set(&pica->last_error, 0);
		request.sequence = atomic64_read(&pica->completed);
		ret = copy_to_user((void __user *)arg, &request, sizeof(request)) ?
			-EFAULT : 0;
	}
	mutex_unlock(&pica->submit_lock);
out_buffers:
	if (command_cpu)
		dma_free_coherent(pica->dev, request.length, command_cpu,
				  command_dma);
	mutex_unlock(&file->buffers_lock);
	return ret;
}

static long ctr_pica_ioctl(struct file *filp, unsigned int cmd,
			   unsigned long arg)
{
	struct ctr_pica_file *file = filp->private_data;
	struct ctr_pica_info info;
	extern int ctr_pica_qualify(struct ctr_pica *pica);

	if (_IOC_TYPE(cmd) != CTR_PICA_IOC_MAGIC)
		return -ENOTTY;
	switch (cmd) {
	case CTR_PICA_IOC_ALLOC:
		return pica_ioctl_alloc(file, arg);
	case CTR_PICA_IOC_FREE:
		return pica_ioctl_free(file, arg);
	case CTR_PICA_IOC_SUBMIT:
		return pica_ioctl_submit(file, arg);
	case CTR_PICA_IOC_TRANSFER:
		return pica_ioctl_transfer(file, arg);
	case CTR_PICA_IOC_INFO:
		memset(&info, 0, sizeof(info));
		info.abi_version = CTR_PICA_ABI_VERSION;
		info.hardware_id = READ_ONCE(file->pica->hardware_id);
		info.completed_sequence = atomic64_read(&file->pica->completed);
		info.reset_count = atomic_read(&file->pica->resets);
		info.last_error = atomic_read(&file->pica->last_error);
		info.qualified = READ_ONCE(file->pica->qualified);
		info.stage = READ_ONCE(file->pica->stage);
		info.wedged = READ_ONCE(file->pica->wedged);
		info.irq_seen = atomic_read(&file->pica->irq_seen);
		info.watchdog_armed = atomic_read(&file->pica->watchdog_armed);
		info.ppf_completed_sequence =
			atomic64_read(&file->pica->ppf_completed);
		return copy_to_user((void __user *)arg, &info, sizeof(info)) ?
			-EFAULT : 0;
	case CTR_PICA_IOC_QUALIFY:
		return ctr_pica_qualify(file->pica);
	default:
		return -ENOTTY;
	}
}

static int ctr_pica_mmap(struct file *filp, struct vm_area_struct *vma)
{
	struct ctr_pica_file *file = filp->private_data;
	struct ctr_pica_buffer *buffer;
	u32 handle = vma->vm_pgoff;
	size_t length = vma->vm_end - vma->vm_start;
	int ret;

	mutex_lock(&file->buffers_lock);
	buffer = pica_find_buffer(file, handle);
	if (!buffer || length > buffer->size) {
		ret = -EINVAL;
	} else {
		vma->vm_pgoff = 0;
		ret = dma_mmap_coherent(file->pica->dev, vma, buffer->cpu,
					buffer->dma, buffer->size);
	}
	mutex_unlock(&file->buffers_lock);
	return ret;
}

static int ctr_pica_open(struct inode *inode, struct file *filp)
{
	struct miscdevice *misc = filp->private_data;
	struct ctr_pica *pica = container_of(misc, struct ctr_pica, misc);
	struct ctr_pica_file *file;

	if (!capable(CAP_SYS_RAWIO))
		return -EPERM;
	mutex_lock(&pica->owner_lock);
	if (pica->owned) {
		mutex_unlock(&pica->owner_lock);
		return -EBUSY;
	}
	pica->owned = true;
	mutex_unlock(&pica->owner_lock);
	file = kzalloc(sizeof(*file), GFP_KERNEL);
	if (!file) {
		mutex_lock(&pica->owner_lock);
		pica->owned = false;
		mutex_unlock(&pica->owner_lock);
		return -ENOMEM;
	}
	file->pica = pica;
	INIT_LIST_HEAD(&file->buffers);
	mutex_init(&file->buffers_lock);
	filp->private_data = file;
	return 0;
}

static int ctr_pica_release(struct inode *inode, struct file *filp)
{
	struct ctr_pica_file *file = filp->private_data;
	struct ctr_pica_buffer *buffer, *next;
	struct ctr_pica *pica = file->pica;

	mutex_lock(&file->buffers_lock);
	mutex_lock(&pica->submit_lock);
	if (READ_ONCE(pica->qualified) && !READ_ONCE(pica->wedged) &&
	    (pica_read(pica, PICA_REG_BUSY) &
	     (PICA_BUSY_P3D | PICA_BUSY_PPF)))
		pica_recover_locked(pica, -ECANCELED);
	mutex_unlock(&pica->submit_lock);
	list_for_each_entry_safe(buffer, next, &file->buffers, node)
		pica_free_buffer(file, buffer);
	mutex_unlock(&file->buffers_lock);
	kfree(file);
	mutex_lock(&pica->owner_lock);
	pica->owned = false;
	mutex_unlock(&pica->owner_lock);
	return 0;
}

static const struct file_operations ctr_pica_fops = {
	.owner = THIS_MODULE,
	.open = ctr_pica_open,
	.release = ctr_pica_release,
	.unlocked_ioctl = ctr_pica_ioctl,
	.mmap = ctr_pica_mmap,
	.llseek = no_llseek,
};

/* N3DS_PICA_PROBE_SELFTEST: explicit post-boot qualification. The list only
 * contains FINALIZE plus 16-byte alignment padding; it cannot draw or alter
 * either display controller. */
int ctr_pica_qualify(struct ctr_pica *pica)
{
	dma_addr_t dma;
	u32 *commands;
	u64 before;
	long waited;
	long watchdog_ret;
	int ret = 0;

	if (READ_ONCE(pica->wedged))
		return -EIO;
	if (READ_ONCE(pica->qualified))
		return 0;
	if (!pica->watchdog_regs)
		return -ENODEV;

	mutex_lock(&pica->submit_lock);
	watchdog_ret = work_on_cpu(0, pica_watchdog_arm_cpu0, pica);
	if (watchdog_ret) {
		ret = watchdog_ret;
		goto out_unlock;
	}
	/* N3DS_PICA_LAZY_IRQ_ENABLE: merely booting the kernel must not enable a
	 * potentially stale GPU interrupt.  Enable P3D only inside the watchdog-
	 * bounded qualification window. */
	if (!pica->irq_registered) {
		ret = devm_request_irq(pica->dev, pica->irq_p3d,
				       ctr_pica_p3d_irq, 0,
				       dev_name(pica->dev), pica);
		if (ret)
			goto out_disarm;
		pica->irq_registered = true;
	}
	/* N3DS_PICA_STAGED_QUALIFICATION: no GPU write occurs during kernel
	 * probe. Only a privileged post-boot request reaches this sequence. */
	WRITE_ONCE(pica->stage, 1);
	WRITE_ONCE(pica->hardware_id, pica_read(pica, PICA_REG_HW_ID));
	pica_write(pica, PICA_REG_INIT_1000, 0);
	pica_write(pica, PICA_REG_INIT_1080, 0x12345678);
	pica_write(pica, PICA_REG_INIT_10C0, 0xfffffff0);
	pica_write(pica, PICA_REG_INIT_10D0, 1);
	pica_write(pica, PICA_REG_START_DRAW_FUNC0, 1);
	wmb();
	WRITE_ONCE(pica->stage, 2);
	pica_write(pica, PICA_REG_CLOCK, PICA_CLOCK_ALL);
	pica_write(pica, 0x0050, 0x22221200);
	pica_write(pica, 0x0054,
		   (pica_read(pica, 0x0054) & ~0x0000ffff) | 0x00000ff2);
	pica_write(pica, PICA_REG_PPF_CONTROL,
		   pica_read(pica, PICA_REG_PPF_CONTROL) & ~0x0000ff00);
	pica_write(pica, PICA_REG_PSC0_CONTROL,
		   pica_read(pica, PICA_REG_PSC0_CONTROL) & ~0x000000ff);
	pica_write(pica, PICA_REG_PSC1_CONTROL,
		   pica_read(pica, PICA_REG_PSC1_CONTROL) & ~0x000000ff);
	wmb();
	WRITE_ONCE(pica->stage, 3);

	commands = dma_alloc_coherent(pica->dev, PAGE_SIZE, &dma,
				      GFP_KERNEL | __GFP_ZERO);
	if (!commands) {
		ret = -ENOMEM;
		pica_recover_locked(pica, ret);
		goto out_disarm;
	}
	/* PICA consumes ARM11 physical FCRAM addresses, not arbitrary DMA/IOMMU
	 * tokens. Linux's 3DS RAM mapping occupies the 0x20000000 window. */
	if (upper_32_bits(dma) || dma < 0x20000000 || dma >= 0x30000000) {
		ret = -ERANGE;
		pica_recover_locked(pica, ret);
		goto out_free;
	}
	commands[0] = 0x12345678;
	commands[1] = 0x000f0010;
	commands[2] = 0x12345678;
	commands[3] = 0x000f0010;
	before = atomic64_read(&pica->completed);
	atomic_set(&pica->irq_seen, 0);
	atomic_set(&pica->submission_armed, 1);
	WRITE_ONCE(pica->stage, 4);
	pica_write(pica, PICA_REG_CMD_SIZE, 16 >> 3);
	pica_write(pica, PICA_REG_CMD_ADDRESS, lower_32_bits(dma) >> 3);
	wmb();
	pica_write(pica, PICA_REG_CMD_START, 1);
	waited = wait_event_timeout(pica->wait,
		atomic64_read(&pica->completed) != before,
		msecs_to_jiffies(PICA_DEFAULT_TIMEOUT_MS));
	atomic_set(&pica->submission_armed, 0);
	if (!waited || !atomic_read(&pica->irq_seen) ||
	    (pica_read(pica, PICA_REG_CMD_START) & 1)) {
		ret = waited ? -EIO : -ETIMEDOUT;
		pica_recover_locked(pica, ret);
		dev_err(pica->dev, "PICA200_PROBE FAIL error=%d\n", ret);
	} else {
		WRITE_ONCE(pica->stage, 5);
		WRITE_ONCE(pica->qualified, true);
		dev_info(pica->dev, "PICA200_PROBE PASS P3D sequence=%llu dma=%08x\n",
			 (unsigned long long)atomic64_read(&pica->completed),
			 lower_32_bits(dma));
	}

out_free:
	dma_free_coherent(pica->dev, PAGE_SIZE, commands, dma);
out_disarm:
	watchdog_ret = work_on_cpu(0, pica_watchdog_disarm_cpu0, pica);
	if (watchdog_ret && !ret)
		ret = watchdog_ret;
out_unlock:
	mutex_unlock(&pica->submit_lock);
	return ret;
}

static int ctr_pica_probe(struct platform_device *pdev)
{
	struct ctr_pica *pica;
	struct device_node *watchdog_np;
	struct resource *resource;
	int ret;

	pica = devm_kzalloc(&pdev->dev, sizeof(*pica), GFP_KERNEL);
	if (!pica)
		return -ENOMEM;
	pica->dev = &pdev->dev;
	resource = platform_get_resource(pdev, IORESOURCE_MEM, 0);
	pica->regs = devm_ioremap_resource(&pdev->dev, resource);
	if (IS_ERR(pica->regs))
		return PTR_ERR(pica->regs);
	watchdog_np = of_find_compatible_node(NULL, NULL,
					      "arm,arm11mp-twd-wdt");
	if (watchdog_np) {
		pica->watchdog_regs = of_iomap(watchdog_np, 0);
		of_node_put(watchdog_np);
	}
	pica->irq_p3d = platform_get_irq_byname(pdev, "p3d");
	if (pica->irq_p3d < 0)
		return pica->irq_p3d;
	pica->irq_ppf = platform_get_irq_byname(pdev, "ppf");
	if (pica->irq_ppf < 0)
		return pica->irq_ppf;
	mutex_init(&pica->owner_lock);
	mutex_init(&pica->submit_lock);
	init_waitqueue_head(&pica->wait);
	atomic64_set(&pica->completed, 0);
	atomic64_set(&pica->ppf_completed, 0);
	atomic_set(&pica->resets, 0);
	atomic_set(&pica->last_error, 0);
	atomic_set(&pica->submission_armed, 0);
	atomic_set(&pica->ppf_armed, 0);
	atomic_set(&pica->irq_seen, 0);
	atomic_set(&pica->watchdog_armed, 0);
	pica->hardware_id = 0;
	pica->irq_registered = false;
	pica->ppf_irq_registered = false;
	pica->stage = 0;
	pica->wedged = false;
	pica->qualified = false;
	pica->misc.minor = MISC_DYNAMIC_MINOR;
	pica->misc.name = "pica200";
	pica->misc.fops = &ctr_pica_fops;
	pica->misc.parent = &pdev->dev;
	ret = misc_register(&pica->misc);
	if (ret)
		return ret;
	platform_set_drvdata(pdev, pica);
	/* N3DS_PICA_ENFORCED_BOOT_MMIO: probe performs qualification synchronously. */
	dev_info(&pdev->dev, "PICA200 P3D irq=%d, running boot qualification; watchdog=%s\n",
		 pica->irq_p3d, pica->watchdog_regs ? "ready" : "missing");
	ret = ctr_pica_qualify(pica);
	if (ret)
		dev_err(&pdev->dev, "Boot qualification failed: %d\n", ret);
	return 0;
}

static int ctr_pica_remove(struct platform_device *pdev)
{
	struct ctr_pica *pica = platform_get_drvdata(pdev);

	misc_deregister(&pica->misc);
	if (pica->watchdog_regs)
		iounmap(pica->watchdog_regs);
	return 0;
}

static const struct of_device_id ctr_pica_of_match[] = {
	{ .compatible = "nintendo,3ds-pica200" },
	{ }
};
MODULE_DEVICE_TABLE(of, ctr_pica_of_match);

static struct platform_driver ctr_pica_driver = {
	.probe = ctr_pica_probe,
	.remove = ctr_pica_remove,
	.driver = {
		.name = "ctr-pica200",
		.of_match_table = ctr_pica_of_match,
	},
};
module_platform_driver(ctr_pica_driver);

MODULE_DESCRIPTION("Nintendo 3DS PICA200 validated command driver");
MODULE_LICENSE("GPL");
'''


def insert_once(path: Path, marker: str, insertion: str) -> None:
    text = path.read_text()
    if insertion.strip() in text:
        return
    if marker not in text:
        raise SystemExit(f"{path}: marker not found: {marker!r}")
    path.write_text(text.replace(marker, insertion + marker, 1))


UAPI.parent.mkdir(parents=True, exist_ok=True)
UAPI.write_text(UAPI_TEXT)
DRIVER.write_text(DRIVER_TEXT)

insert_once(MAKEFILE, "obj-$(CONFIG_CTR_LCD)",
            "obj-$(CONFIG_CTR_PICA)\t+= ctr_pica.o\n\n")
insert_once(KCONFIG, "config CTR_LCD", r'''config CTR_PICA
	bool "Nintendo 3DS PICA200 GPU ownership"
	depends on MMU
	select DMA_SHARED_BUFFER
	default y
	help
	  Own the PICA200 register aperture and P3D completion interrupt. Exposes
	  validated command submission and coherent GPU buffers via /dev/pica200.


''')

dts_text = DTS.read_text()
if 'compatible = "nintendo,3ds-pica200";' not in dts_text:
    anchor = "\t\t/* I2C blocks */\n"
    node = r'''		pica200: gpu@10400000 {
			compatible = "nintendo,3ds-pica200";
			reg = <0x10400000 0x2000>;
			interrupts = <GIC_SPI 0x08 IRQ_TYPE_LEVEL_HIGH>,
				     <GIC_SPI 0x09 IRQ_TYPE_LEVEL_HIGH>,
				     <GIC_SPI 0x0C IRQ_TYPE_LEVEL_HIGH>,
				     <GIC_SPI 0x0D IRQ_TYPE_LEVEL_HIGH>;
			interrupt-names = "psc0", "psc1", "ppf", "p3d";
		};

'''
    if anchor not in dts_text:
        raise SystemExit("DTS insertion anchor not found")
    DTS.write_text(dts_text.replace(anchor, node + anchor, 1))
else:
    for irq in ("08", "09", "0C", "0D"):
        dts_text = dts_text.replace(
            f"GIC_SPI 0x{irq} IRQ_TYPE_EDGE_RISING",
            f"GIC_SPI 0x{irq} IRQ_TYPE_LEVEL_HIGH")
    DTS.write_text(dts_text)

defconfig = DEFCONFIG.read_text()
if "CONFIG_CTR_PICA=y" not in defconfig:
    if not defconfig.endswith("\n"):
        defconfig += "\n"
    defconfig += "CONFIG_CTR_PICA=y\n"
    DEFCONFIG.write_text(defconfig)

print("add_pica200_driver: read-only boot, staged qualification, fail-closed timeout installed")
