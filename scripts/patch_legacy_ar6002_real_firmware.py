from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

old_function_marker_start = "static int\nar6000_ar6002_boot_firmware(struct ar6_softc *ar)\n{"
assert content.count(old_function_marker_start) == 1, "can't find existing function to replace"

# Find the full old function body to replace (from the marker through its
# closing "return 0;\n}\n" before the next function/comment block begins).
start_idx = content.index(old_function_marker_start)
# The function's doc comment precedes it; find that comment's start instead,
# so we replace comment + function together.
comment_marker = "/* Phase 2 (WiFi bring-up, legacy AR6002 driver port): this driver"
comment_start = content.index(comment_marker)
assert comment_start < start_idx

# The function ends at the first "return 0;\n}\n\n" after start_idx.
end_marker = "    return 0;\n}\n\n"
end_idx = content.index(end_marker, start_idx) + len(end_marker)

new_function = '''/* Phase 2 (WiFi bring-up, legacy AR6002 driver port): this driver
 * snapshot's board-data/firmware download path (ar6000_transfer_bin_file
 * and everything below) was only ever wired up for AR6003, which uses
 * BMI-queried dynamic target addresses via HOST_INTEREST_ITEM_ADDRESS.
 * AR6002 uses a different, simpler fixed-address loading sequence with
 * no filename macros defined anywhere in this codebase.
 *
 * These addresses and this block structure are NOT reverse-engineered
 * guesses -- they come directly from Nintendo's own compiled ARM11 NWM
 * (WiFi system module) code, extracted from the console's own NAND
 * (title 0004013000002D02) and located via the documented literal-pool
 * discovery method (search for constant 0x00524C00, verify 0x000003ED
 * at the expected adjacent offset, then read the surrounding pool
 * entries -- see GBATEK's "3DS Files - Module NWM" page). Every
 * extracted block's size matches GBATEK's documented sizes exactly:
 *   stub_data  (56 bytes)   -> target 0x524C00
 *   stub_code  (790 bytes)  -> target 0x527000
 *   database   (488 bytes)  -> target 0x53FE18
 *   main_type1 (6939 bytes) -> target 0x524C00 (same as stub_data --
 *                              loaded after the stub has finished with
 *                              that region; "type1" = basic internet
 *                              access, the variant we want, out of the
 *                              type1/type4/type5 alternatives Nintendo's
 *                              code supports)
 *
 * What's still a real inference rather than confirmed fact: the load
 * ORDER and whether/where each block needs a BMI Execute step. Best
 * available reasoning: stub_data + stub_code look like a bootstrap that
 * reads real per-console RF calibration off a physical EEPROM chip on
 * the WiFi module into the database region, so the stub is executed
 * before loading the main firmware -- this does NOT write our extracted
 * database.bin at all, on the theory that the stub populates it from
 * real hardware at runtime and our copy is likely just a zero/template
 * placeholder that would be overwritten (or worse, interfered with)
 * anyway. If this doesn't work, writing database.bin explicitly before
 * running the stub is the next thing to try.
 */
static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    u32 param;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;

    /* stub_data -> 0x524C00 */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/stub_data.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/stub_data.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x524C00, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    /* stub_code -> 0x527000 */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/stub_code.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/stub_code.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x527000, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    /* Run the EEPROM-reading stub at its own load address, so it can
     * populate the database region (0x53FE18) from real hardware. */
    param = 0;
    bmifn(BMIExecute(ar->arHifDevice, 0x527000, &param));

    /* main_type1 (basic internet firmware) -> 0x524C00, reusing the
     * address stub_data used -- safe now that the stub has run. */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/main_type1.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/main_type1.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x524C00, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));

    return 0;
}

'''

content = content[:comment_start] + new_function + content[end_idx:]

with open(path, 'w') as f:
    f.write(content)
print("OK")
