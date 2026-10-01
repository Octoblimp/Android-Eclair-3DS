"""Phase 2 / AR6002: settle whether BMI memory writes round-trip.

State of the evidence:
  - We wrote 0x53FE18 to hi_dset_list_head (BMIWriteMemory returned OK) and
    read back the pre-load value, unchanged.
  - All 11 host-interest reads returned byte-identical values before and
    after the load, so reads are deterministic per address, not a
    desynchronised response stream.
  - AR6002_HOST_INTEREST_ADDRESS (0x00500400) is confirmed correct from
    Nintendo's own NWM code: a literal pool at file offset 0x0322D4 holds
    0x00500400, and the function immediately above it stores to [r5,#0x00],
    #0x1C, #0x50, #0x54, #0x58, #0x5C, #0x60, #0x64, #0x68, #0x6C, #0x70,
    #0x74, #0x78 -- the host_interest_s field layout exactly.
  - BMIWriteMemory and BMIReadMemory both look correct in source for a
    4-byte transfer.

Those can't all hold, so measure instead of theorising. For each address:
read the original word, write a unique pattern, read it back, restore the
original. Every probed address is one the driver already writes to during a
normal boot, so this adds no new risk.

Outcomes:
  0x53FE18 round-trips, 0x5004xx does not -> the host-interest region
      specifically is not writable; memory-map or chip-state problem.
  Neither round-trips -> BMIReadMemory does not reflect writes at all. That
      would make ar6000_configure_target's read-modify-write on
      hi_option_flag feed the firmware a garbage option word on every boot,
      which is a sufficient cause for the init assert.
  Both round-trip -> something clears hi_dset_list_head between our write
      and the dump.
"""
from a3ds_paths import A3DS_ROOT

path = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"
with open(path) as f:
    content = f.read()


def replace_once(old, new, label):
    global content
    count = content.count(old)
    assert count == 1, f"{label}: expected exactly 1 match, found {count}"
    content = content.replace(old, new)


old_anchor = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

new_anchor = """/* Write a unique pattern to each address, read it back, restore the original.
 * Deliberately does not use bmifn(): a failure on one probe should not abort
 * the rest. Every address here is one the driver already writes during a
 * normal boot, so this adds no exposure beyond what we already do. */
static void
ar6002_probe_writable(struct ar6_softc *ar)
{
    static const u32 probe_addrs[] = {
        0x00500400,   /* hi_app_host_interest  (base + 0x00) */
        0x00500418,   /* hi_dset_list_head     (base + 0x18) */
        0x00500454,   /* hi_board_data         (base + 0x54) */
        0x0050046C,   /* hi_mbox_io_block_sz   (base + 0x6c) */
        0x00524C00,   /* known good: main_type1 loads here   */
        0x0053FE18,   /* known good: database loads here     */
    };
    u32 i, orig, pattern, back;

    for (i = 0; i < sizeof(probe_addrs) / sizeof(probe_addrs[0]); i++) {
        u32 addr = probe_addrs[i];

        if (BMIReadMemory(ar->arHifDevice, addr, (u8 *)&orig, 4) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 PROBE 0x%08x: initial read FAILED\\n", addr));
            continue;
        }

        pattern = 0xA5A50000 | i;
        if (BMIWriteMemory(ar->arHifDevice, addr, (u8 *)&pattern, 4) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 PROBE 0x%08x: write FAILED (orig 0x%08x)\\n", addr, orig));
            continue;
        }

        if (BMIReadMemory(ar->arHifDevice, addr, (u8 *)&back, 4) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 PROBE 0x%08x: readback FAILED\\n", addr));
            continue;
        }

        /* put it back before anything else runs */
        BMIWriteMemory(ar->arHifDevice, addr, (u8 *)&orig, 4);

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 PROBE 0x%08x: orig=0x%08x wrote=0x%08x read=0x%08x %s\\n",
             addr, orig, pattern, back,
             (back == pattern) ? "WRITABLE" : "*** NOT WRITABLE ***"));
    }
}

static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

replace_once(old_anchor, new_anchor, "add ar6002_probe_writable")

replace_once(
    """    ar6002_dump_host_interest(ar, "pre-load");
""",
    """    ar6002_dump_host_interest(ar, "pre-load");
    ar6002_probe_writable(ar);
""",
    "call probe before load",
)

with open(path, 'w') as f:
    f.write(content)
print("OK")
