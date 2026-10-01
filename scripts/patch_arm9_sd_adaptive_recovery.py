#!/usr/bin/env python3
"""Add bounded slow-clock SD recovery and Linux-visible TMIO diagnostics."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
ARM9 = ROOT / "third_party/arm9linuxfw"
SDMMC = ARM9 / "source/hw/sdmmc.c"
SDMMC_H = ARM9 / "include/hw/sdmmc.h"
SDCARD = ARM9 / "source/vdev/sdcard.c"
PXI = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_pxi.c"
PXI_H = ROOT / "third_party/linux/drivers/platform/nintendo3ds/ctr_pxi.h"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


sdmmc = SDMMC.read_text()
if "N3DS_SD_ADAPTIVE_SLOW_CLOCK" not in sdmmc:
    sdmmc = replace_once(
        sdmmc,
        "struct mmcdevice handleNAND;\nstruct mmcdevice handleSD;\n",
        "struct mmcdevice handleNAND;\nstruct mmcdevice handleSD;\n\n"
        "/* N3DS_SD_ADAPTIVE_SLOW_CLOCK: stay at the normal 16.76 MHz until\n"
        " * a real runtime transfer fails, then use the next slower divider\n"
        " * for every recovery and transfer for the rest of this boot. */\n"
        "static bool sdmmc_sd_slow_mode;\n",
        "adaptive-clock state",
    )
    sdmmc = replace_once(
        sdmmc,
        "static void sdmmc_abort_command(struct mmcdevice *ctx)\n"
        "{\n"
        "\tctx->error |= 4;\n",
        "static void sdmmc_abort_command(struct mmcdevice *ctx)\n"
        "{\n"
        "\t/* Snapshot the cause before reset clears the only useful evidence. */\n"
        "\tctx->stat0 = sdmmc_read16(REG_SDSTATUS0);\n"
        "\tctx->stat1 = sdmmc_read16(REG_SDSTATUS1);\n"
        "\tctx->error |= 4;\n",
        "timeout status snapshot",
    )
    sdmmc = replace_once(
        sdmmc,
        "\thandleSD.clk |= 0x200;\n\n\treturn 0;\n}\n\n"
        "/* N3DS_SDMMC_RECOVERY_RETRY",
        "\tif (sdmmc_sd_slow_mode)\n"
        "\t\thandleSD.clk = 0x202; /* 8.38 MHz fallback */\n"
        "\telse\n"
        "\t\thandleSD.clk |= 0x200; /* 16.76 MHz normal */\n"
        "\tsetckl(handleSD.clk);\n\n"
        "\treturn 0;\n}\n\n"
        "/* N3DS_SDMMC_RECOVERY_RETRY",
        "final SD clock selection",
    )
    sdmmc = replace_once(
        sdmmc,
        "int sdmmc_sdcard_recover(void)\n"
        "{\n"
        "\tsdmmc_init();\n"
        "\treturn SD_Init();\n"
        "}\n",
        "int sdmmc_sdcard_recover(void)\n"
        "{\n"
        "\tsdmmc_init();\n"
        "\treturn SD_Init();\n"
        "}\n\n"
        "int sdmmc_sdcard_recover_slow(void)\n"
        "{\n"
        "\tsdmmc_sd_slow_mode = true;\n"
        "\tsdmmc_init();\n"
        "\treturn SD_Init();\n"
        "}\n\n"
        "bool sdmmc_sdcard_is_slow(void)\n"
        "{\n"
        "\treturn sdmmc_sd_slow_mode;\n"
        "}\n",
        "slow recovery helpers",
    )

if sdmmc.count("N3DS_SD_ADAPTIVE_SLOW_CLOCK") != 1:
    raise SystemExit("adaptive SD clock marker missing or duplicated")
SDMMC.write_text(sdmmc)


header = SDMMC_H.read_text()
if "sdmmc_sdcard_recover_slow" not in header:
    header = replace_once(
        header,
        "\tint sdmmc_sdcard_recover(void);\n",
        "\tint sdmmc_sdcard_recover(void);\n"
        "\tint sdmmc_sdcard_recover_slow(void);\n"
        "\tbool sdmmc_sdcard_is_slow(void);\n",
        "adaptive recovery declarations",
    )
SDMMC_H.write_text(header)


sdcard = SDCARD.read_text()
if "N3DS_SD_ADAPTIVE_RECOVERY" not in sdcard:
    sdcard = replace_once(
        sdcard,
        '#include "hw/sdmmc.h"\n',
        '#include "arm/arm.h"\n#include "hw/sdmmc.h"\n',
        "ARM barrier include",
    )
    sdcard = replace_once(
        sdcard,
        "\tu32 max_discard_sectors;\n"
        "\tu32 max_discard_seg;\n"
        "\tu32 discard_sector_alignment;\n"
        "\tu32 max_write_zeroes_sectors;\n"
        "\tu32 max_write_zeroes_seg;\n"
        "\tu8 write_zeroes_may_unmap;\n"
        "\tu8 unused1[3];\n",
        "\t/* N3DS_SD_DIAG_CONFIG: discard/write-zeroes are not advertised.\n"
        "\t * Reuse their otherwise unread config bytes for one atomic-ish\n"
        "\t * recovery snapshot consumed only by the 3DS PXI transport. */\n"
        "\tstruct n3ds_sd_diag {\n"
        "\t\tu32 seq;\n"
        "\t\tu32 sector;\n"
        "\t\tu32 first_tmio;\n"
        "\t\tu32 last_tmio;\n"
        "\t\tu32 meta;\n"
        "\t\tu32 counts;\n"
        "\t} diag;\n",
        "diagnostic config window",
    )
    sdcard = replace_once(
        sdcard,
        "static blk_config sdmc_blk_config;\n",
        "static blk_config sdmc_blk_config;\n"
        "static u32 sdmc_failure_count;\n"
        "static u32 sdmc_recovery_count;\n\n"
        "enum n3ds_sd_diag_phase {\n"
        "\tN3DS_SD_DIAG_WRITE_RECOVERED = 1,\n"
        "\tN3DS_SD_DIAG_SLOW_READ_RECOVERED = 2,\n"
        "\tN3DS_SD_DIAG_SECTOR_READ_RECOVERED = 3,\n"
        "\tN3DS_SD_DIAG_FINAL_IOERR = 4,\n"
        "};\n",
        "diagnostic state",
    )

    start = sdcard.index("static int sdmc_transfer(")
    end = sdcard.index("\n/* N3DS_SD_ONE_REQUEST_PER_PASS", start)
    transfer = r'''/* N3DS_SD_ADAPTIVE_RECOVERY: preserve the normal fast path, but after
 * the first actual TMIO failure keep the card at half rate for this boot.
 * Every retry is bounded. Writes retain one whole-request retry; reads gain
 * one final single-sector retry or the existing per-sector fallback.
 * N3DS_SD_SECTOR_READ_FALLBACK remains the multi-sector recovery contract. */
static u32 sdmc_tmio_status(void)
{
	mmcdevice *sd = getMMCDevice(1);
	return ((u32)sd->stat1 << 16) | sd->stat0;
}

static void sdmc_record_diag(u32 sector, u32 sectors, u32 attempts,
			     u32 first_tmio, u32 last_tmio,
			     enum n3ds_sd_diag_phase phase, int recovery_ret)
{
	struct n3ds_sd_diag *diag = &sdmc_blk_config.diag;
	u32 seq = diag->seq + 1;
	u32 bounded_sectors = sectors > 0xff ? 0xff : sectors;
	u32 bounded_attempts = attempts > 0xff ? 0xff : attempts;
	u32 failures = sdmc_failure_count > 0xffff ? 0xffff : sdmc_failure_count;
	u32 recoveries = sdmc_recovery_count > 0xffff ? 0xffff : sdmc_recovery_count;

	diag->sector = sector;
	diag->first_tmio = first_tmio;
	diag->last_tmio = last_tmio;
	diag->meta = bounded_sectors | (bounded_attempts << 8) |
		((u32)phase << 16) | ((u32)(u8)recovery_ret << 24);
	diag->counts = failures | (recoveries << 16);
	arm_sync_barrier();
	diag->seq = seq;
	arm_sync_barrier();
}

static int sdmc_recover_slow(void)
{
	sdmc_recovery_count++;
	return sdmmc_sdcard_recover_slow();
}

static int sdmc_transfer(bool write, u32 sector, u32 sectors, u8 *data)
{
	int ret, recovery_ret;
	u32 i, attempts = 1;
	u32 first_tmio, last_tmio;

	ret = write ? sdmmc_sdcard_writesectors(sector, sectors, data) :
		      sdmmc_sdcard_readsectors(sector, sectors, data);
	if (!ret)
		return 0;

	sdmc_failure_count++;
	first_tmio = last_tmio = sdmc_tmio_status();
	recovery_ret = sdmc_recover_slow();
	if (!recovery_ret) {
		attempts++;
		ret = write ? sdmmc_sdcard_writesectors(sector, sectors, data) :
			      sdmmc_sdcard_readsectors(sector, sectors, data);
		if (!ret) {
			sdmc_record_diag(sector, sectors, attempts, first_tmio,
					 sdmc_tmio_status(),
					 write ? N3DS_SD_DIAG_WRITE_RECOVERED :
					 N3DS_SD_DIAG_SLOW_READ_RECOVERED, 0);
			return 0;
		}
		sdmc_failure_count++;
		last_tmio = sdmc_tmio_status();
	} else {
		last_tmio = sdmc_tmio_status();
	}

	/* Writes keep their pre-existing one-recovery all-or-error contract. */
	if (write) {
		sdmc_record_diag(sector, sectors, attempts, first_tmio, last_tmio,
				 N3DS_SD_DIAG_FINAL_IOERR, recovery_ret);
		return -1;
	}

	/* A one-sector Linux read gets one extra slow recovery/attempt. */
	if (sectors <= 1) {
		recovery_ret = sdmc_recover_slow();
		if (!recovery_ret) {
			attempts++;
			ret = sdmmc_sdcard_readsectors(sector, 1, data);
			if (!ret) {
				sdmc_record_diag(sector, 1, attempts, first_tmio,
						 sdmc_tmio_status(),
						 N3DS_SD_DIAG_SLOW_READ_RECOVERED, 0);
				return 0;
			}
			sdmc_failure_count++;
			last_tmio = sdmc_tmio_status();
		} else {
			last_tmio = sdmc_tmio_status();
		}
		sdmc_record_diag(sector, 1, attempts, first_tmio, last_tmio,
				 N3DS_SD_DIAG_FINAL_IOERR, recovery_ret);
		return -1;
	}

	/* A failed multi-sector command may have left TMIO mid-transfer. Reset
	 * once before decomposing it; retry each failed sector only once. */
	recovery_ret = sdmc_recover_slow();
	if (recovery_ret) {
		sdmc_record_diag(sector, sectors, attempts, first_tmio,
				 sdmc_tmio_status(), N3DS_SD_DIAG_FINAL_IOERR,
				 recovery_ret);
		return -1;
	}

	for (i = 0; i < sectors; i++) {
		attempts++;
		ret = sdmmc_sdcard_readsectors(sector + i, 1, data + (i << 9));
		if (ret) {
			sdmc_failure_count++;
			last_tmio = sdmc_tmio_status();
			recovery_ret = sdmc_recover_slow();
			if (!recovery_ret) {
				attempts++;
				ret = sdmmc_sdcard_readsectors(sector + i, 1,
							     data + (i << 9));
			}
			if (ret) {
				if (!recovery_ret) {
					sdmc_failure_count++;
					last_tmio = sdmc_tmio_status();
				}
				sdmc_record_diag(sector + i, 1, attempts,
						 first_tmio, last_tmio,
						 N3DS_SD_DIAG_FINAL_IOERR,
						 recovery_ret);
				return -1;
			}
		}
	}

	sdmc_record_diag(sector, sectors, attempts, first_tmio,
			 sdmc_tmio_status(), N3DS_SD_DIAG_SECTOR_READ_RECOVERED, 0);
	return 0;
}
'''
    sdcard = sdcard[:start] + transfer + sdcard[end:]
    sdcard = replace_once(
        sdcard,
        "\tvjob_s vjob;\n\tbool processed = false;\n",
        "\tvjob_s vjob;\n"
        "\tbool processed = false;\n"
        "\tu32 diag_before = sdmc_blk_config.diag.seq;\n",
        "diagnostic sequence snapshot",
    )
    sdcard = replace_once(
        sdcard,
        "\tvman_notify_host(vdev, VIRQ_VQUEUE);\n}\n",
        "\tvman_notify_host(vdev, VIRQ_VQUEUE);\n"
        "\tif (sdmc_blk_config.diag.seq != diag_before)\n"
        "\t\tvman_notify_host(vdev, VIRQ_CONFIG);\n"
        "}\n",
        "diagnostic config interrupt",
    )

for marker in (
    "N3DS_SD_ADAPTIVE_RECOVERY",
    "N3DS_SD_DIAG_CONFIG",
    "vman_notify_host(vdev, VIRQ_CONFIG)",
):
    if marker not in sdcard:
        raise SystemExit(f"ARM9 block marker missing: {marker}")
if "N3DS_SD_SECTOR_READ_FALLBACK" not in sdcard:
    old = " * one final single-sector retry or the existing per-sector fallback. */"
    new = (" * one final single-sector retry or the existing per-sector fallback.\n"
           " * N3DS_SD_SECTOR_READ_FALLBACK remains the multi-sector recovery contract. */")
    if sdcard.count(old) != 1:
        raise SystemExit("sector-fallback compatibility marker anchor missing")
    sdcard = sdcard.replace(old, new, 1)
SDCARD.write_text(sdcard)


pxi_h = PXI_H.read_text()
if "n3ds_sd_diag_seq" not in pxi_h:
    pxi_h = replace_once(
        pxi_h,
        "\tstruct list_head vqs;\n\tstruct virtio_device vdev;\n",
        "\tstruct list_head vqs;\n"
        "\tu32 n3ds_sd_diag_seq;\n"
        "\tstruct virtio_device vdev;\n",
        "Linux diagnostic sequence state",
    )
PXI_H.write_text(pxi_h)


pxi = PXI.read_text()
if "N3DS_SD_RECOVERY_TELEMETRY" not in pxi:
    pxi = replace_once(
        pxi,
        "#include <linux/virtio.h>\n",
        "#include <linux/virtio.h>\n#include <linux/virtio_ids.h>\n",
        "virtio device IDs include",
    )
    anchor = "static void vpxi_irq_worker(struct work_struct *work)\n"
    helper = r'''/* N3DS_SD_RECOVERY_TELEMETRY: block config bytes 36..59 are unused
 * because this transport advertises neither discard nor write-zeroes. ARM9
 * raises a config IRQ only when this snapshot changes. Read seq twice so a
 * second recovery cannot produce a torn diagnostic line. */
#define N3DS_SD_DIAG_CONFIG_OFFSET	36

struct n3ds_sd_diag {
	u32 seq;
	u32 sector;
	u32 first_tmio;
	u32 last_tmio;
	u32 meta;
	u32 counts;
};

static void vpxi_read_sd_diag(struct virtio_pxi_dev *vpd)
{
	struct n3ds_sd_diag diag;
	u32 seq_after;
	int retry;

	for (retry = 0; retry < 2; retry++) {
		vpxi_get_config(&vpd->vdev, N3DS_SD_DIAG_CONFIG_OFFSET,
				&diag.seq, sizeof(diag.seq));
		if (!diag.seq || diag.seq == vpd->n3ds_sd_diag_seq)
			return;
		vpxi_get_config(&vpd->vdev, N3DS_SD_DIAG_CONFIG_OFFSET + 4,
				&diag.sector, sizeof(diag.sector));
		vpxi_get_config(&vpd->vdev, N3DS_SD_DIAG_CONFIG_OFFSET + 8,
				&diag.first_tmio, sizeof(diag.first_tmio));
		vpxi_get_config(&vpd->vdev, N3DS_SD_DIAG_CONFIG_OFFSET + 12,
				&diag.last_tmio, sizeof(diag.last_tmio));
		vpxi_get_config(&vpd->vdev, N3DS_SD_DIAG_CONFIG_OFFSET + 16,
				&diag.meta, sizeof(diag.meta));
		vpxi_get_config(&vpd->vdev, N3DS_SD_DIAG_CONFIG_OFFSET + 20,
				&diag.counts, sizeof(diag.counts));
		vpxi_get_config(&vpd->vdev, N3DS_SD_DIAG_CONFIG_OFFSET,
				&seq_after, sizeof(seq_after));
		if (seq_after == diag.seq)
			break;
	}

	if (seq_after != diag.seq)
		return;
	vpd->n3ds_sd_diag_seq = diag.seq;
	dev_warn(&vpd->vdev.dev,
		 "N3DS_SD_RECOVERY seq=%u sector=%u sectors=%u attempts=%u phase=%u recovery=%d first_tmio=%08x last_tmio=%08x failures=%u recoveries=%u",
		 diag.seq, diag.sector, diag.meta & 0xff,
		 (diag.meta >> 8) & 0xff, (diag.meta >> 16) & 0xff,
		 (s8)(diag.meta >> 24), diag.first_tmio, diag.last_tmio,
		 diag.counts & 0xffff, diag.counts >> 16);
}

'''
    pxi = replace_once(pxi, anchor, helper + anchor, "Linux SD diagnostic helper")
    pxi = replace_once(
        pxi,
        "\t\t\tif (pending_mask & BIT_ULL(cirq)) {\n"
        "\t\t\t\tvirtio_config_changed(&vpd->vdev);\n"
        "\t\t\t}\n",
        "\t\t\tif (pending_mask & BIT_ULL(cirq)) {\n"
        "\t\t\t\tif (vpd->vdev.id.device == VIRTIO_ID_BLOCK)\n"
        "\t\t\t\t\tvpxi_read_sd_diag(vpd);\n"
        "\t\t\t\telse\n"
        "\t\t\t\t\tvirtio_config_changed(&vpd->vdev);\n"
        "\t\t\t}\n",
        "config IRQ diagnostic dispatch",
    )

if pxi.count("N3DS_SD_RECOVERY_TELEMETRY") != 1:
    raise SystemExit("Linux SD telemetry marker missing or duplicated")
PXI.write_text(pxi)

print("patch_arm9_sd_adaptive_recovery: slow fallback + TMIO telemetry applied")
