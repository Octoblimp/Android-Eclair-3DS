from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

old_comment = """/* Phase 2 (WiFi bring-up, legacy AR6002 driver port): this driver
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
 */"""

new_comment = """/* Phase 2 (WiFi bring-up, legacy AR6002 driver port): this driver
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
 *   stub_data  (56 bytes)   -> target 0x524C00 (currently unused, see below)
 *   stub_code  (790 bytes)  -> target 0x527000 (currently unused, see below)
 *   database   (488 bytes)  -> target 0x53FE18
 *   main_type1 (6939 bytes) -> target 0x524C00
 *
 * The stub bootstrap (stub_data + stub_code, executed via BMIExecute at
 * 0x527000) was tried first on the theory that it reads real per-console
 * RF calibration off a physical EEPROM into the database region. It does
 * not work: BMIExecute's response wait (bmiBufferReceive with
 * want_timeout=false, see bmi.c) is a genuinely UNBOUNDED busy loop by
 * design (its own comment says so) that never returns unless the target
 * signals completion through RX_LOOKAHEAD_VALID. Two hardware tests
 * confirmed this hangs permanently -- zero output of any kind after the
 * BMIExecute call (not even a BMI error, which bmifn() would have
 * printed on a clean failure), while the SDIO interrupt count climbed
 * continuously across each test (7868 -> 7957 -> 21394), consistent with
 * bmiBufferReceive's internal loop hammering HIFReadWrite forever
 * waiting for a response that never comes. Most likely explanation:
 * Nintendo's stub code depends on NWM module runtime infrastructure
 * (RTOS/interrupts/timers) that doesn't exist when executed standalone
 * via a raw BMI Execute outside that environment, so it never reaches
 * the point where it signals back.
 *
 * Current approach: skip the stub entirely and write our own extracted
 * database.bin directly to 0x53FE18, instead of relying on the stub to
 * populate it from hardware at runtime.
 */"""

replace_once(old_comment, new_comment, "doc comment")

old_body = """    /* stub_data -> 0x524C00 */
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

    /* Phase 2 diagnostic: read back what the stub actually left behind,
     * so we can tell empirically whether it populated the database
     * region from real hardware (vs. leaving it untouched/zeroed),
     * without needing another full guess-and-reboot cycle.
     *
     * Kept deliberately stack-frugal (one 4-byte buffer, one word printed
     * at a time) after the first attempt (a 256-byte line buffer plus two
     * more arrays, ~300+ bytes total) produced neither its own output nor
     * a BMI error -- consistent with silently overrunning a limited
     * kernel-thread/workqueue stack rather than the read itself failing.
     */
    {
        u8 dbg_word[4];
        int dbg_i;

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: database[0x53FE18..+16] after stub exec:\\n"));
        for (dbg_i = 0; dbg_i < 16; dbg_i += 4) {
            bmifn(BMIReadMemory(ar->arHifDevice, 0x53FE18 + dbg_i, dbg_word, 4));
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("  +%02x: %02x %02x %02x %02x\\n",
                dbg_i, dbg_word[0], dbg_word[1], dbg_word[2], dbg_word[3]));
        }

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: 0x524C00[..+8] after stub exec (still stub_data?):\\n"));
        for (dbg_i = 0; dbg_i < 8; dbg_i += 4) {
            bmifn(BMIReadMemory(ar->arHifDevice, 0x524C00 + dbg_i, dbg_word, 4));
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("  +%02x: %02x %02x %02x %02x\\n",
                dbg_i, dbg_word[0], dbg_word[1], dbg_word[2], dbg_word[3]));
        }
    }

    /* main_type1 (basic internet firmware) -> 0x524C00, reusing the
     * address stub_data used -- safe now that the stub has run. */"""

new_body = """    /* database -> 0x53FE18, written directly (see doc comment above:
     * the stub-execution approach for populating this region hangs
     * forever, so we use our own extracted copy instead). */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing database.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/database.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/database.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x53FE18, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: database.bin written OK\\n"));

    /* main_type1 (basic internet firmware) -> 0x524C00 */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing main_type1.bin\\n"));"""

replace_once(old_body, new_body, "function body")

with open(path, 'w') as f:
    f.write(content)
print("OK")
