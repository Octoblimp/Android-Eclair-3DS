# Nintendo 3DS camera block — research notes

Compiled 2026-09-11 for Part 6 (camera bring-up + app shell). Every address,
IRQ and i2c address below was read off 3dbrew directly in this session; where
3dbrew has nothing, this file says so instead of guessing.

## The single most important finding

**There is no public register-level documentation for the 3DS CAM block.**
3dbrew's `Camera Registers` page is a 27-byte stub — an empty page, not a page
that is merely thin. GBATEK's `gbatek-3ds-cameras.htm` returns 404. Every
other block we have driven on this console (PDN, I2C, DSP, PXI) had at least a
register table to work from. The camera does not.

Consequence for planning: a working V4L2 *capture* path cannot be derived from
public documentation. It requires either disassembling the `cam` sysmodule or
hardware poking. What follows is everything that *is* documented, which is
enough to build the clock/power/i2c/IRQ scaffolding honestly and to know
exactly where the undocumented gap begins.

## Memory map

| Block | Address | Notes |
|---|---|---|
| CAM registers | `0x10120000` | mirror at `0x10121000`. **Not** `0x10122000` — that is WiFi SDIO. |
| Y2R (YUV to RGB converter) | `0x10102000` | see table below |
| DMA FIFO mirror region | `0x10300000` – `0x10340000` | 3dbrew: "Needed for DMA" |
| Camera port 0 capture FIFO | `0x10320000` | derived, see below |
| Camera port 1 capture FIFO | `0x10321000` | derived, see below |
| `PDN_CAMERA_CNT` | `0x10141224` | width 1, **bit 0 = clock enable** |

`PDN_CAMERA_CNT` sits inside the address range of the existing `pdn` syscon
node (`syscon@10141000`, `reg = <0x10141000 0x1000>`). That is not a conflict:
`drivers/mfd/syscon.c` maps with `devm_ioremap` and never calls
`request_mem_region`, so the byte can be handed to the camera node as its own
`reg` entry -- which is exactly what the existing `dsp@10203000` node already
does for `0x10141230`. Follow that proven idiom. What must never happen is a
`request_mem_region()` on the range.

### Y2R registers (documented)

| Name | Address | Width |
|---|---|---|
| `Y2R_PARAMS` | `0x10102000` | 4 |
| `Y2R_LINEW` | `0x10102004` | 2 |
| `Y2R_LINES` | `0x10102006` | 2 |
| `Y2R_COEFFICIENTS` | `0x10102010` | 0x10 |
| `Y2R_ALPHA` | `0x10102020` | 2 |
| `Y2R_???` | `0x10102100` | 0x20 |
| `Y2R_INPUT_Y` | `0x10302000` | 0x80? |
| `Y2R_INPUT_U` | `0x10302080` | 0x80? |
| `Y2R_INPUT_V` | `0x10302100` | 0x80? |
| `Y2R_INPUT_X?` | `0x10302180` | 0x80? |
| `Y2R_OUTPUT_RGB` | `0x10302200` | 0x80? |

`Y2R_PARAMS` bits: 0-3 InputFormat, 8-9 OutputFormat, 10-11 Rotation,
12 BlockAlignment, 30 transfer-end interrupt, 31 enable/busy. The rest are
marked `?` upstream.

Note the split: the Y2R *control* registers are at `0x10102000` but its data
FIFOs are at `0x10302000`, inside the DMA mirror region. That is the same
pattern the camera FIFO follows, and is why the mirror region matters.

### The camera FIFO address is derivable, not a guess

3dbrew's IO Registers table places the FIFO region at `0x10300000`-`0x10340000`
and it maps device-for-device onto `0x10100000`-`0x10140000`: the offset within
the region is the offset of the device's own control window. Two documented
pairs pin this down independently -- HASH's control block at `0x10101000` has
its FIFO at `0x10301000`, and Y2R's control block at `0x10102000` has its input
and output FIFOs at `0x10302000` (both spelled out in the table above, both
read straight off 3dbrew, neither inferred).

Applying the same rule to the camera gives **`0x10320000` for the CAM window at
`0x10120000`**, and **`0x10321000` for the second window at `0x10121000`**. The
second address is only meaningful if that window is a real second register file
rather than an alias -- see the mirror question below, which kernel #301
answers on hardware.

This matters because it is the whole of a PIO capture path. With no CDMA
driver, reading pixels means reading the FIFO word by word from the CPU, and
until now the FIFO address itself was unknown. It is not unknown any more.
What is still missing is the *control* half: which register starts a transfer
and which bit says a frame is ready. Do not read a FIFO before that is known;
a read of an empty FIFO on this bus can stall it.

## Measured register map — the sweep result, kernel #301

No part of this table is documented anywhere. All of it was measured on
hardware by writing `0x5aa5` and `0xa55a` to every 16-bit offset of each
aperture, restoring it, and taking `wmask = r1 ^ r2` (the writable, readable
bits) and `fixed = r1 & ~wmask` (what the rest reads as). The two patterns are
bitwise complements, so `wmask` is exact for every bit — there is no
pattern-dependent blind spot, which is what makes the *gaps* meaningful.

