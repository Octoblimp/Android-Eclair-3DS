from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

old_comment_tail = """ * Current approach: skip the stub entirely and write our own extracted
 * database.bin directly to 0x53FE18, instead of relying on the stub to
 * populate it from hardware at runtime.
 */"""

new_comment_tail = """ * Current approach: trigger the stub via BMIExecuteNoWait (sends the
 * BMI_EXECUTE command, which is what makes the target actually jump to
 * and run the code, but does not wait for/read a response that may
 * never come), delay a fixed amount, then read back and log the
 * database region to see empirically whether the stub wrote real
 * calibration data. We still overwrite that region with our own
 * extracted database.bin afterward regardless (known to at least get
 * the target running far enough to report "Got WMI" and start the HTC
 * handshake, even though it then asserts ~2s later -- see
 * ar6000_target_failure/DevPollMboxMsgRecv timeout in ar6k_events.c and
 * the "AR6K: Register Dump" it produces on a real device. That crash,
 * roughly 2s after BMISetAppStart, before the target ever sends its HTC
 * ready message, is the leading suspect for why: firmware likely
 * expects genuine per-console RF calibration -- normally supplied by
 * the stub reading the physical EEPROM -- and our static extracted
 * database.bin, pulled from Nintendo's binary as a template, may be
 * insufficient/invalid, causing an internal assert partway through
 * firmware init). This diagnostic read-back tells us whether the stub
 * is actually doing useful work we could switch to trusting instead.
 */"""

replace_once(old_comment_tail, new_comment_tail, "doc comment tail")

old_body = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;

    /* database -> 0x53FE18, written directly (see doc comment above:
     * the stub-execution approach for populating this region hangs
     * forever, so we use our own extracted copy instead). */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing database.bin\\n"));"""

new_body = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;

    /* stub_data -> 0x524C00, stub_code -> 0x527000, then trigger the
     * stub without waiting for a response (see doc comment above). */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing stub_data.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/stub_data.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/stub_data.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x524C00, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing stub_code.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/stub_code.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/stub_code.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x527000, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: triggering stub via BMIExecuteNoWait\\n"));
    bmifn(BMIExecuteNoWait(ar->arHifDevice, 0x527000));
    A_MDELAY(100);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: stub trigger done, reading back database region\\n"));

    {
        u8 dbg_word[4];
        int dbg_i;

        for (dbg_i = 0; dbg_i < 16; dbg_i += 4) {
            bmifn(BMIReadMemory(ar->arHifDevice, 0x53FE18 + dbg_i, dbg_word, 4));
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: database[0x53FE18+%02x] = %02x %02x %02x %02x\\n",
                dbg_i, dbg_word[0], dbg_word[1], dbg_word[2], dbg_word[3]));
        }
    }

    /* database -> 0x53FE18, written directly regardless of what the
     * stub produced above (known-working fallback -- see doc comment). */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing database.bin\\n"));"""

replace_once(old_body, new_body, "function body: add stub trigger + readback")

with open(path, 'w') as f:
    f.write(content)
print("OK")
