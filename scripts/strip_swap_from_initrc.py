#!/usr/bin/env python3
"""Remove the SD-card swap block from the SD-hosted init.rc.

Swap was added on 2026-08-04 as a hypothesis-driven mitigation for the
multi-CPU soft lockup. It never worked: boot_log_latest.txt shows
`setup_swap: FAILED mkswap -- continuing without swap` after burning
30 seconds (13.8s -> 44.5s) `dd`ing a 128 MB file onto the SD card on
*every* boot, followed by `init: command 'exec' FAILED`. The lockup
happened anyway. Removed per user direction.
"""
from a3ds_paths import A3DS_ROOT
import sys

PATH = (f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/"
        "rootfs_overlay/etc/init.rc")

MARKER_START = "# 256MB device, NO swap"
MARKER_END = "    class_start default"

s = open(PATH).read()
if MARKER_START not in s:
    print("swap block already absent -- nothing to do")
    sys.exit(0)

start = s.index(MARKER_START)
end = s.index(MARKER_END)
s = s[:start] + s[end:]
open(PATH, "w").write(s)
print("removed swap block from", PATH)