| Offset | CAM `wmask` | CAM1 `wmask` | reset | Reading |
|---|---|---|---|---|
| `+0x000` | `ef1c` | `ef0c` | `0010` / `0000` | control |
| `+0x006` | `003f` | `003f` | `0000` | 6-bit field, unidentified |
| `+0x010` | `03fe` | `03fe` | `0000` | crop `xStart`, even, 0–1022 |
| `+0x012` | `01ff` | `01ff` | `0000` | crop `yStart`, 0–511 |
| `+0x014` | `03fe` | `03fe` | `0000` | crop `xEnd`, even, 0–1022 |
| `+0x016` | `01ff` | `01ff` | `0000` | crop `yEnd`, 0–511 |

`fixed = 0000` at every offset, on both ports.

**The port register file is 24 bytes.** Six of 2048 offsets responded and the
other 4072 bytes read zero and took no bits. That is not "mostly unmapped" —
the sweep logs any offset with a nonzero reset value too, so a read-only
constant would have shown up. It is consistent with the DMA path below:
pixels leave through the FIFO at `0x10320000` under CDMA peripheral `0x2`/`0x3`,
so no buffer-address or length register is expected in this window at all.

**Two ports, one design.** `0x10121000` answered the same six offsets with the
same masks, which together with the alias probe (which it failed — see above)
settles the mirror question: it is camera port 1's own register file. The one
difference is bit 4 of `+0x000`: writable and set at reset on port 0, neither
readable nor writable on port 1. A bit that exists on one port and not the
other is not a format or size field; it is left unnamed.

**The crop window is a fit, not a guess.** `+0x010`/`+0x014` take bits 1–9
(even values, 0–1022) and `+0x012`/`+0x016` take bits 0–8 (0–511). A 640x480
sensor needs 0–639 and 0–479, and a YUV 4:2:2 crop must start and end on a
chroma pair — exactly an even X. Four registers, in `xStart, yStart, xEnd,
yEnd` order, is also the shape of the only trimming call the `cam:u` service
API exposes. Still an inference; marked as one in the driver.

### What the sweep structurally cannot see, and why that is the lead

A bit missing from `wmask` is one of exactly four things: not implemented,
write-only, read-only status, or self-clearing.

A capture trigger is self-clearing **by construction** — written 1, reads back
0. A frame-ready flag is read-only **by construction**. Neither can ever appear
in `wmask`, no matter how good the sweep is.

So the holes in `CAM+0x000` — bits **0, 1, 5, 6, 7, 12**, mask `0x10e3` — are
the only place the missing capture control can be, and they are the last bits
in the block unaccounted for. The search space for the one thing blocking this
driver went from 4096 bytes to six bits.

Kernel #302 tests them (`N3DS_CAM_CTRL_BIT_WALK`, `ctr_cam.start_probe=1`):
set each dark bit alone, hold it 120 ms — longer than one frame at the
MT9V113's default 30 fps — and count camera-bus interrupts while it is set.
The interrupt is the point. Every other signal is ambiguous (a bit reading 0
may be unimplemented or may be a trigger that already fired), but an edge on
cam-bus0 means the receiver moved data, and nothing this driver has ever done
has caused one. The FIFO is still not read: an empty-FIFO read can stall the
bus, and an interrupt count cannot.

## Interrupts

3dbrew's ARM11 interrupt table (these are raw ARM11 IRQ numbers; a
`GIC_SPI` number in the DT is this value minus `0x20`):

| IRQ | GIC_SPI | Meaning |
|---|---|---|
| `0x48` | `0x28` | Camera Bus 0 |
| `0x49` | `0x29` | Camera Bus 1 (left eye) |
| `0x4B` | `0x2B` | Y2R conversion finished |

All three are edge-triggered, 1-N.

Incidental cross-check from the same table: `0x4A` is the DSP general
interrupt, i.e. `GIC_SPI 0x2A`. That is exactly what `nintendo3ds.dtsi`
already carries on the `dsp@10203000` node, so the DSP interrupt number is
confirmed correct and is **not** a candidate cause of the DSP silence.

## I2C sensor addresses — found

From 3dbrew's `I2C Registers` device table. These are **write** addresses;
the 7-bit address Linux wants is the value shifted right by one.

| Device id | Bus | Write addr | 7-bit | Service | Description |
|---|---|---|---|---|---|
| 1 | 1 | `0x7a` | **`0x3d`** | `i2c::CAM` | Camera0 (same dev-addr as DSi cam0) |
| 2 | 1 | `0x78` | **`0x3c`** | `i2c::CAM` | Camera1 (same dev-addr as DSi cam1) |
| 4 | 2 | `0x78` | `0x3c` | `i2c::CAM` | unidentified |

"Bus 1" is `I2C1_DATA` at `0x10161000` — which is the `i2c1` node already
present and probing in `nintendo3ds.dtsi` with no children. So the two camera
sensors sit on that bus at `reg = <0x3d>` and `reg = <0x3c>`. `ctr_cam.c`
reaches them through a `nintendo,i2c-bus = <&i2c1>` phandle and a zero-length
write probe rather than declaring child nodes, because declaring a child node
asserts a `compatible` -- a part number we do not have.

