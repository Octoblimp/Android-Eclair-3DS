from a3ds_paths import A3DS_ROOT
import re

path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

# 1. Insert the new AR6002 firmware-boot function right before
# ar6000_sysfs_bmi_get_config, which is where it gets called from.
new_function = '''/* Phase 2 (WiFi bring-up, legacy AR6002 driver port): this driver
 * snapshot's board-data/firmware download path (ar6000_transfer_bin_file
 * and everything below) was only ever wired up for AR6003, which uses
 * BMI-queried dynamic target addresses via HOST_INTEREST_ITEM_ADDRESS.
 * AR6002 uses a different, simpler fixed-address loading sequence with
 * no filename macros defined anywhere in this codebase (confirmed
 * against an earlier, more complete SDK snapshot too -- AR6002 support
 * was apparently dropped from this file-transfer mechanism at some
 * point upstream, though other AR6002 register-level code paths
 * elsewhere in this file remain intact).
 *
 * The addresses and load order below are NOT from source we have
 * access to -- they come from an independent empirical trace of a real
 * AR6002-based device's BMI boot log (the Parrot AR.Drone, which used
 * this same chip for its WiFi):
 *   https://coverclock.blogspot.com/2011/04/deconstructing-ardrone-part-4.html
 * Treat this as a best-effort reverse-engineered reconstruction, not a
 * vendor-documented sequence -- it's untested until real hardware
 * proves otherwise.
 *
 * Expects eeprom.data, eeprom.bin, athwlan.bin.z77, and
 * data.patch.hw2_0.bin under /lib/firmware/ath6k/AR6002/ (the standard
 * linux-firmware layout for this chip).
 */
static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    u32 param;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;

    /* Step 1: eeprom.data -> 0x502070 */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/eeprom.data", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get eeprom.data\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x502070, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    /* Step 2: eeprom.bin -> 0x513950 */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/eeprom.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get eeprom.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x513950, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    /* Step 3: execute whatever bootstrap code eeprom.bin just loaded */
    param = 0;
    bmifn(BMIExecute(ar->arHifDevice, 0x913950, &param));

    /* Step 4 */
    bmifn(BMISetAppStart(ar->arHifDevice, 0x913950));

    /* Step 5: main WLAN firmware (compressed) -> 0x502070 (same address
     * as eeprom.data -- already consumed by the execute step above) */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/athwlan.bin.z77", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get athwlan.bin.z77\\n"));
        return A_ERROR;
    }
    bmifn(BMIFastDownload(ar->arHifDevice, 0x502070, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    /* Step 6: patch data -> 0x52d6c8 */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/data.patch.hw2_0.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get data.patch.hw2_0.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x52d6c8, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    /* Step 7: point the firmware at the patch data */
    param = 0x52d6c8;
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x500418, (u8 *)&param, 4));

    /* Step 8: enable the patch (observed as orig 0xa -> new 0xb, i.e. an
     * OR with mask 0x1 -- translated as read-modify-write since this
     * driver has no dedicated bitwise-modify BMI primitive, only plain
     * read/write) */
    bmifn(BMIReadSOCRegister(ar->arHifDevice, 0x500410, &param));
    param |= 0x1;
    bmifn(BMIWriteSOCRegister(ar->arHifDevice, 0x500410, param));

    /* Step 9: done */
    return 0;
}

'''

replace_once(
    "ar6000_sysfs_bmi_get_config(struct ar6_softc *ar, u32 mode)\n{",
    new_function + "ar6000_sysfs_bmi_get_config(struct ar6_softc *ar, u32 mode)\n{",
    "insert ar6000_ar6002_boot_firmware before caller",
)

# 2. Branch the board-data step 3 ways (AR6002 / AR6003 / unsupported),
# and gate the subsequent unconditional-AR6003 firmware+app-start+patch
# block so it only runs for AR6003 (AR6002's entire firmware sequence
# already happened inside ar6000_ar6002_boot_firmware()).
old_block = '''        } else {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("Programming of board data for chip %d not supported\\n", ar->arTargetType));
            return A_ERROR;
        }

        /* Download Target firmware */
        AR6K_APP_LOAD_ADDRESS(address, ar->arVersion.target_ver);
        if (ar->arVersion.target_ver == AR6003_REV3_VERSION)
                address = 0x1234;
        if ((ar6000_transfer_bin_file(ar, AR6K_FIRMWARE_FILE, address, true)) != 0) {
            return A_ERROR;
        }

        /* Set starting address for firmware */
        AR6K_APP_START_OVERRIDE_ADDRESS(address, ar->arVersion.target_ver);
        bmifn(BMISetAppStart(ar->arHifDevice, address));

	if(ar->arTargetType == TARGET_TYPE_AR6003) {
		AR6K_DATASET_PATCH_ADDRESS(address, ar->arVersion.target_ver);
		if ((ar6000_transfer_bin_file(ar, AR6K_PATCH_FILE,
					      address, false)) != 0)
			return A_ERROR;
		param = address;
		bmifn(BMIWriteMemory(ar->arHifDevice,
		HOST_INTEREST_ITEM_ADDRESS(ar, hi_dset_list_head),
					   (unsigned char *)&param, 4));
	}

        /* Restore system sleep */'''

new_block = '''        } else if (ar->arTargetType == TARGET_TYPE_AR6002) {
            if (ar6000_ar6002_boot_firmware(ar) != 0) {
                return A_ERROR;
            }
        } else {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("Programming of board data for chip %d not supported\\n", ar->arTargetType));
            return A_ERROR;
        }

        if (ar->arTargetType == TARGET_TYPE_AR6003) {
        /* Download Target firmware */
        AR6K_APP_LOAD_ADDRESS(address, ar->arVersion.target_ver);
        if (ar->arVersion.target_ver == AR6003_REV3_VERSION)
                address = 0x1234;
        if ((ar6000_transfer_bin_file(ar, AR6K_FIRMWARE_FILE, address, true)) != 0) {
            return A_ERROR;
        }

        /* Set starting address for firmware */
        AR6K_APP_START_OVERRIDE_ADDRESS(address, ar->arVersion.target_ver);
        bmifn(BMISetAppStart(ar->arHifDevice, address));

		AR6K_DATASET_PATCH_ADDRESS(address, ar->arVersion.target_ver);
		if ((ar6000_transfer_bin_file(ar, AR6K_PATCH_FILE,
					      address, false)) != 0)
			return A_ERROR;
		param = address;
		bmifn(BMIWriteMemory(ar->arHifDevice,
		HOST_INTEREST_ITEM_ADDRESS(ar, hi_dset_list_head),
					   (unsigned char *)&param, 4));
        }

        /* Restore system sleep */'''

replace_once(old_block, new_block, "board-data 3-way branch + gate AR6003 firmware block")

with open(path, 'w') as f:
    f.write(content)
print("OK")
