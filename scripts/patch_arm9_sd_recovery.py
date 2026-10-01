#!/usr/bin/env python3
"""Bound ARM9 SD commands and make virtio/PXI cache and I/O failures explicit."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
SDMMC = ROOT / "third_party/arm9linuxfw/source/hw/sdmmc.c"
SDMMC_H = ROOT / "third_party/arm9linuxfw/include/hw/sdmmc.h"
SDCARD = ROOT / "third_party/arm9linuxfw/source/vdev/sdcard.c"
PXI = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_pxi.c"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


sdmmc = SDMMC.read_text()
if "N3DS_SDMMC_BOUNDED_COMMAND" not in sdmmc:
    sdmmc = replace_once(
        sdmmc,
        '#include "arm/arm.h"\n',
        '#include "arm/arm.h"\n#include "hw/timer.h"\n',
        "timer include",
    )
    start = sdmmc.index("static void sdmmc_send_command(")
    end = sdmmc.index("\nint sdmmc_sdcard_writesectors", start)
    bounded_command = r'''/* N3DS_SDMMC_BOUNDED_COMMAND: an ARM9 command must never hold a Linux
 * virtio request forever.  The old CMD_BUSY and DATAEND polls had no timeout;
 * one controller/card fault therefore stranded PID 1 in a VFAT syscall. */
#define SDMMC_COMMAND_TIMEOUT_MS 2000

static bool sdmmc_deadline_expired(u64 deadline)
{
	return timer_get_ticks() >= deadline;
}

static void sdmmc_abort_command(struct mmcdevice *ctx)
{
	ctx->error |= 4;
	sdmmc_mask16(REG_DATACTL32, 0x1800, 0x400);
	sdmmc_write16(REG_SDSTATUS0, 0);
	sdmmc_write16(REG_SDSTATUS1, 0);
	/* Leave the controller in a known idle state.  The request layer performs
	 * a complete SD reinitialization before its one retry. */
	sdmmc_write16(REG_SDRESET, 0);
	arm_delay_cycles(64);
	sdmmc_write16(REG_SDRESET, 1);
}

static void sdmmc_send_command(struct mmcdevice *ctx, u32 cmd, u32 args)
{
	const bool getSDRESP = (cmd << 15) >> 31;
	u16 flags = (cmd << 15) >> 31;
	const bool readdata = cmd & 0x20000;
	const bool writedata = cmd & 0x40000;
	u64 deadline = timer_get_ticks() +
		timer_ms_to_ticks(SDMMC_COMMAND_TIMEOUT_MS);

	if (readdata || writedata)
		flags |= TMIO_STAT0_DATAEND;

	ctx->error = 0;
	while (sdmmc_read16(REG_SDSTATUS1) & TMIO_STAT1_CMD_BUSY) {
		if (sdmmc_deadline_expired(deadline)) {
			sdmmc_abort_command(ctx);
			return;
		}
	}

	sdmmc_write16(REG_SDIRMASK0, 0);
	sdmmc_write16(REG_SDIRMASK1, 0);
	sdmmc_write16(REG_SDSTATUS0, 0);
	sdmmc_write16(REG_SDSTATUS1, 0);
	sdmmc_mask16(REG_DATACTL32, 0x1800, 0x400);
	sdmmc_write16(REG_SDCMDARG0, args & 0xFFFF);
	sdmmc_write16(REG_SDCMDARG1, args >> 16);
	sdmmc_write16(REG_SDCMD, cmd & 0xFFFF);

	u32 size = ctx->size;
	const u16 blkSize = sdmmc_read16(REG_SDBLKLEN32);
	u32 *rDataPtr32 = (u32*)(void*)ctx->rData;
	u8  *rDataPtr8  = ctx->rData;
	const u32 *tDataPtr32 = (u32*)(void*)ctx->tData;
	const u8  *tDataPtr8  = ctx->tData;
	bool rUseBuf = NULL != rDataPtr32;
	bool tUseBuf = NULL != tDataPtr32;
	u16 status0 = 0;

	while (1) {
		volatile u16 status1 = sdmmc_read16(REG_SDSTATUS1);
		volatile u16 ctl32 = sdmmc_read16(REG_DATACTL32);

		if (sdmmc_deadline_expired(deadline)) {
			sdmmc_abort_command(ctx);
			return;
		}

		if (ctl32 & 0x100) {
			if (readdata) {
				if (rUseBuf && size >= blkSize) {
					sdmmc_mask16(REG_SDSTATUS1, TMIO_STAT1_RXRDY, 0);
					for (u32 i = 0; i < blkSize; i += 16) {
						*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
						*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
						*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
						*rDataPtr32++ = sdmmc_read32(REG_SDFIFO32);
					}
					size -= blkSize;
				}
				sdmmc_mask16(REG_DATACTL32, 0x800, 0);
			}
		}
		if (!(ctl32 & 0x200)) {
			if (writedata) {
				if (tUseBuf && size >= blkSize) {
					sdmmc_mask16(REG_SDSTATUS1, TMIO_STAT1_TXRQ, 0);
					for (u32 i = 0; i < blkSize; i += 16) {
						sdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
						sdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
						sdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
						sdmmc_write32(REG_SDFIFO32, *tDataPtr32++);
					}
					size -= blkSize;
				}
				sdmmc_mask16(REG_DATACTL32, 0x1000, 0);
			}
		}

		if (status1 & TMIO_MASK_GW) {
			ctx->error |= 4;
			break;
		}

		if (!(status1 & TMIO_STAT1_CMD_BUSY)) {
			status0 = sdmmc_read16(REG_SDSTATUS0);
			if (status0 & TMIO_STAT0_CMDRESPEND)
				ctx->error |= 0x1;
			if (status0 & TMIO_STAT0_DATAEND)
				ctx->error |= 0x2;
			if ((status0 & flags) == flags)
				break;
		}
	}

	ctx->stat0 = sdmmc_read16(REG_SDSTATUS0);
	ctx->stat1 = sdmmc_read16(REG_SDSTATUS1);
	sdmmc_write16(REG_SDSTATUS0, 0);
	sdmmc_write16(REG_SDSTATUS1, 0);

	if (getSDRESP != 0) {
		ctx->ret[0] = (u32)(sdmmc_read16(REG_SDRESP0) | (sdmmc_read16(REG_SDRESP1) << 16));
		ctx->ret[1] = (u32)(sdmmc_read16(REG_SDRESP2) | (sdmmc_read16(REG_SDRESP3) << 16));
		ctx->ret[2] = (u32)(sdmmc_read16(REG_SDRESP4) | (sdmmc_read16(REG_SDRESP5) << 16));
		ctx->ret[3] = (u32)(sdmmc_read16(REG_SDRESP6) | (sdmmc_read16(REG_SDRESP7) << 16));
	}

	(void)rDataPtr8;
	(void)tDataPtr8;
}
'''
    sdmmc = sdmmc[:start] + bounded_command + sdmmc[end:]

    sdmmc = replace_once(
        sdmmc,
        '''\t\tdo
\t\t{
\t\t\tsdmmc_send_command(&handleNAND,0x10701,0x100000);
\t\t} while ( !(handleNAND.error & 1) );
''',
        '''\t\tdo
\t\t{
\t\t\tsdmmc_send_command(&handleNAND,0x10701,0x100000);
\t\t\tif (handleNAND.error & 4) return -1;
\t\t} while ( !(handleNAND.error & 1) );
''',
        "bounded NAND readiness",
    )
    sdmmc = replace_once(
        sdmmc,
        '''\t\t\tsdmmc_send_command(&handleSD,0x10437,handleSD.initarg << 0x10);
\t\t\tsdmmc_send_command(&handleSD,0x10769,0x10100000 | temp); // Allow 150mA, 3.2-3.3V (from Process9)
\t\t\ttemp2 = 1;
''',
        '''\t\t\tsdmmc_send_command(&handleSD,0x10437,handleSD.initarg << 0x10);
\t\t\tif (handleSD.error & 4) return -11;
\t\t\tsdmmc_send_command(&handleSD,0x10769,0x10100000 | temp); // Allow 150mA, 3.2-3.3V (from Process9)
\t\t\tif (handleSD.error & 4) return -12;
\t\t\ttemp2 = 1;
''',
        "bounded SD readiness",
    )
    sdmmc = replace_once(
        sdmmc,
        '''u32 sdmmc_sdcard_size(void)
{
\treturn handleSD.total_size;
}
''',
        '''/* N3DS_SDMMC_RECOVERY_RETRY: reset and renegotiate after a timed-out
 * runtime request.  This is called only after the original request failed. */
int sdmmc_sdcard_recover(void)
{
\tsdmmc_init();
\treturn SD_Init();
}

u32 sdmmc_sdcard_size(void)
{
\treturn handleSD.total_size;
}
''',
        "SD recovery helper",
    )
    sdmmc = sdmmc.replace("if(Nand_Init() != 0) ret &= 1;",
                          "if(Nand_Init() != 0) { ret |= 1; sdmmc_init(); }")
    sdmmc = sdmmc.replace("if(!timeout || SD_Init() != 0) ret &= 2;",
                          "if(!timeout || SD_Init() != 0) ret |= 2;")

if "N3DS_SDMMC_BOUNDED_COMMAND" not in sdmmc or "ret |= 2" not in sdmmc:
    raise SystemExit("ARM9 SD timeout/recovery patch incomplete")
SDMMC.write_text(sdmmc)


header = SDMMC_H.read_text()
if "sdmmc_sdcard_recover" not in header:
    header = replace_once(
        header,
        "\tint sdmmc_sdcard_writesectors(u32 sector_no, u32 numsectors, const u8 *in);\n",
        "\tint sdmmc_sdcard_writesectors(u32 sector_no, u32 numsectors, const u8 *in);\n"
        "\tint sdmmc_sdcard_recover(void);\n",
        "SD recovery declaration",
    )
SDMMC_H.write_text(header)


sdcard = SDCARD.read_text()
if "N3DS_VIRTIO_BLK_TRUTHFUL_STATUS" not in sdcard:
    sdcard = replace_once(
        sdcard,
        "#define VIRTIO_BLK_F_RO\tBIT(5)\n",
        "#define VIRTIO_BLK_F_RO\tBIT(5)\n"
        "#define VIRTIO_BLK_T_IN\t0\n"
        "#define VIRTIO_BLK_T_OUT\t1\n"
        "#define VIRTIO_BLK_S_OK\t0\n"
        "#define VIRTIO_BLK_S_IOERR\t1\n",
        "virtio block constants",
    )
    start = sdcard.index("static void sdmc_process_vqueue(")
    end = sdcard.index("\nDECLARE_VIRTDEV(", start)
    truthful = r'''/* N3DS_VIRTIO_BLK_TRUTHFUL_STATUS: one bounded recovery attempt, then
 * complete with IOERR.  Never leave Linux waiting forever and never claim a
 * failed SD transfer succeeded (the inherited backend did both). */
static int sdmc_transfer(bool write, u32 sector, u32 sectors, u8 *data)
{
	int ret;

	ret = write ? sdmmc_sdcard_writesectors(sector, sectors, data) :
		      sdmmc_sdcard_readsectors(sector, sectors, data);
	if (!ret)
		return 0;

	if (sdmmc_sdcard_recover())
		return -1;

	return write ? sdmmc_sdcard_writesectors(sector, sectors, data) :
		       sdmmc_sdcard_readsectors(sector, sectors, data);
}

static void sdmc_process_vqueue(vdev_s *vdev, vqueue_s *vq)
{
	vjob_s vjob;

	while (vqueue_fetch_job_new(vq, &vjob) >= 0) {
		bool header_seen = false;
		u32 type = ~0U;
		u32 sector = 0;
		u8 status = VIRTIO_BLK_S_OK;

		do {
			vdesc_s desc;
			vqueue_get_job_desc(vq, &vjob, &desc);

			if (!desc.data) {
				status = VIRTIO_BLK_S_IOERR;
				continue;
			}

			if (!header_seen) {
				if (desc.dir != HOST_TO_VDEV || desc.length < sizeof(vblk_t)) {
					status = VIRTIO_BLK_S_IOERR;
				} else {
					const vblk_t *blk = (const vblk_t*)desc.data;
					type = blk->type;
					sector = (u32)blk->sector_offset;
				}
				header_seen = true;
				continue;
			}

			if (desc.dir == VDEV_TO_HOST && desc.length < 512) {
				*(u8*)desc.data = status;
				vjob_add_written(&vjob, 1);
				continue;
			}

			if (status != VIRTIO_BLK_S_OK || desc.length < 512 ||
			    (desc.length & 511)) {
				status = VIRTIO_BLK_S_IOERR;
				continue;
			}

			u32 sectors = desc.length >> 9;
			bool write = desc.dir == HOST_TO_VDEV;
			if ((write && type != VIRTIO_BLK_T_OUT) ||
			    (!write && type != VIRTIO_BLK_T_IN) ||
			    sdmc_transfer(write, sector, sectors, desc.data)) {
				status = VIRTIO_BLK_S_IOERR;
				continue;
			}

			sector += sectors;
			if (!write)
				vjob_add_written(&vjob, desc.length);
		} while (vqueue_fetch_job_next(vq, &vjob) >= 0);

		vqueue_push_job(vq, &vjob);
	}

	vman_notify_host(vdev, VIRQ_VQUEUE);
}
'''
    sdcard = sdcard[:start] + truthful + sdcard[end:]

if "N3DS_VIRTIO_BLK_TRUTHFUL_STATUS" not in sdcard:
    raise SystemExit("ARM9 virtio block status patch incomplete")
SDCARD.write_text(sdcard)


pxi = PXI.read_text()
if "N3DS_PXI_REQUIRES_DMA_API" not in pxi:
    old = '''\tvring_transport_features(vdev);
\tif (!__virtio_test_bit(vdev, VIRTIO_F_VERSION_1))
\t\treturn -EINVAL;
'''
    new = '''\tvring_transport_features(vdev);
\tif (!__virtio_test_bit(vdev, VIRTIO_F_VERSION_1))
\t\treturn -EINVAL;

\t/* N3DS_PXI_REQUIRES_DMA_API: ARM9 is outside the ARM11 SCU and cannot
\t * snoop PL310. ACCESS_PLATFORM makes virtio_ring use dma_map_* for every
\t * block buffer and dma_alloc_coherent for the ring itself. */
\tif (!__virtio_test_bit(vdev, VIRTIO_F_ACCESS_PLATFORM)) {
\t\tdev_err(&vdev->dev, "ARM9 transport requires DMA API cache maintenance");
\t\treturn -EINVAL;
\t}
\tdev_info(&vdev->dev, "ARM9 transport using DMA API for PL310 coherency");
'''
    pxi = replace_once(pxi, old, new, "PXI DMA API requirement")
PXI.write_text(pxi)

print("patch_arm9_sd_recovery: bounded SD commands; recovery retry; truthful IOERR; DMA API required")
