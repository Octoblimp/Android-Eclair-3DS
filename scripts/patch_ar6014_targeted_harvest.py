#!/usr/bin/env python3
"""Legacy entry point for the bounded AR6014 scan-result locator.

This first applies the historical targeted-window transformation when needed,
then upgrades it to the address-independent sparse locator.  Keeping this old
entry point safe prevents a stale rebuild command from restoring the guessed
0x53a000..0x53e000 table window.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux")
DRV = ROOT / "drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"


drv = DRV.read_text()

if "N3DS_AR6014_VALIDATED_TARGET_BSS" in drv:
    print("patch_ar6014_targeted_harvest: validated hardware window already installed")
    raise SystemExit(0)

if "N3DS_AR6014_SPARSE_BSS_LOCATOR" in drv:
    print("patch_ar6014_targeted_harvest: sparse locator already installed")
    raise SystemExit(0)

old_constants = """#define AR6014_HARVEST_CHUNK         4096
#define AR6014_HARVEST_HOLDOFF_MS    3000
#define AR6014_HARVEST_MARGIN        (16 * 1024)
#define AR6014_HARVEST_NARROW_RUNS   8
"""
new_constants = """#define AR6014_HARVEST_CHUNK         4096
#define AR6014_HARVEST_HOLDOFF_MS    3000
/* N3DS_AR6014_TARGETED_BSS_HARVEST: decoded Nintendo scan nodes have been
 * observed around 0x53c6a0 (offset 0x1c6a0 in this 128 KiB RAM window).  A
 * full diagnostic sweep costs ~144 seconds on real 3DS hardware; this 16 KiB
 * window covers the firmware's approximately 8 KiB fixed-stride BSS table
 * and completes before nl80211's scan timeout. */
#define AR6014_HARVEST_BOOT_LO       0x0001a000
#define AR6014_HARVEST_BOOT_HI       0x0001e000
#define AR6014_HARVEST_MARGIN        (4 * 1024)
#define AR6014_HARVEST_NARROW_RUNS   32
"""
if "N3DS_AR6014_TARGETED_BSS_HARVEST" not in drv:
    if drv.count(old_constants) != 1:
        raise SystemExit("AR6014 harvest constants hunk not found exactly once")
    drv = drv.replace(old_constants, new_constants)

old_range = """    } else {
        lo = 0;
        hi = AR6014_RAM_SIZE;
        ar6014_harvest_narrow = AR6014_HARVEST_NARROW_RUNS;
    }
"""
new_range = """    } else {
        lo = AR6014_HARVEST_BOOT_LO;
        hi = AR6014_HARVEST_BOOT_HI;
        ar6014_harvest_narrow = AR6014_HARVEST_NARROW_RUNS;
    }
"""
if drv.count(old_range) == 1:
    drv = drv.replace(old_range, new_range)
elif drv.count(new_range) != 1:
    raise SystemExit("AR6014 initial harvest range hunk not found exactly once")

old_empty = """    } else if (lo != 0 || hi != AR6014_RAM_SIZE) {
        ar6014_harvest_narrow = 0;
    }
"""
new_empty = """    } else {
        /* Stay on the decoded table region.  Falling back to the old blind
         * 128 KiB sweep regresses one scan into a multi-minute lockout. */
        ar6014_harvest_lo = 0;
        ar6014_harvest_hi = 0;
        ar6014_harvest_narrow = 0;
    }
"""
if drv.count(old_empty) == 1:
    drv = drv.replace(old_empty, new_empty)
elif drv.count(new_empty) != 1:
    raise SystemExit("AR6014 empty-harvest hunk not found exactly once")

old_log = """         found, ar6014_bss_cache_count, injected, lo, hi));
"""
new_log = """         found, ar6014_bss_cache_count, injected, lo, hi));
    if (found)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: result span=0x%x..0x%x target=0x%x..0x%x\\n",
             seen_lo, seen_hi, AR6014_HI + seen_lo,
             AR6014_HI + seen_hi));
"""
if "AR6002 scan: result span=" not in drv:
    if drv.count(old_log) != 1:
        raise SystemExit("AR6014 harvest log hunk not found exactly once")
    drv = drv.replace(old_log, new_log)

DRV.write_text(drv)

sparse = Path(__file__).with_name("patch_ar6014_sparse_bss_locator.py")
exec(compile(sparse.read_text(), str(sparse), "exec"))
