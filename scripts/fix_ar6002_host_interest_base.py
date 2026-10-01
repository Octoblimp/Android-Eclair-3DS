"""Phase 2 / AR6002: move the host-interest base out of ROM.

Hardware probe result (write pattern, read back, restore):

  0x00500400  NOT WRITABLE      0x00524C00  WRITABLE   (main_type1 loads here)
  0x00500418  NOT WRITABLE      0x0053FE18  WRITABLE   (database loads here)
  0x00500454  NOT WRITABLE
  0x0050046C  NOT WRITABLE

BMI reads and writes both work -- the controls round-trip exactly. The whole
0x5004xx host-interest region is read-only, i.e. ROM. With ROM based at
0x4E0000 that implies a 256KB ROM (0x4E0000..0x520000) and RAM starting at
0x520000, not the 0x500000 the REV2 constants in this driver assume. That
fits the rest of the map: main_type1 at 0x524C00 and the DataSet blob at
0x53FE18 are both in RAM, and 0x53FE18 is 488 bytes below the 0x540000 top.

Everything routed through HOST_INTEREST_ITEM_ADDRESS has therefore been
writing into ROM and reading uninitialised ROM contents back: the HTC
protocol version, the fwmode/num_dev bits in hi_option_flag (a
read-modify-write, so the firmware got a garbage option word), the mailbox
IO block size, our hi_dset_list_head, and the hi_failure_state the assert
handler reads to locate the register dump -- which is why that dump printed
60 words of noise from 0xCC503C03.

Two candidate bases:
  0x520400  RAM_START + 0x400, the REV2 layout. Appears twice in NWM's
            literals; nearby literals map onto real fields, notably
            0x52047C -> offset 0x7C = hi_ext_clk_detected.
  0x520600  RAM_START + 0x600, which addrs.h uses for REV4/AR6003.
            0x520630 -> offset 0x30 = hi_xtal_control_setting.

This patch takes the 0x520400 shot and, independently, dumps 1KB spanning
both candidates so the log shows which region actually looks like a
host_interest struct (mostly zeros, sparse plausible values, a pointer near
0x53Fxxx at +0x54) regardless of whether the guess was right.
"""
from a3ds_paths import A3DS_ROOT

targaddrs = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/include/common/targaddrs.h"
drv = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"


def patch(path, pairs):
    with open(path) as f:
        c = f.read()
    for old, new, label in pairs:
        n = c.count(old)
        assert n == 1, f"{label}: expected exactly 1 match, found {n}"
        c = c.replace(old, new)
    with open(path, "w") as f:
        f.write(c)


# ------------------------------------------------------- the actual fix ---
patch(targaddrs, [(
    "#define AR6002_HOST_INTEREST_ADDRESS    0x00500400",
    """/* This chip's ROM is 256KB at 0x4E0000, so it covers 0x500400 and RAM does
 * not start until 0x520000 -- confirmed on hardware by a BMI write/readback
 * probe: 0x500400/0x500418/0x500454/0x50046C are all read-only, while
 * 0x524C00 and 0x53FE18 round-trip. The stock 0x00500400 is the REV2 value
 * and puts every host-interest access into ROM, where writes are silently
 * dropped and reads return ROM contents. 0x520600 (the REV4 +0x600 layout)
 * is the other candidate if this one proves wrong. */
#define AR6002_HOST_INTEREST_ADDRESS    0x00520400""",
    "move AR6002 host interest base to RAM",
)])


# ---------------------------------------- retarget probe + add raw dump ---
old_probe_list = """    static const u32 probe_addrs[] = {
        0x00500400,   /* hi_app_host_interest  (base + 0x00) */
        0x00500418,   /* hi_dset_list_head     (base + 0x18) */
        0x00500454,   /* hi_board_data         (base + 0x54) */
        0x0050046C,   /* hi_mbox_io_block_sz   (base + 0x6c) */
        0x00524C00,   /* known good: main_type1 loads here   */
        0x0053FE18,   /* known good: database loads here     */
    };"""

new_probe_list = """    static const u32 probe_addrs[] = {
        0x00500400,   /* old base: known ROM, expect NOT WRITABLE  */
        0x0051FF00,   /* just below the suspected ROM/RAM boundary */
        0x00520000,   /* suspected start of RAM                    */
        0x00520400,   /* candidate host-interest base (REV2 +0x400)*/
        0x00520600,   /* candidate host-interest base (REV4 +0x600)*/
        0x00524C00,   /* known good: main_type1 loads here         */
        0x0053FE18,   /* known good: database loads here           */
    };"""

# Dump a window covering both candidate bases so the struct is visible in the
# log even if the base we picked is wrong.
old_anchor = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

new_anchor = """/* Dump raw target memory across both candidate host-interest bases. A real
 * host_interest_s reads as mostly zeros with a few plausible values, and
 * should show a pointer into the 0x53Fxxx range at base+0x54 (hi_board_data). */
#define AR6002_DUMP_START  0x00520300
#define AR6002_DUMP_LEN    0x400

static u8 ar6002_dump_buf[AR6002_DUMP_LEN];

static void
ar6002_dump_target_region(struct ar6_softc *ar)
{
    u32 i;

    if (BMIReadMemory(ar->arHifDevice, AR6002_DUMP_START,
                      ar6002_dump_buf, AR6002_DUMP_LEN) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 DUMP 0x%08x: read FAILED\\n", AR6002_DUMP_START));
        return;
    }

    for (i = 0; i < AR6002_DUMP_LEN; i += 16) {
        u32 *w = (u32 *)&ar6002_dump_buf[i];

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 DUMP 0x%08x: %08x %08x %08x %08x\\n",
             AR6002_DUMP_START + i, w[0], w[1], w[2], w[3]));
    }
}

static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

patch(drv, [
    (old_probe_list, new_probe_list, "retarget writability probe"),
    (old_anchor, new_anchor, "add raw region dump"),
    ("""    ar6002_probe_writable(ar);
""",
     """    ar6002_probe_writable(ar);
    ar6002_dump_target_region(ar);
""",
     "call region dump"),
])

print("OK")