3dbrew notes these are the same device addresses as the DSi cameras. The DSi
sensors are Aptina/Micron MT9V113-class parts. That was a lead when this file
was written; **kernel #300 confirmed it on hardware**. Both sensors ACK, and
both return `0x2280` from `R0x0000`, which is the MT9V113 part ID. The access
shape is confirmed too: 16-bit register address and 16-bit data, big-endian,
one `i2c_transfer` with a write message followed by a read message.

One practical consequence from the same capture: an i2c transaction on this bus
costs roughly **600 ms**. Three register reads took 1.87 s. That is not a bug
to chase -- it is the bus -- but it does mean a full page-0 sensor dump would
add over a minute to every boot, which is why `ctr_cam_sensor_dump()` reads
eight registers and not two hundred.

The bus-2 controller (`0x10144000`) also lists a `i2c::CAM` device; its role
is undocumented.

## DMA path

The Corelink CDMA peripheral-ID table names the camera explicitly:

| ID | Module | Description |
|---|---|---|
| `0x2` | camera (cam) | Camera Port 1 |
| `0x3` | camera (cam) | Camera Port 2 |
| `0x6` | camera (y2r) | SetSendingY |
| `0x7` | camera (y2r) | SetSendingU |
| `0x8` | camera (y2r) | SetSendingV |
| `0x9` | camera (y2r) | SetSendingYUYV |
| `0xA` | camera (y2r) | SetReceiving |

So the intended data flow is: sensor → CAM port FIFO → CDMA (peripheral 0x2 /
0x3) → memory, and separately memory → CDMA (0x6-0x9) → Y2R → CDMA (0xA) →
memory as RGB. We have no CDMA driver. For a first pass, PIO out of the
camera FIFO is the only option, and even that needs the undocumented CAM
register layout to know when a frame is ready.

## What is still unknown

1. **The capture control bits of `CAM+0x000`** — narrowed, not resolved. The
   register *layout* is no longer unknown: it was measured, it is 24 bytes
   wide, and four of its six registers are a crop window (see the measured
   map above). What is still missing is the start bit and the frame-ready
   flag, and both are necessarily invisible to a write-readback sweep, which
   places them in the six dark bits of `CAM+0x000`. This is still the
   blocker; it is a six-bit blocker instead of a 4096-byte one.
2. ~~The exact camera FIFO offset~~ — resolved by derivation, above.
3. ~~The sensor part number~~ — resolved on hardware: MT9V113, ID `0x2280`.
   The MT9V113 register set is a published Aptina part and can be worked from
   directly; what is not published is how the 3DS CAM block is driven.
4. `CAMERA Services` — 3dbrew's HLE service page for `cam:u` is also empty,
   so the service-level semantics that would hint at the register semantics
   are not available either.
5. MCU-side power/LED gating. `MCUHWC:SetCameraLEDPattern` exists as a name;
   MCU device 3 (bus 2, `0x4a`) is documented register-by-register but no
   camera-power register is called out in it.

## Where to look next, in order of expected yield

1. **Run the control-bit walk on hardware** (`ctr_cam.start_probe=1`) and read
   the interrupt counts. This is now first, ahead of disassembly, because it
   costs 1.5 s of one boot and can return a positive result rather than more
   map. See the measured-map section above for what it is testing and why the
   six bits it tries are the only candidates.
2. **Disassemble the `cam` sysmodule** from a retail firmware dump. Blocked as
   of 2026-09-12: there is no cam binary in the tree. `content/code.bin` is
   the **nwm** sysmodule, and `scratch/` holds only the DSP, nwm and PICA
   corpora. This needs a firmware dump that has not been made yet, so it
   cannot be the next step even though it is the most complete one.
3. ~~Azahar / Citra's `core/hw/camera`~~ — **checked, and it does not exist.**
   This entry was written by analogy with the DSP, where Azahar's HLE was
   decisive. The analogy does not hold. Azahar and Citra implement `cam:u` at
   the *service* level and hand frames to a host webcam or a still image; they
   never touch `0x10120000`, so there are no register names to read out of
   them. Corgi3DS, the low-level emulator that *would* model registers, has no
   camera or Y2R implementation at all. Strike both as sources.

   The general lesson, worth carrying: an HLE emulator documents the service
   ABI, not the hardware. It was decisive for the DSP only because the DSP's
   ARM11-side protocol *is* a service-level protocol. The camera's is not.
4. libctru's `cam.h` / `y2r.h` — gives the *service* API shape (resolutions,
   formats, port enums), which constrains what the registers must express.

## Rules `ctr_cam.c` follows (and any extension must keep)

- Print a `dev_err()` before **every** early return in probe. The DSP driver
  cost a full session precisely because probe could fail silently.
- Take `PDN_CAMERA_CNT` as a plain `reg` entry, the way `dsp@10203000`
  takes `0x10141230`. Never `request_mem_region()` a range another node owns.
- Report honestly. A driver that enables the clock, finds the sensors on i2c
  and says "no documented capture path" is a correct driver for this state of
  knowledge. A driver that pretends to stream is not.
