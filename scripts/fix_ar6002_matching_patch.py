"""Phase 2 / AR6002: use the patch file that actually matches athwlan.bin.z77.

Last boot proved the real firmware genuinely executes: hi_option_flag
changed from the fixed 0x1200 seen on every prior boot (including with
main_type1.bin) to 0x1202, and the register dump's address-bearing slots
(2/3/4/43/44) shifted from 0x00524C00 to 0x00538000 -- both are firmware
doing something new, not noise. But it still asserts at the same location
with the same ~2.1s Got-WMI-to-timeout interval.

We were still layering nwm/database.bin -- Nintendo's DataSet patch,
decoded in an earlier session with DataPtr fields at 0x53FE2C/40/54/68 and
0x511D40, all addresses specific to main_type1.bin's layout -- on top of
the real athwlan.bin.z77 firmware. data.patch.hw2_0.bin, sitting next to
athwlan.bin.z77 and eeprom.bin in the same directory (as opposed to
nwm/, Nintendo's own separate tree), has the identical 20-byte descriptor
format but DataPtr fields at 0x0052dXXX -- squarely inside the real
firmware's own data section. That's the patch actually meant to pair with
this firmware.
"""
from a3ds_paths import A3DS_ROOT

drv = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

with open(drv) as f:
    c = f.read()

old = """    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing database.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/database.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/database.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x53FE18, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: database.bin written OK\\n"));"""

assert old in c, "expected database.bin block not found verbatim"

new = """    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing data.patch.hw2_0.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/data.patch.hw2_0.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get data.patch.hw2_0.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x53FE18, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: data.patch.hw2_0.bin written OK\\n"));"""

c = c.replace(old, new)

with open(drv, "w") as f:
    f.write(c)
print("OK")
