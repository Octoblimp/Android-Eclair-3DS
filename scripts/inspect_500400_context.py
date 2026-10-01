"""Show the literal-pool context around every 0x00500400 reference in NWM.

0x00500400 is AR6002_HOST_INTEREST_ADDRESS in the Linux driver. On hardware
that region reads back deterministic, unchanging values and swallows writes,
which is ROM behaviour -- but NWM references 0x500400 twice, which would
argue it is a real, writable host-interest base. Those two claims can't both
be true, so look at what the literals around each reference actually are.

A genuine host-interest base should sit near other AR6002 register/target
constants. If instead it sits among unrelated values, the match is a
coincidence and the ROM reading stands.
"""

import struct
import os

BASE = os.path.join(os.path.dirname(__file__), "..", "content")
PATH = os.path.join(BASE, "code_decompressed.bin")

with open(PATH, "rb") as f:
    data = f.read()

TARGETS = [0x0322D4, 0x054754]
WINDOW = 0x40  # bytes either side

# Anything a host-interest access would plausibly sit near.
NOTABLE = {
    0x00500400: "<-- AR6002_HOST_INTEREST_ADDRESS",
    0x00524C00: "main_type1 / stub_data load addr",
    0x00527000: "stub_code load addr",
    0x0053FE18: "database (DataSet patch) load addr",
    0x0051FE00: "seen 3x elsewhere",
    0x00520000: "",
    0x00511D40: "dset descriptor data ptr",
}

for t in TARGETS:
    lo = max(0, t - WINDOW)
    hi = min(len(data), t + WINDOW + 4)
    print(f"=== context around file offset 0x{t:06X} ===")
    for off in range(lo, hi, 4):
        (w,) = struct.unpack_from("<I", data, off)
        mark = " <<<" if off == t else "    "
        note = NOTABLE.get(w, "")
        # Flag anything that looks like an AR6K target-space address.
        kind = ""
        if 0x004E0000 <= w < 0x00560000:
            kind = "  [target-space]"
        print(f"  0x{off:06X}: 0x{w:08X}{mark}{kind}  {note}")
    print()
