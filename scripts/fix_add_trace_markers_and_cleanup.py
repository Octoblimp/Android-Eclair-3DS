from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)

# Remove now-unused `param` local (was only used by the removed BMIExecute call).
replace_once(
    """    const struct firmware *fw_entry;
    u32 param;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;""",
    """    const struct firmware *fw_entry;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;""",
    "remove unused param",
)

# Trace marker before main_type1 write, and before/after BMISetAppStart.
replace_once(
    """    /* main_type1 (basic internet firmware) -> 0x524C00 */
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/main_type1.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/main_type1.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x524C00, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);

    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));

    return 0;
}""",
    """    /* main_type1 (basic internet firmware) -> 0x524C00 */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: writing main_type1.bin\\n"));
    if (A_REQUEST_FIRMWARE(&fw_entry, "ath6k/AR6002/nwm/main_type1.bin", dev) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: failed to get nwm/main_type1.bin\\n"));
        return A_ERROR;
    }
    bmifn(BMIWriteMemory(ar->arHifDevice, 0x524C00, (u8 *)fw_entry->data, fw_entry->size));
    A_RELEASE_FIRMWARE(fw_entry);
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: main_type1.bin written OK, calling BMISetAppStart\\n"));

    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: BMISetAppStart returned OK\\n"));

    return 0;
}""",
    "trace markers",
)

with open(path, 'w') as f:
    f.write(content)
print("OK")
