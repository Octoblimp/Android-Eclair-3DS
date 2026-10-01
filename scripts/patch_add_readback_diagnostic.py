from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

old = """    /* Run the EEPROM-reading stub at its own load address, so it can
     * populate the database region (0x53FE18) from real hardware. */
    param = 0;
    bmifn(BMIExecute(ar->arHifDevice, 0x527000, &param));

    /* main_type1 (basic internet firmware) -> 0x524C00, reusing the
     * address stub_data used -- safe now that the stub has run. */"""

new = """    /* Run the EEPROM-reading stub at its own load address, so it can
     * populate the database region (0x53FE18) from real hardware. */
    param = 0;
    bmifn(BMIExecute(ar->arHifDevice, 0x527000, &param));

    /* Phase 2 diagnostic: read back what the stub actually left behind,
     * so we can tell empirically whether it populated the database
     * region from real hardware (vs. leaving it untouched/zeroed),
     * without needing another full guess-and-reboot cycle. */
    {
        u8 dbg_database[32];
        u8 dbg_stubdata_area[16];
        int dbg_i;
        char dbg_line[256];
        int dbg_off;

        bmifn(BMIReadMemory(ar->arHifDevice, 0x53FE18, dbg_database, sizeof(dbg_database)));
        dbg_off = 0;
        dbg_line[0] = '\\0';
        for (dbg_i = 0; dbg_i < sizeof(dbg_database); dbg_i++) {
            dbg_off += snprintf(dbg_line + dbg_off, sizeof(dbg_line) - dbg_off, "%02x ", dbg_database[dbg_i]);
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: database[0x53FE18..+32] after stub exec = %s\\n", dbg_line));

        bmifn(BMIReadMemory(ar->arHifDevice, 0x524C00, dbg_stubdata_area, sizeof(dbg_stubdata_area)));
        dbg_off = 0;
        dbg_line[0] = '\\0';
        for (dbg_i = 0; dbg_i < sizeof(dbg_stubdata_area); dbg_i++) {
            dbg_off += snprintf(dbg_line + dbg_off, sizeof(dbg_line) - dbg_off, "%02x ", dbg_stubdata_area[dbg_i]);
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002 DIAG: 0x524C00[..+16] after stub exec (still stub_data?) = %s\\n", dbg_line));
    }

    /* main_type1 (basic internet firmware) -> 0x524C00, reusing the
     * address stub_data used -- safe now that the stub has run. */"""

count = content.count(old)
assert count == 1, f"expected 1 match, found {count}"
content = content.replace(old, new)

with open(path, 'w') as f:
    f.write(content)
print("OK")
