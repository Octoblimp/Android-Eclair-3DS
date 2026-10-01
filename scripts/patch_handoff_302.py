#!/usr/bin/env python3
"""Record kernel #302 in HANDOFF.md: the camera map, and where the start bit is.

Written because the previous session's best evidence -- the full CAM/CAM1/Y2R
writable-bit sweep -- existed only in boot_progress.txt, which is overwritten
every boot.  A finding that lives in a file the next boot destroys is a finding
nobody has.
"""
from a3ds_paths import A3DS_ROOT
import io

PATH = f"{A3DS_ROOT}/HANDOFF.md"

doc = io.open(PATH, encoding="utf-8").read()
orig = doc

# ------------------------------------------------------------- header ---
old = """**Last updated:** 2026-09-12 (kernel #300)
**Current flashable:** `sdcard.zip`, 59,365,677 bytes, md5 `70d9d923739336c51101b46b8613bdb1`
"""
new = """**Last updated:** 2026-09-12 (kernel #302)
**Current flashable:** `sdcard.zip`, 59,371,688 bytes, md5 `bbe04b74626dc52df2c083c936ad60a1`

That zip carries both halves of the current work: the DSP audio evidence
probes (§3.13) and the camera control-bit walk (§3.14). One flash, both
captures.
"""
assert old in doc, "header anchor missing"
doc = doc.replace(old, new, 1)

# ---------------------------------------------------------- section 3.14 ---
section = """## 3.14 Kernel #302: the CAM register file is 24 bytes, and the start bit has
six places left to hide

### The sweep result, which was about to be lost

The #301 capture ran the full writable-bit sweep and the result went into
`boot_progress.txt` -- a file the next boot overwrites. It is now in the driver
as `N3DS_CAM_MEASURED_MAP` and in `docs/CAMERA_RESEARCH.md`. This is the first
measurement of the 3DS CAM block that exists anywhere; 3dbrew's page is an empty
stub and GBATEK's is a 404.

| Offset | CAM `wmask` | CAM1 `wmask` | reset | Reading |
|---|---|---|---|---|
| `+0x000` | `ef1c` | `ef0c` | `0010` / `0000` | control |
| `+0x006` | `003f` | `003f` | `0000` | 6-bit field, unidentified |
| `+0x010` | `03fe` | `03fe` | `0000` | crop `xStart`, even, 0-1022 |
| `+0x012` | `01ff` | `01ff` | `0000` | crop `yStart`, 0-511 |
| `+0x014` | `03fe` | `03fe` | `0000` | crop `xEnd`, even, 0-1022 |
| `+0x016` | `01ff` | `01ff` | `0000` | crop `yEnd`, 0-511 |

`fixed=0000` at every offset, on both ports.

**The port register file is twenty-four bytes.** Six of 2048 offsets responded;
the other 4072 bytes do not decode at all. That is not "mostly unmapped" -- the
sweep also logs any offset whose *reset* value is nonzero, so a read-only
constant would not have been missed. It fits the DMA path already documented in
`docs/CAMERA_RESEARCH.md`: pixels leave through the FIFO at `0x10320000` under
CDMA peripheral `0x2`/`0x3`, so there was never going to be a buffer-address or
length register in this window.

**Four of the six are a crop window.** `+010`/`+014` take bits 1-9 (even values,
0-1022); `+012`/`+016` take bits 0-8 (0-511). A 640x480 sensor needs 0-639 and
0-479, and a YUV 4:2:2 crop has to begin and end on a chroma pair -- exactly an
even X. Four registers in `xStart, yStart, xEnd, yEnd` order is also the shape
of the only trimming call the `cam:u` service API exposes. Named accordingly;
still an inference, and flagged as one in the source.

**`0x10121000` is port 1's own register file**, now settled twice: the #301
alias probe failed (wrote `0x03fe` at CAM+010, the second window read `0x0000`)
and the second sweep answered the same six offsets with the same masks. The one
asymmetry is bit 4 of `+0x000` -- writable and set at reset on port 0, neither
readable nor writable on port 1. A bit that exists on one port and not the other
is not a format or size field, so it is left unnamed rather than guessed at.

### Why the *gap* in the mask is the lead

The sweep writes `0x5aa5` and `0xa55a`, which are exact bitwise complements, so
every bit is written both ways and `wmask = r1 ^ r2` is exact. There is no
pattern-dependent blind spot. A bit missing from `wmask` is therefore one of
exactly four things: unimplemented, write-only, read-only status, or
self-clearing.

A capture trigger is self-clearing **by construction** -- written 1, reads back
0. A frame-ready flag is read-only **by construction**. Neither can ever appear
in `wmask`, no matter how good the sweep is. So the six holes in `CAM+0x000` --
bits **0, 1, 5, 6, 7, 12**, mask `0x10e3` -- are the only place the missing
capture control can be, and they are the last bits in the block unaccounted for.

The thing that blocks this driver went from 4096 bytes to six bits. That is the
single most useful sentence in this section.

### What #302 ships to test it

`N3DS_CAM_CTRL_BIT_WALK`, enabled by `ctr_cam.start_probe=1`, which is now in
both DTS bootargs. For each dark bit of `CAM+000`, on each port: set it alone,
read it back, hold it 120 ms -- longer than one frame at the MT9V113's default
30 fps -- re-read the whole 24-byte file, restore, and report how many
camera-bus interrupts arrived while it was set.

The interrupt count is the point. Every other signal is ambiguous: a bit reading
back 0 might be unimplemented, or might be a trigger that has already fired. An
edge on `cam-bus0` is not ambiguous -- it means the receiver moved data, and
nothing this driver has ever done has caused one.

Those three lines had never been requested, for a stated reason: an edge-
triggered line with no status register to acknowledge is a screaming-interrupt
hazard. The hazard is real; the answer is a counter and a muzzle, not permanent
blindness. They are requested only for the length of the walk, counted,
`disable_irq_nosync()`-ed past 64 edges, re-enabled to balance the depth, and
freed before probe returns, so the driver's steady state is still "not
requested".

Bounded the same way the sweep is: `CAM+000` is restored within microseconds of
every write, and the #301 sweep already wrote all six of these bits *at once*
and the boot survived, so a single-bit walk adds no exposure the last boot did
not already take. The FIFO is deliberately **not** read -- an empty-FIFO read on
this bus can stall it, and an interrupt count cannot. Cost is about 1.5 s of
boot, against roughly 15 s for the aperture sweep, which is why it gets its own
module param instead of riding on `dump_regs`.

### Disassembling the `cam` sysmodule is blocked, and that is why the walk is first

`docs/CAMERA_RESEARCH.md` used to list the disassembly as step 1. It cannot be:
there is no `cam` binary anywhere in the tree. `content/code.bin` is the **nwm**
sysmodule, and `scratch/` holds only the DSP, nwm and PICA corpora. That route
needs a firmware dump that has not been made, so the bit walk -- 1.5 s of one
boot, and capable of returning a positive result rather than more map -- is now
first and the disassembly second.

### What shipped

Kernel **#302**. Built clean, `System.map` paired, all four new symbols present
(`ctr_cam_ctrl_bit_walk` `c0681a34`, `ctr_cam_start_probe` `c0681f58`,
`ctr_cam_irq_handler` `c053ef14`, `ctr_cam_file_snapshot` `c06816d8`). Both DTBs
rebuilt and verified to carry `ctr_cam.start_probe=1` in the packed bytes, not
merely in the source. `sdcard.zip` md5 **`bbe04b74626dc52df2c083c936ad60a1`**,
59,371,688 bytes, 186 files all verified byte-for-byte against staging, distinct
from all 25 archived zips. `verify_release_artifacts.sh`: ALL OK.
Hardware-unconfirmed until the next capture.

"""

