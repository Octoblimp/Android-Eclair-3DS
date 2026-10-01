#!/usr/bin/env python3
"""Recover failed ARM9 multi-sector SD reads one sector at a time."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
SDCARD = ROOT / "third_party/arm9linuxfw/source/vdev/sdcard.c"


text = SDCARD.read_text()
if "N3DS_SD_SECTOR_READ_FALLBACK" not in text:
    old = """static int sdmc_transfer(bool write, u32 sector, u32 sectors, u8 *data)
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
"""
    new = """static int sdmc_transfer(bool write, u32 sector, u32 sectors, u8 *data)
{
	int ret;
	u32 i;

	ret = write ? sdmmc_sdcard_writesectors(sector, sectors, data) :
		      sdmmc_sdcard_readsectors(sector, sectors, data);
	if (!ret)
		return 0;

	if (!sdmmc_sdcard_recover()) {
		ret = write ? sdmmc_sdcard_writesectors(sector, sectors, data) :
			      sdmmc_sdcard_readsectors(sector, sectors, data);
		if (!ret)
			return 0;
	}

	/* N3DS_SD_SECTOR_READ_FALLBACK: hardware logs show repeatable 4 KiB
	 * virtio reads failing as a unit while the card remains responsive.  A
	 * failed read has no partial-write ambiguity, so retry each 512-byte
	 * sector independently and recover once around an individual failure.
	 * Writes stay all-or-error to preserve their existing semantics. */
	if (write || sectors <= 1)
		return -1;
	for (i = 0; i < sectors; i++) {
		ret = sdmmc_sdcard_readsectors(sector + i, 1, data + (i << 9));
		if (ret && !sdmmc_sdcard_recover())
			ret = sdmmc_sdcard_readsectors(sector + i, 1,
						     data + (i << 9));
		if (ret)
			return -1;
	}
	return 0;
}
"""
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"sdmc_transfer anchor: expected one match, found {count}")
    text = text.replace(old, new, 1)

SDCARD.write_text(text)
if SDCARD.read_text().count("N3DS_SD_SECTOR_READ_FALLBACK") != 1:
    raise SystemExit("sector fallback marker missing or duplicated")

print("patch_arm9_sd_read_fallback: bounded per-sector recovery after bulk read failure")
