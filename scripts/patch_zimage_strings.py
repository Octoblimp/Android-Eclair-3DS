#!/usr/bin/env python3
"""Add the ctr_csnd capture probes to the shipped-zImage string gate.

This gate exists because a symbol missing from System.map proves nothing
(gcc partial-inlines these static helpers) while a format string in
.rodata proves the code shipped.  It reads the zip the user actually
flashes, so it also catches a stale pack.

The capture path is new and is exactly the kind of change that would
otherwise ship silently stale: /dev/eac grew a .read, the codec ADC and
MICBIAS are powered on first use, and the sample source is an explicitly
marked seam.  If a future build drops any of that, recording goes quiet
in a way that looks identical to a hardware fault -- assert it here.

Idempotent: keyed on the marker comment.
"""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

import io
import sys

COPIES = [
    f"{A3DS_ROOT}/scripts/verify_zimage_strings.py",
    f"{A3DS_WIN}"
    "/scripts/verify_zimage_strings.py",
]

ANCHOR = '''    "does not restore",
    "before the walk",
]
'''

NEW = '''    "does not restore",
    "before the walk",
    # ctr_csnd capture: /dev/eac grew a .read, and this banner is the
    # contract AudioStreamInGeneric::set() demands -- 8000 Hz, mono, S16.
    # If this string moves, the recorder gets -EINVAL and nothing records.
    "returns 16-bit mono at 8000 Hz on read",
    # The analog front end really is powered, via documented TSC2117
    # registers, not guessed ones.
    "codec: ADC + MICBIAS powered",
    # ...and the honest part: the front end is live but the MIC block at
    # 0x10162000 is as undocumented as the CAM block, so reads return
    # paced silence rather than invented samples.  This line is the seam.
    # Losing it would mean someone wired a sample source without saying so.
    "capture: front end is live but there is no sample source yet",
]
'''

changed = 0
for path in COPIES:
    try:
        with io.open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except IOError as e:
        print("  SKIP (unreadable): %s (%s)" % (path, e))
        continue

    if "ctr_csnd capture" in src:
        print("  already patched: %s" % path)
        continue
    if ANCHOR not in src:
        print("  ANCHOR NOT FOUND: %s" % path)
        sys.exit(1)

    src = src.replace(ANCHOR, NEW, 1)
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print("  patched: %s" % path)
    changed += 1

print("changed=%d" % changed)
