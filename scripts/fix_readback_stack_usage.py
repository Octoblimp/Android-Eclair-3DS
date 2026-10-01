from a3ds_paths import A3DS_ROOT
path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()

old = """    /* Phase 2 diagnostic: read back what the stub actually left behind,
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

new = """    /* Phase 2 diagnostic: read back what the stub actually left behind,
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

count = content.count(old)
assert count == 1, f"expected 1 match, found {count}"
content = content.replace(old, new)

with open(path, 'w') as f:
    f.write(content)
print("OK")
