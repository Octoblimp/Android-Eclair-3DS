"""Phase 2 / AR6002: register the board data with the target via the
host-interest area, which the AR6002 download path never did.

The AR6003 branch of ar6000_sysfs_bmi_get_config does three things with
board data:
  1. read hi_board_data to find where in target RAM it belongs,
  2. write the board data image there,
  3. write hi_board_data_initialized = 1.

Our AR6002 branch only ever did (2), to Nintendo's hardcoded 0x53FE18.
Step (3) is what tells the running firmware its RF/board calibration is
present and valid; without it the firmware has no reason to believe the
region holds anything, which fits the observed symptom exactly (firmware
starts, then asserts internally ~2s later before ever sending its HTC
ready message).

This patch adds a host-interest dump (so we learn what the target's own
defaults are) plus the missing hi_board_data / hi_board_data_initialized
writes.
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


# ---------------------------------------------------------------- helper ---
old_fn_open = """static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;
"""

new_fn_open = """/* AR6002 host interest lives at a fixed target RAM address
 * (AR6002_HOST_INTEREST_ADDRESS == 0x00500400), so these are plain BMI
 * memory reads -- safe to do before the firmware is started, and already
 * proven to work on this device (the hi_ext_clk_detected read earlier in
 * ar6000_sysfs_bmi_get_config uses the same mechanism). */
static void
ar6002_dump_host_interest(struct ar6_softc *ar, const char *when)
{
    u32 v;

#define AR6002_DUMP_HI(item)                                                  \\
    do {                                                                      \\
        v = 0xdeadbeef;                                                       \\
        if (BMIReadMemory(ar->arHifDevice,                                    \\
                          HOST_INTEREST_ITEM_ADDRESS(ar, item),               \\
                          (u8 *)&v, 4) == 0) {                                \\
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,                                    \\
                ("AR6002 HI[%s] " #item " = 0x%08x\\n", when, v));             \\
        } else {                                                              \\
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,                                    \\
                ("AR6002 HI[%s] " #item " READ FAILED\\n", when));             \\
        }                                                                     \\
    } while (0)

    AR6002_DUMP_HI(hi_board_data);
    AR6002_DUMP_HI(hi_board_data_initialized);
    AR6002_DUMP_HI(hi_option_flag);
    AR6002_DUMP_HI(hi_end_RAM_reserve_sz);
    AR6002_DUMP_HI(hi_app_start);
    AR6002_DUMP_HI(hi_mbox_io_block_sz);
    AR6002_DUMP_HI(hi_refclk_hz);
    AR6002_DUMP_HI(hi_ext_clk_detected);
    AR6002_DUMP_HI(hi_app_host_interest);

#undef AR6002_DUMP_HI
}

static int
ar6000_ar6002_boot_firmware(struct ar6_softc *ar)
{
    const struct firmware *fw_entry;
    struct device *dev = (struct device *)ar->osDevInfo.pOSDevice;
    u32 param;

    ar6002_dump_host_interest(ar, "pre-load");
"""

replace_once(old_fn_open, new_fn_open, "add HI dump helper + call")


# ------------------------------------------------ board data registration ---
old_setappstart = """    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: main_type1.bin written OK, calling BMISetAppStart\\n"));

    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));
"""

new_setappstart = """    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: main_type1.bin written OK\\n"));

    /* Tell the target where its board data is and that it is valid. The
     * AR6003 branch above does exactly this after its board data download
     * (hi_board_data + hi_board_data_initialized = 1); the AR6002 branch
     * never did, so the firmware had no reason to treat 0x53FE18 as
     * anything but uninitialized memory. */
    param = 0x53FE18;
    bmifn(BMIWriteMemory(ar->arHifDevice,
                         HOST_INTEREST_ITEM_ADDRESS(ar, hi_board_data),
                         (u8 *)&param, 4));
    param = 1;
    bmifn(BMIWriteMemory(ar->arHifDevice,
                         HOST_INTEREST_ITEM_ADDRESS(ar, hi_board_data_initialized),
                         (u8 *)&param, 4));
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: board data registered with target\\n"));

    ar6002_dump_host_interest(ar, "post-load");

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: calling BMISetAppStart\\n"));
    bmifn(BMISetAppStart(ar->arHifDevice, 0x524C00));
"""

replace_once(old_setappstart, new_setappstart, "register board data via host interest")


# ------------------------------------------------------------ doc comment ---
old_tail = """ * Current approach (reverted to the known-safe baseline after the above
 * test): skip the stub entirely, write our own extracted database.bin
 * directly to 0x53FE18. This is confirmed to get the target running
 * main_type1.bin far enough to report "Got WMI" and begin the HTC
 * handshake, before it asserts internally ~2s later, before ever
 * sending its HTC ready message -- see ar6000_target_failure /
 * DevPollMboxMsgRecv's timeout handling in ar6k_events.c, and the
 * "AR6K: Register Dump" it produces on a real device. That crash is the
 * next thing to investigate; it's a separate problem from the stub.
 */"""

new_tail = """ * Current approach: skip the stub entirely and write our own extracted
 * database.bin directly to 0x53FE18, THEN register it with the target
 * through the host interest area (hi_board_data = 0x53FE18,
 * hi_board_data_initialized = 1).
 *
 * That registration step is the fix for the next failure seen after the
 * stub work: with the data merely written to RAM and nothing else, the
 * target ran main_type1.bin but asserted internally ~2s later, before
 * ever sending its HTC ready message (ar6000_target_failure /
 * DevPollMboxMsgRecv's timeout in ar6k_events.c, plus an "AR6K: Register
 * Dump"). Comparing against the AR6003 branch of the same function makes
 * the omission obvious: AR6003 reads hi_board_data to find the download
 * address, writes the board data there, and then sets
 * hi_board_data_initialized = 1. The AR6002 branch only ever did the
 * middle step. Without the flag the firmware has no reason to treat the
 * region as valid calibration data, which is consistent with an assert
 * partway through RF/PHY init.
 *
 * ar6002_dump_host_interest() logs the relevant host interest words
 * before and after this, so the target's own defaults are visible in
 * dmesg for whatever comes next.
 */"""

replace_once(old_tail, new_tail, "doc comment tail")

with open(path, 'w') as f:
    f.write(content)
print("OK")
