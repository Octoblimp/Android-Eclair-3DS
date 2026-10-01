"""Phase 2 / AR6002: run the real WLAN firmware instead of the 6.9KB DataSet stub.

The last two boots (garbage board data, then real eeprom.bin board data)
produced byte-identical register dumps at the assert -- 59 of 60 registers
matched exactly, the one difference was a single hex nibble consistent
with stack noise. That means the crash point is fully deterministic and
independent of board data content, so board data was never the cause.

The remaining suspect is main_type1.bin itself: 6,939 bytes, loaded at
0x524C00 and handed directly to BMISetAppStart as the entire application.
The real AR6002 WLAN firmware, athwlan.bin.z77, sits right next to it in
the same firmware tree at ~98KB compressed -- consistent with what a
genuine AR6002 firmware image should be, and orders of magnitude larger
than a 6.9KB blob could plausibly be.

athwlan.bin.z77's own naming/extension matches the AR6003 branch's own
firmware files exactly (AR6003_REV1/2_FIRMWARE_FILE are also
"athwlan.bin.z77", downloaded via BMIFastDownload -- BMI's target-side
LZ decompression opcode, not a plain memory write). This confirms the
convention: main_type1.bin/database.bin are DataSet patches (small,
uncompressed, loaded via plain BMIWriteMemory) meant to be layered on top
of the real firmware, not to replace it.

New ordering matches the AR6003 branch's own sequence (see the
TARGET_TYPE_AR6003 arm above this function): firmware download -> compressed via
BMIFastDownload -> BMISetAppStart -> patch download -> hi_dset_list_head
write. Previously BMISetAppStart ran last; now it runs right after the
firmware it starts, and the patch is layered in afterward exactly as
AR6003 does for its own patch file.
"""
from a3ds_paths import A3DS_ROOT

drv = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

with open(drv) as f:
    c = f.read()

old = """    ar6002_dump_host_interest(ar, "pre-load");
    ar6002_probe_writable(ar);
    ar6002_probe_diag_writable(ar);
    ar6002_probe_and_write_board_data(ar);

    /* database -> 0x53FE18, written directly (see doc comment above:
     * running the stub -- even fire-and-forget -- wedges the target's
     * BMI communication layer, so we use our own extracted copy instead
     * of relying on the stub to populate it from hardware). */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing database.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/database.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/database.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x53FE18, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: database.bin written OK\\n"));

    /* main_type1 (basic internet firmware) -> 0x524C00 */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing main_type1.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/main_type1.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/main_type1.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x524C00, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: main_type1.bin written OK\\n"));

    /* Point the target's DataSet patch mechanism at the descriptor list we
     * just wrote to 0x53FE18. The AR6003 branch above does exactly this
     * for its own patch file (download to a fixed address near the top of
     * RAM, then hi_dset_list_head = that address); the AR6002 branch never
     * did, so the target ran its ROM unpatched. */
    param = 0x53FE18;
    bmifn(BMIWriteMemory(ar->arHifDevice,
                         HOST_INTEREST_ITEM_ADDRESS(ar, hi_dset_list_head),
                         (u8 *)&param, 4));
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: hi_dset_list_head set to 0x53FE18\\n"));

    ar6002_dump_host_interest(ar, "post-load");

    /* Locate the ROM's own host_interest_s before committing to a value.
     * RAM is 0x520000..0x540000 on the evidence so far; if 0x540000 also
     * turned out writable the map is bigger than the dataset-patch address
     * implies, so cover the AR6003-shaped range too. */
    ar6002_locate_host_interest(ar, 0x00520000, 0x00540000);
    if (ar6002_ram_past_540000) {
        ar6002_locate_host_interest(ar, 0x00540000, 0x00580000);
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: calling BMISetAppStart\\n"));
    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: BMISetAppStart returned OK\\n"));

    /* Dumped after SetAppStart this time -- the previous "post-load" dump ran
     * before it, so hi_app_start reading 0 there proved nothing. */
    ar6002_dump_host_interest(ar, "post-appstart");

    return 0;
}"""

assert old in c, "expected function body not found verbatim"

new = """    ar6002_dump_host_interest(ar, "pre-load");
    ar6002_probe_writable(ar);
    ar6002_probe_diag_writable(ar);
    ar6002_probe_and_write_board_data(ar);

    /* Real WLAN firmware -> 0x524C00, compressed (BMIFastDownload does
     * target-side LZ decompression -- same mechanism and same .z77
     * extension convention as AR6003_REV1/2_FIRMWARE_FILE above). The
     * previous main_type1.bin (6,939 bytes) was a DataSet patch payload,
     * not firmware -- it was never meant to run standalone as the entire
     * application, which is what BMISetAppStart was doing with it. */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing athwlan.bin.z77\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/athwlan.bin.z77", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get athwlan.bin.z77\\n"));
        return A_ERROR;
    }
    bmifn(BMIFastDownload(ar->arHifDevice, 0x524C00, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: athwlan.bin.z77 written OK (%zu bytes)\\n", fw_entry->size));

    /* Order matches the AR6003 branch above: SetAppStart runs right after
     * the firmware it starts, before the DataSet patch is layered in. */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: calling BMISetAppStart\\n"));
    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: BMISetAppStart returned OK\\n"));

    /* database -> 0x53FE18, written directly (see doc comment above:
     * running the stub -- even fire-and-forget -- wedges the target's
     * BMI communication layer, so we use our own extracted copy instead
     * of relying on the stub to populate it from hardware). */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing database.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/database.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/database.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x53FE18, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: database.bin written OK\\n"));

    /* Point the target's DataSet patch mechanism at the descriptor list we
     * just wrote to 0x53FE18. The AR6003 branch above does exactly this
     * for its own patch file (download to a fixed address near the top of
     * RAM, then hi_dset_list_head = that address); the AR6002 branch never
     * did, so the target ran its ROM unpatched. */
    param = 0x53FE18;
    bmifn(BMIWriteMemory(ar->arHifDevice,
                         HOST_INTEREST_ITEM_ADDRESS(ar, hi_dset_list_head),
                         (u8 *)&param, 4));
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: hi_dset_list_head set to 0x53FE18\\n"));

    /* SetAppStart already ran above, so hi_app_start reads back correctly
     * here -- no need for a separate post-appstart dump anymore. */
    ar6002_dump_host_interest(ar, "post-load");

    /* Locate the ROM's own host_interest_s before committing to a value.
     * RAM is 0x520000..0x540000 on the evidence so far; if 0x540000 also
     * turned out writable the map is bigger than the dataset-patch address
     * implies, so cover the AR6003-shaped range too. */
    ar6002_locate_host_interest(ar, 0x00520000, 0x00540000);
    if (ar6002_ram_past_540000) {
        ar6002_locate_host_interest(ar, 0x00540000, 0x00580000);
    }

    return 0;
}"""

c = c.replace(old, new)

with open(drv, "w") as f:
    f.write(c)
print("OK")
