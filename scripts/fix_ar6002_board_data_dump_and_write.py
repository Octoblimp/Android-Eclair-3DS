"""Phase 2 / AR6002: dump hi_board_data's target, write eeprom.bin there, dump again.

Last boot (with the corrected host-interest base) showed hi_board_data
(pre-load) = 0x00520e00 -- a real pointer the boot ROM set up on its own,
never written by us. We deliberately never populate real calibration data
(see the comment above ar6000_ar6002_boot_firmware: "Note this blob is NOT
board/EEPROM calibration data ... hi_board_data and
hi_board_data_initialized are deliberately left alone"). If the ROM expects
real board data at that address and never gets it, that's a plausible cause
of the assert we keep hitting.

ath6k/AR6002/eeprom.bin (784 bytes, vs. AR6002_BOARD_DATA_SZ == 768) is the
best candidate on disk -- it's the generic-reference-design board data file
that ships alongside the AR6002 WLAN firmware, as opposed to the nwm/*
files which are Nintendo's DataSet patch mechanism.

ar6000_transfer_bin_file()'s AR6K_BOARD_DATA_FILE case is AR6003-only (it
switches on arVersion.target_ver against AR6003_REV1/2/3 and errors out
otherwise), so this can't reuse that path -- write directly via BMI, same
pattern already used for database.bin/main_type1.bin below.

One BMI pass this time: dump target memory at hi_board_data before
touching it, write eeprom.bin, dump again to confirm the write landed, and
then let the existing boot sequence run to completion so the log shows
whether this was enough by itself.
"""
from a3ds_paths import A3DS_ROOT

drv = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

with open(drv) as f:
    c = f.read()


def replace_once(old, new, label):
    global c
    n = c.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    c = c.replace(old, new)


old_anchor = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

new_anchor = """/* hi_board_data (pre-load) has read a real ROM-set pointer
 * (0x00520e00 observed) on every boot since the host-interest base was
 * corrected, yet we never write anything there -- the DataSet patch
 * (database.bin) was established to not be board/EEPROM data. Try the
 * obvious candidate: ath6k/AR6002/eeprom.bin, the generic reference-design
 * board data file that ships next to the real AR6002 WLAN firmware. Dumps
 * before and after so the write is verified independent of what happens
 * afterward. */
static void
ar6002_probe_and_write_board_data(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;
    u32 board_addr = 0;
    u32 param;
    u32 write_len;

    if (BMIReadMemory(ar->arHifDevice,
                      HOST_INTEREST_ITEM_ADDRESS(ar, hi_board_data),
                      (u8 *)&board_addr, 4) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 BOARD-DATA: failed to read hi_board_data\\n"));
        return;
    }

    if (board_addr == 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 BOARD-DATA: hi_board_data is 0, target allocated no"
             " space for board data -- skipping\\n"));
        return;
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 BOARD-DATA: hi_board_data = 0x%08x\\n", board_addr));
    ar6002_dump_target_region(ar, "pre-board-data", board_addr, AR6002_BOARD_DATA_SZ);

    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/eeprom.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 BOARD-DATA: failed to get ath6k/AR6002/eeprom.bin,"
             " skipping\\n"));
        return;
    }

    write_len = fw_entry->size;
    if (write_len > AR6002_BOARD_DATA_SZ) {
        write_len = AR6002_BOARD_DATA_SZ;
    }
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 BOARD-DATA: writing %u of %zu bytes from eeprom.bin to 0x%08x\\n",
         write_len, fw_entry->size, board_addr));

    if (BMIWriteMemory(ar->arHifDevice, board_addr, (u8 *)fw_entry->data, write_len) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 BOARD-DATA: write FAILED\\n"));
        A_RELEASE_FIRMWARE(fw_entry);
        return;
    }
    A_RELEASE_FIRMWARE(fw_entry);

    param = 1;
    bmifn(BMIWriteMemory(ar->arHifDevice,
                         HOST_INTEREST_ITEM_ADDRESS(ar, hi_board_data_initialized),
                         (u8 *)&param, 4));

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 BOARD-DATA: write OK, hi_board_data_initialized set\\n"));
    ar6002_dump_target_region(ar, "post-board-data", board_addr, AR6002_BOARD_DATA_SZ);
}

static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

replace_once(old_anchor, new_anchor, "add board-data probe/write function")

replace_once(
    """    ar6002_dump_host_interest(ar, "pre-load");
    ar6002_probe_writable(ar);
    ar6002_probe_diag_writable(ar);
""",
    """    ar6002_dump_host_interest(ar, "pre-load");
    ar6002_probe_writable(ar);
    ar6002_probe_diag_writable(ar);
    ar6002_probe_and_write_board_data(ar);
""",
    "call board-data probe/write before firmware load",
)

with open(drv, "w") as f:
    f.write(c)
print("OK")
