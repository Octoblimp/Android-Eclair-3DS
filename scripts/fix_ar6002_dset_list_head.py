"""Phase 2 / AR6002: register database.bin as the target's DataSet patch
list via hi_dset_list_head.

Supersedes the hi_board_data theory in
fix_ar6002_board_data_host_interest.py. A full hexdump of Nintendo's
extracted database.bin shows it is NOT an EEPROM/board-data image -- it
is an AR6K DataSet descriptor list plus a BDIFF patch stream, with all
pointers pre-relocated for a load address of exactly 0x53FE18:

  file 0x00  next=0x0053FE2C id=0x00040118 data=0x0053FFF4 ...
  file 0x14  next=0x0053FE40 id=0x00040119 data=0x0053FFF0 ...
  file 0x28  next=0x0053FE54 id=0x0E040002 data=0x00511D40 ...
  file 0x3C  ...             ...           data=0x0053FE68 ...
  file 0x50  "BDIFF" magic   <- exactly where 0x0053FE68 points
  file 0x1E0 0x0053FE18      <- self-pointer in the last 8 bytes of RAM

Every 0x53Fxxx pointer resolves to `0x53FE18 + its own file offset`, and
the descriptor at file 0x3C points at the BDIFF stream at file 0x50.
That is the AR6K dataset-patch format.

It also sits in the same place AR6003's dataset patch does -- a fixed
address a few hundred bytes below the top of target RAM:

  AR6003_REV2_DATASET_PATCH_ADDRESS 0x57E884 (RAM ends 0x580000)
  AR6003_REV3_DATASET_PATCH_ADDRESS 0x57FF74 (RAM ends 0x580000)
  Nintendo AR6002                   0x53FE18 (RAM ends 0x540000, 488B)

The AR6003 branch of ar6000_sysfs_bmi_get_config downloads its patch
file to that address and then writes hi_dset_list_head = <that address>.
Our AR6002 branch did the download but never the registration, so the
firmware's ROM-patch mechanism never saw the list and ran unpatched --
which fits the observed assert partway through firmware init.
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


# --------------------------------------------------- widen the HI dump ---
replace_once(
    """    AR6002_DUMP_HI(hi_board_data);
    AR6002_DUMP_HI(hi_board_data_initialized);
    AR6002_DUMP_HI(hi_option_flag);""",
    """    AR6002_DUMP_HI(hi_dset_list_head);
    AR6002_DUMP_HI(hi_dset_RAM_index_table);
    AR6002_DUMP_HI(hi_board_data);
    AR6002_DUMP_HI(hi_board_data_initialized);
    AR6002_DUMP_HI(hi_option_flag);""",
    "add dset items to HI dump",
)


# ------------------------------- swap board-data reg for dset list reg ---
old_reg = """    /* Tell the target where its board data is and that it is valid. The
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
"""

new_reg = """    /* Point the target's DataSet patch mechanism at the descriptor list we
     * just wrote to 0x53FE18. The AR6003 branch above does exactly this
     * for its own patch file (download to a fixed address near the top of
     * RAM, then hi_dset_list_head = that address); the AR6002 branch never
     * did, so the target ran its ROM unpatched. */
    param = 0x53FE18;
    bmifn(BMIWriteMemory(ar->arHifDevice,
                         HOST_INTEREST_ITEM_ADDRESS(ar, hi_dset_list_head),
                         (u8 *)&param, 4));
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("AR6002: hi_dset_list_head set to 0x53FE18\\n"));
"""

replace_once(old_reg, new_reg, "replace board-data reg with dset list reg")


# ------------------------------------------------------- doc comment ---
old_tail = """ * Current approach: skip the stub entirely and write our own extracted
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

new_tail = """ * "database" is a misnomer inherited from the extraction notes: a full
 * hexdump shows it is an AR6K DataSet descriptor list plus a BDIFF patch
 * stream, with every pointer pre-relocated for a load address of exactly
 * 0x53FE18. Each descriptor is 20 bytes (next, id, data, type, aux); the
 * chain runs 0x53FE18 -> 0x53FE2C -> 0x53FE40 -> 0x53FE54 -> 0x53FE68,
 * i.e. base + 0x00/0x14/0x28/0x3C/0x50, and the last of those points at
 * file offset 0x50 -- which is exactly where the "BDIFF" magic sits. The
 * final 8 bytes of the blob land on the last 8 bytes of target RAM
 * (0x53FFF8) and hold a self-pointer back to 0x53FE18, mirroring
 * ROM_DATASET_INDEX_ADDR's convention in AR6002/addrs.h.
 *
 * It is also placed exactly where AR6003 places its dataset patch -- a
 * fixed address a few hundred bytes below the top of target RAM:
 *   AR6003_REV2_DATASET_PATCH_ADDRESS 0x57E884 (RAM ends 0x580000)
 *   AR6003_REV3_DATASET_PATCH_ADDRESS 0x57FF74 (RAM ends 0x580000)
 *   Nintendo AR6002 database.bin      0x53FE18 (RAM ends 0x540000, 488B)
 *
 * Current approach: skip the stub entirely, write database.bin directly
 * to 0x53FE18, then register it via hi_dset_list_head = 0x53FE18 exactly
 * as the AR6003 branch does for its own patch file. That registration is
 * the fix for the failure seen after the stub work: with the blob merely
 * present in RAM and nothing pointing at it, the target ran main_type1
 * unpatched and asserted internally ~2s later, before ever sending its
 * HTC ready message (ar6000_target_failure / DevPollMboxMsgRecv's
 * timeout in ar6k_events.c, plus an "AR6K: Register Dump").
 *
 * Note this blob is NOT board/EEPROM calibration data, so hi_board_data
 * and hi_board_data_initialized are deliberately left alone -- pointing
 * the firmware's board-data reader at a descriptor list would be its own
 * new bug. Where AR6002 RF calibration actually comes from is still open.
 *
 * ar6002_dump_host_interest() logs the relevant host interest words
 * before and after this, so the target's own defaults are visible in
 * dmesg for whatever comes next.
 */"""

replace_once(old_tail, new_tail, "doc comment tail")

with open(path, 'w') as f:
    f.write(content)
print("OK")
