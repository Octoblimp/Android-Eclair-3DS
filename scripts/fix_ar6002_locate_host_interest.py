"""Phase 2 / AR6002: locate the target's real host_interest_s, non-circularly.

Every "confirmation" of a host-interest base so far has been circular: we
wrote a value through our own guessed base and read the same value back.
That only proves the address is RAM -- it says nothing about where the
target's ROM firmware actually keeps its struct.

BMISetAppStart is different. bmi.c:423 shows it sends BMI_SET_APP_START +
address as a *command*; the target's boot ROM receives it and stores the
value into hi_app_start (offset 0x1c) inside whatever host_interest_s IT
knows about. Our AR6002_HOST_INTEREST_ADDRESS is not involved. So:

    issue BMISetAppStart(A), snapshot target RAM
    issue BMISetAppStart(B), snapshot target RAM again
    the word that went A -> B is hi_app_start, and base = that addr - 0x1c

Two different values are used rather than one so a hit cannot be a
coincidental match against pre-existing RAM contents -- the word has to
track both probes.

Also settles the memory map. Measured so far: 0x500400 read-only via BOTH
BMI and the diag window (so it is genuinely ROM, not a BMI range check),
0x51FF00 read-only, 0x520000/0x524C00/0x53FE18 writable. That puts a
256KB ROM at 0x4E0000-0x520000, which is the REV4/AR6003 ROM size, not
the REV2 80KB that AR6002_HOST_INTEREST_ADDRESS 0x00500400 assumes
(addrs.h: REV2 => RAM at 0x500000, REV4/AR6003 => RAM at 0x540000).
Whether RAM stops at 0x540000 or continues to 0x580000 like AR6003
decides which convention applies, so probe up there too and extend the
scan if it answers.
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


# ---------------------------------------------------------------- probe list
# Extend the writability probe past 0x540000 to decide the RAM extent, and
# remember the answer so the scan below can cover the larger map if it exists.
replace_once(
    """        0x0053FE18,   /* known good: database loads here           */
    };
    u32 i, orig, pattern, back;
""",
    """        0x0053FE18,   /* known good: database loads here           */
        0x0053FFFC,   /* last word if RAM ends at 0x540000          */
        0x00540000,   /* AR6003/REV4 RAM start -- does RAM go on?   */
        0x00560000,
        0x0057FF74,   /* AR6003 rev3 dataset patch addr             */
    };
    u32 i, orig, pattern, back;
""",
    "extend probe list",
)

replace_once(
    """        /* put it back before anything else runs */
        BMIWriteMemory(ar->arHifDevice, addr, (u8 *)&orig, 4);
""",
    """        /* put it back before anything else runs */
        BMIWriteMemory(ar->arHifDevice, addr, (u8 *)&orig, 4);

        if (addr == 0x00540000 && back == pattern) {
            ar6002_ram_past_540000 = true;
        }
""",
    "record high-RAM writability",
)

replace_once(
    """/* Write a unique pattern to each address, read it back, restore the original.""",
    """/* Set by ar6002_probe_writable() if 0x00540000 round-trips, i.e. RAM does not
 * stop where the Nintendo dataset-patch address (0x53FE18) implies it does. */
static bool ar6002_ram_past_540000;

/* Write a unique pattern to each address, read it back, restore the original.""",
    "declare high-RAM flag",
)

# ------------------------------------------------------- host-interest locator
old_anchor = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

new_anchor = """static u8 ar6002_scan_a[0x400];
static u8 ar6002_scan_b[0x400];

/* Find the host_interest_s the target's ROM actually uses, without going
 * through AR6002_HOST_INTEREST_ADDRESS.
 *
 * BMISetAppStart is a target-side command (bmi.c: BMI_SET_APP_START); the
 * ROM stores the address into hi_app_start at offset 0x1c of its own
 * struct. Issue it with two different values, diff target RAM between the
 * two, and the word that tracked both probes is hi_app_start. Everything
 * else we have "confirmed" about the base was us reading back our own
 * writes, which proves only that the address is RAM.
 *
 * Safe to call before BMIDone: the target does not begin executing until
 * BMI is finished, so SetAppStart is just a store and can be repeated.
 * The intended value is restored by the caller afterwards.
 */
static void
ar6002_locate_host_interest(struct ar6_softc *ar, u32 start, u32 end)
{
    const u32 probe1 = 0x00524C00;
    const u32 probe2 = 0x00538000;
    u32 addr, hits = 0;
    bool found = false;

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 HI-LOCATE: scanning 0x%08x..0x%08x for hi_app_start\\n",
         start, end));

    for (addr = start; addr < end; addr += sizeof(ar6002_scan_a)) {
        u32 *a = (u32 *)ar6002_scan_a;
        u32 *b = (u32 *)ar6002_scan_b;
        u32 i;

        if (BMISetAppStart(ar->arHifDevice, probe1) != 0 ||
            BMIReadMemory(ar->arHifDevice, addr,
                          ar6002_scan_a, sizeof(ar6002_scan_a)) != 0) {
            continue;
        }
        if (BMISetAppStart(ar->arHifDevice, probe2) != 0 ||
            BMIReadMemory(ar->arHifDevice, addr,
                          ar6002_scan_b, sizeof(ar6002_scan_b)) != 0) {
            continue;
        }

        for (i = 0; i < sizeof(ar6002_scan_a) / 4; i++) {
            u32 at;

            if (a[i] == b[i]) {
                continue;
            }
            at = addr + (i * 4);
            hits++;

            if (a[i] == probe1 && b[i] == probe2) {
                found = true;
                AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                    ("AR6002 HI-LOCATE: hi_app_start at 0x%08x"
                     " => host interest base 0x%08x (we use 0x%08x)\\n",
                     at, at - 0x1c, AR6002_HOST_INTEREST_ADDRESS));
            } else {
                /* Not our probe -- some other word the target touches
                 * between the two reads. Logged so it is not mistaken for
                 * a missed hit. */
                AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                    ("AR6002 HI-LOCATE: 0x%08x changed 0x%08x -> 0x%08x\\n",
                     at, a[i], b[i]));
            }
        }

        if (hits > 32) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                ("AR6002 HI-LOCATE: too many changing words, stopping at 0x%08x\\n",
                 addr));
            break;
        }
    }

    if (!found) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 HI-LOCATE: hi_app_start NOT found in 0x%08x..0x%08x"
             " (%d other words changed)\\n", start, end, hits));
    }
}

static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{"""

replace_once(old_anchor, new_anchor, "add host-interest locator")

# ------------------------------------------------------------------ call site
replace_once(
    """    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: calling BMISetAppStart\\n"));
    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: BMISetAppStart returned OK\\n"));

    return 0;""",
    """    /* Locate the ROM's own host_interest_s before committing to a value.
     * RAM is 0x520000..0x540000 on the evidence so far; if 0x540000 also
     * turned out writable the map is bigger than the dataset-patch address
     * implies, so cover the AR6003-shaped range too. */
    ar6002_locate_host_interest(ar, 0x00520000, 0x00540000);
    if (ar6002_ram_past_540000) {
        ar6002_locate_host_interest(ar, 0x00540000, 0x00580000);
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: calling BMISetAppStart\\n"));
    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: BMISetAppStart returned OK\\n"));

    /* Dumped after SetAppStart this time -- the previous "post-load" dump ran
     * before it, so hi_app_start reading 0 there proved nothing. */
    ar6002_dump_host_interest(ar, "post-appstart");

    return 0;""",
    "call locator",
)

with open(drv, "w") as f:
    f.write(c)
print("OK")
