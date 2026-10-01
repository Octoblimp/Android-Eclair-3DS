"""Phase 2 / AR6002: dump the host-interest candidates BEFORE we write to them.

The previous dump ran inside ar6000_ar6002_boot_firmware, which happens after
ar6000_configure_target has already written the HTC version, hi_option_flag,
and the mailbox block size at the new base. So every "confirming" value at
0x520400 was just our own write echoed back -- circular, and no evidence at
all about where the firmware actually reads host interest from.

Meanwhile a proper disassembly of NWM shows Nintendo recording 0x00500400 as
the host-interest address in its config struct at 0x00154720 (field +0x34),
which is the address hardware reports as read-only. Those two facts can't
both be right, so look at the pristine contents.

This moves the dump to the very top of ar6000_configure_target, before any
host-interest write happens, and covers both the old base and both new
candidates. What to look for in a ROM-initialised host_interest_s: mostly
zeros, a handful of small plausible values, and ideally a pointer into the
0x52xxxx-0x53xxxx range at base+0x54 (hi_board_data).

If none of the three regions looks like a struct, the answer is that the
target was never reset and is still carrying Horizon's state -- which the
0x008Exxxx ARM11 heap pointers found at 0x520300 already hint at -- and a
cold reset before BMI becomes the next move.
"""
from a3ds_paths import A3DS_ROOT

drv = f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

with open(drv) as f:
    c = f.read()


def replace_once(old, new, label):
    global c
    n = c.count(old)
    assert n == 1, f"{label}: expected exactly 1 match, found {n}"
    c = c.replace(old, new)


# ------------------------------------- make the dump helper parameterised ---
old_dump = """#define AR6002_DUMP_START  0x00520300
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
}"""

new_dump = """#define AR6002_DUMP_MAX    0x400

static u8 ar6002_dump_buf[AR6002_DUMP_MAX];

static void
ar6002_dump_target_region(struct ar6_softc *ar, const char *tag,
                          u32 start, u32 len)
{
    u32 i;

    if (len > AR6002_DUMP_MAX) {
        len = AR6002_DUMP_MAX;
    }

    if (BMIReadMemory(ar->arHifDevice, start, ar6002_dump_buf, len) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 DUMP[%s] 0x%08x: read FAILED\\n", tag, start));
        return;
    }

    for (i = 0; i < len; i += 16) {
        u32 *w = (u32 *)&ar6002_dump_buf[i];

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 DUMP[%s] 0x%08x: %08x %08x %08x %08x\\n",
             tag, start + i, w[0], w[1], w[2], w[3]));
    }
}"""

replace_once(old_dump, new_dump, "parameterise dump helper")

replace_once(
    """    ar6002_probe_writable(ar);
    ar6002_dump_target_region(ar);
""",
    """    ar6002_probe_writable(ar);
""",
    "drop the contaminated post-write dump",
)


# ------------------- dump pristine state at the top of configure_target ---
old_cfg = """ar6000_configure_target(struct ar6_softc *ar)
{
    u32 param;
"""

new_cfg = """ar6000_configure_target(struct ar6_softc *ar)
{
    u32 param;

    /* Runs before any host-interest write, so this is the target's own
     * pristine state. Covers the stock base (0x500400, which hardware says is
     * read-only) and both RAM candidates (0x520400 = RAM_START+0x400 REV2
     * layout, 0x520600 = RAM_START+0x600 REV4 layout). Whichever region holds
     * a ROM-initialised host_interest_s is the real base. */
    if (ar->arTargetType == TARGET_TYPE_AR6002) {
        ar6002_dump_target_region(ar, "pristine-old", 0x00500380, 0x180);
        ar6002_dump_target_region(ar, "pristine-new", 0x00520380, 0x300);
    }
"""

replace_once(old_cfg, new_cfg, "dump pristine regions in configure_target")

with open(drv, "w") as f:
    f.write(c)
print("OK")
