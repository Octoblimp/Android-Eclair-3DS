from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

old_comment_tail = """ * Current approach: trigger the stub via BMIExecuteNoWait (sends the
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

new_comment_tail = """ * Triggering the stub via BMIExecuteNoWait (send the BMI_EXECUTE command
 * without waiting for/reading a response) was also tried, on the theory
 * that the stub reads real per-console RF calibration off a physical
 * EEPROM into the database region. This is confirmed WORSE than not
 * running it at all: a hardware test showed that after triggering it and
 * delaying 100ms, the very next BMI operation (a simple memory read)
 * failed only after ~100,000 busy-polling iterations
 * (BMI_COMMUNICATION_TIMEOUT in bmiBufferSend's credit-wait loop,
 * bmi.c), with "BMI Communication timeout - bmiBufferSend" / "Unable to
 * write to the device" -- i.e. the target's BMI/SDIO command-credit
 * flow control was completely wedged, not just non-responsive to our
 * specific read. SDIO interrupt count went from ~5k to ~175k across a
 * 30s window during this failure. So running this stub code standalone
 * doesn't just fail to signal completion (as with plain BMIExecute) --
 * it crashes the target's whole BMI communication layer. Most likely
 * explanation is unchanged: the stub depends on NWM module runtime
 * infrastructure that doesn't exist when invoked raw, and running it
 * corrupts something the target's boot ROM/BMI handler itself depends
 * on (e.g. interrupt vectors, stack, or a peripheral init).
 *
 * Current approach (reverted to the known-safe baseline after the above
 * test): skip the stub entirely, write our own extracted database.bin
 * directly to 0x53FE18. This is confirmed to get the target running
 * main_type1.bin far enough to report "Got WMI" and begin the HTC
 * handshake, before it asserts internally ~2s later, before ever
 * sending its HTC ready message -- see ar6000_target_failure /
 * DevPollMboxMsgRecv's timeout handling in ar6k_events.c, and the
 * "AR6K: Register Dump" it produces on a real device. That crash is the
 * next thing to investigate; it's a separate problem from the stub.
 */"""

replace_once(old_comment_tail, new_comment_tail, "doc comment tail")

old_body = """static int
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

new_body = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;

    /* database -> 0x53FE18, written directly (see doc comment above:
     * running the stub -- even fire-and-forget -- wedges the target's
     * BMI communication layer, so we use our own extracted copy instead
     * of relying on the stub to populate it from hardware). */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing database.bin\\n"));"""

replace_once(old_body, new_body, "revert function body to stubless baseline")

with open(path, 'w') as f:
    f.write(content)
print("OK")
