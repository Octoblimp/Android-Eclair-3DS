"""Scan Nintendo's decompressed NWM ARM11 code for target-address literals.

We know the driver's AR6002_HOST_INTEREST_ADDRESS (0x00500400) is wrong for
this chip: on hardware, reads there return ROM-looking garbage and writes are
silently dropped. Nintendo's own WiFi module must reference the correct base,
so mine its literal pools for words in the target address space and see what
clusters where.

Known-good anchors we should see fall out of this, which validate the method:
  0x00524C00  stub_data / main_type1 load address
  0x00527000  stub_code load address
  0x0053FE18  database (DataSet patch) load address
"""

import collections
import struct
import sys
import os

BASE = os.path.join(os.path.dirname(__file__), "..", "content")
PATH = os.path.join(BASE, "code_decompressed.bin")

with open(PATH, "rb") as f:
    data = f.read()

print(f"{PATH}: {len(data)} bytes\n")

LO, HI = 0x004E0000, 0x00560000

hits = collections.defaultdict(list)
for off in range(0, len(data) - 3, 4):
    (w,) = struct.unpack_from("<I", data, off)
    if LO <= w < HI:
        hits[w].append(off)

print(f"distinct target-space literals in [0x{LO:06X},0x{HI:06X}): {len(hits)}\n")

KNOWN = {
    0x00524C00: "stub_data / main_type1 load addr",
    0x00527000: "stub_code load addr",
    0x0053FE18: "database (DataSet patch) load addr",
}

print("=== all literals, sorted by address ===")
for w in sorted(hits):
    note = KNOWN.get(w, "")
    offs = hits[w]
    shown = " ".join(f"{o:#08x}" for o in offs[:6])
    more = f" (+{len(offs) - 6} more)" if len(offs) > 6 else ""
    print(f"  0x{w:08X}  x{len(offs):-3d}  at {shown}{more}   {note}")

print("\n=== candidates in the host-interest window (base+0x000..0x100) ===")
print("A host-interest base should show up as a cluster: the base itself")
print("and/or several nearby addresses (base+0x18, +0x54, +0x58, +0x6c ...)")
for cand_base in sorted({w & ~0xFFF for w in hits}):
    near = sorted(w for w in hits if cand_base <= w < cand_base + 0x1000)
    if len(near) >= 2:
        print(f"\n  page 0x{cand_base:08X}:")
        for w in near:
            print(f"      0x{w:08X}  x{len(hits[w])}")
