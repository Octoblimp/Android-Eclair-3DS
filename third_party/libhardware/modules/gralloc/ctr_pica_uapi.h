/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
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