anchor = "## 4. Known blocked\n"
assert anchor in doc, "section 4 anchor missing"
assert "3.14 Kernel #302" not in doc, "3.14 already present"
doc = doc.replace(anchor, section + anchor, 1)

# --------------------------------------------------------------- greps ---
old = """- **kmsg, tag `3ds-dsp`, new in #301 -- the line this whole session is for:**"""
new = """- **kmsg, tag `3ds-cam`, new in #302 -- the highest-value line in the capture:**
  `CAM+000 bit N: wrote XXXX read YYYY  irq bus0+A bus1+B y2r+C`, six of them
  per port. **Any nonzero `bus0+`/`bus1+` count is the capture path**: that bit
  started a transfer, and the camera stops being a research problem. Second best
  is `CAM+000 settled XXXX -> YYYY over 120 ms -- self-clearing`, which names a
  trigger even if no interrupt reached the GIC. Third is any
  `CAM+0NN changed AAAA -> BBBB while bit N was set` -- a register that moves on
  its own while a control bit is set is a status or a counter, and it is the
  frame-ready flag the block is missing. All-zero counts and no changes on all
  twelve bits is also a real answer: it means the receiver needs more than one
  bit set, and the next step is pairs, not a wider sweep.
- **kmsg, tag `3ds-cam`, new in #302:** `cam-bus0: N interrupts during the
  walk`. `(line muzzled at the storm limit)` on that line means the line was
  wedged asserted rather than pulsing -- still information, but treat the
  per-bit counts from that port as unreliable.
- **kmsg, tag `3ds-dsp`, new in #301 -- the line this whole session is for:**"""
assert old in doc, "grep anchor missing"
doc = doc.replace(old, new, 1)

assert doc != orig, "unchanged"
io.open(PATH, "w", encoding="utf-8", newline="\n").write(doc)
print("patched " + PATH)
