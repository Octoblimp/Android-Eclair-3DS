# PICA200 Linux and Android bring-up research

Status: 2026-08-28 (build #234 P3D completion repair). This document
distinguishes compiled work from behavior that still needs physical 3DS proof.

## Build #234 evidence-driven completion repair

The fresh build #233 hardware capture creates `/dev/pica200` and reaches the
first deferred FINALIZE completion. Attempt 1 returns `-EIO` in 33 ms, while
attempts 2 and 3 consume the full 500 ms and return `-ETIMEDOUT`. A CPU0 stack
appears at the first attempt's IRQ-warning deadline. Source correlation makes
the boundary deterministic: the level-high P3D handler did not acknowledge
`GPUREG_IRQ_ACK`, returned `IRQ_NONE` after clearing its software arm flag, and
sampled CMDBUF_JUMP0 immediately even though the interrupt had already fired.

Build #234 follows the current direct-hardware libn3ds contract. It writes zero
to `GPUREG_IRQ_ACK`, flushes that posted write, treats a fresh P3D IRQ followed
by the documented external P3D busy bit becoming idle as completion, and never
returns `IRQ_NONE` for the owned P3D line. It performs one delayed qualification
attempt; a failure quarantines PICA until reboot instead of retrying an IRQ line
that may be compromised. It does not gate the display-shared GPU clock. The
CPU0 watchdog is armed before inherited-state MMIO, and completion diagnostics
record IRQ, busy, jump, error, and stage values.

The focused source/idempotence regression, affected kernel build, Windows/WSL
staging parity, and independent release verifier pass. This is software proof
of the repaired contract—not physical proof that P3D now qualifies, and not
proof of Android hardware rendering. The deployed Android renderer remains
libagl/PixelFlinger with ashmem gralloc until the physical P3D/PPF gates and a
real hardware EGL/compositor path are completed.

## Crash diagnosis and recovery policy

The hard-lock photograph contains no kernel panic. It stops during early
Android init around 38 seconds among successful `setprop` commands. The FAT
warning is a consequence of the preceding unclean shutdown. The root
`boot_progress.txt` and `logcat.txt` predate this lock, so there is no crash
record to symbolize.

Two unsafe activation decisions existed in that image:

1. PICA initialization and command submission ran from kernel probe. Software
   fallback could not protect boot if that probe locked ARM11 first.
2. gralloc replaced its known-good ashmem pool with PICA coherent DMA as soon
   as `/dev/pica200` opened, although no hardware EGL/GLES renderer consumed
   that allocation.

Both unsafe probe-time decisions are removed. Probe itself performs no PICA
register access and does not enable P3D IRQ. Build #234 schedules one
watchdog-bounded qualification attempt three seconds after probe; the boot
diagnostic remains read-only and gralloc remains on ashmem. Qualification is
still the only path that can establish hardware ownership.

Qualification is protected by the ARM11 MPCore watchdog described by the
existing `twd-watchdog@17e00620` device-tree node. Arm/disarm runs on CPU0 to
avoid the wrong-CPU defect for which upstream removed its old generic MPcore
watchdog driver. A five-second reset request surrounds the risky MMIO/IRQ
window. The 3DS external reset wiring still needs physical proof, so this is
a containment measure, not a claimed guarantee.

On an ordinary timeout the driver does not attempt an undocumented GPU
"reset." It stops submitting, marks PICA wedged, and requires a reboot.
Cycling register `0x10400004` is a clock change shared with display hardware,
not a documented PICA reset sequence.

## Confirmed hardware contract

- ARM11 PICA aperture: physical `0x10400000`; Horizon maps the same block at
  user VA `0x1ef00000`.
- Busy register: external offset `0x34`; PSC0 bit 26, PSC1 bit 27, PPF bit 30,
  and P3D bit 31.
- Command-list registers: size at `0x18e0` in eight-byte units, physical
  address at `0x18e8` shifted right three, and start at `0x18f0` bit 0.
- Lists are parameter/header pairs and must be 16-byte aligned. Internal
  register `0x0010` (`GPUREG_FINALIZE`) terminates processing and raises P3D.
  libctru uses a second FINALIZE when required for alignment; qualification
  follows that convention.
- The command page must be PICA-visible physical memory. On this port that is
  coherent FCRAM in `0x20000000..0x2fffffff`, not a CPU virtual address.
- Hardware interrupt IDs are PSC0 `0x28`, PSC1 `0x29`, PPF `0x2c`, and P3D
  `0x2d`, represented as GIC SPI offsets `0x08`, `0x09`, `0x0c`, and `0x0d`.
  Nintendo's ARM11 configuration describes them as level-high. Current
  qualification lazily enables only P3D; transfer IRQ ownership remains.
- Current libctru first-user initialization writes internal registers
  `0x1000=0`, `0x1080=0x12345678`, `0x10c0=0xfffffff0`, `0x10d0=1`, and
  `0x1914=1`; enables components with external `0x4=0x70100`; clears PSC/PPF
  fields; and writes `0x50=0x22221200` plus masked `0x54=0xff2`. Linux leaves
  PDC0/PDC1 timing and scanout untouched.

Primary references:

- [3dbrew GPU external registers](https://www.3dbrew.org/wiki/GPU/External_Registers)
- [3dbrew GPU internal registers](https://www.3dbrew.org/wiki/GPU/Internal_Registers)
- [3dbrew ARM11 interrupt map](https://www.3dbrew.org/wiki/ARM11_Interrupts)
- [libctru GSP initialization](https://github.com/devkitPro/libctru/blob/master/libctru/source/services/gspgpu.c)
- [libctru command lists](https://github.com/devkitPro/libctru/blob/master/libctru/source/gpu/gpu.c)
- [ARM11 MPCore manual](https://documentation-service.arm.com/static/5e8e1cd9fd977155116a4a7a)

## Current qualification stages

1. Arm CPU0's private watchdog and lazily register P3D IRQ `0x2d`.
2. Read the hardware ID and apply documented internal initialization.
3. Enable documented GPU clocks and clear PSC/PPF/initial status fields.
4. Allocate one coherent page and validate its physical FCRAM address.
5. Acknowledge any stale level-high P3D source, submit only two FINALIZE pairs,
   wait at most 500 ms for a newly observed and acknowledged P3D IRQ, then wait
   a bounded 10 ms for the external P3D busy bit to become idle. CMDBUF_JUMP0
   is retained as diagnostics, not misused as the IRQ acknowledgement.
6. Mark PICA qualified only after every check, then disarm the watchdog. A
   command timeout quarantines the device until reboot.

The default `pica200_smoketest` remains status-only. The kernel makes the one
deferred boot attempt; `--qualify` is still required for an explicit userspace
request and cannot bypass reboot-only quarantine.

## Command security before Android clients

Structural parsing is insufficient. Texture addresses (`0x85..0x8a`, `0x95`,
`0x9d`), depth/color targets (`0x11c`, `0x11d`), attribute base (`0x200`),
index offsets (`0x227`), and nested command registers can make PICA access
physical memory. Retained state also makes relative offsets dangerous.

P3D command submission still accepts only FINALIZE. ABI v3 now copies the
validated stream into kernel-private coherent memory before execution, closing
the mmap time-of-check/time-of-use race. A rendering submit ABI must still
carry a relocation table naming an owned DMA handle, byte range, command-word offset,
address encoding, and access direction. The kernel must reject overflow,
freed handles, out-of-range texture/draw/index extents, and unrelocated
address words. Context changes must restore complete PICA state.

## ABI v3 owned PPF transfer

ABI v3 adds `CTR_PICA_IOC_TRANSFER`. Both endpoints must be live DMA handles
owned by the exclusive file context; the kernel validates offsets, calculated
image extents, documented format combinations, dimensions, and alignment, then
constructs every PPF address/register value itself. Raw copy, scaling, unknown
flags, same-buffer aliasing, and unsafe conversion combinations are rejected.

PPF IRQ `0x2c` is enabled lazily after P3D qualification. Transfers use a
bounded wait, CPU0 watchdog coverage, level interrupt acknowledgement, and the
same reboot-only quarantine on timeout. `pica200_smoketest --qualify` now runs
an owned 64x16 RGBA8 transfer and emits `PICA200_PPF PASS` only after IRQ
completion.

PSC0/PSC1 remain unexposed: documented memory fills require VRAM, while the
current owned allocator deliberately supplies coherent FCRAM. Treating those
address spaces as interchangeable would risk another hardware lock.

## GLES 1.1 / EGL / gralloc route

Khronos reported PICA200 as GLES 1.1 conformant, but the homebrew libraries
are not Linux Android drivers. citro3d is a permissively licensed PICA-native
state library and is the best low-level command reference. picaGL demonstrates
fixed-function translation and has powered real 3DS ports, but its repository
contains no license grant, so its code must not be copied here.

- [Khronos conformance announcement](https://www.khronos.org/news/permalink/dmp-announces-opengl-es-1.1-conformant-pica-200-adopted-by-nintendo)
- [devkitPro citro3d](https://github.com/devkitPro/citro3d)
- [picaGL design reference](https://github.com/masterfeizz/picaGL)
- [Nintendo OpenGL reverse-engineering notes](https://docs.mikage.app/Nintendo_OpenGL/)

Remaining implementation order:

1. Extend ABI v3 with P3D relocation tables, complete texture/vertex/index
   extent validation, and context restore. The current explicit context policy
   remains one privileged broker/open file.
2. Add PSC0/PSC1 alongside a real owned-VRAM allocator. PPF owned-buffer
   conversion, IRQ completion, watchdog timeout, and quarantine are compiled;
   physical qualification is pending.
3. A Linux command library based on documented registers and permissively
   licensed citro3d interfaces: shaders, vertices, indices, textures, and
   tiled color/depth targets.
4. A from-scratch GLES 1.1 translator for matrices, arrays, lighting,
   materials, texture combiners, alpha/blend, depth/stencil, scissor,
   viewport, clears, and drawing. Picasso compiles trusted shaders at build.
5. EGL display/config/context/surface integration beneath Eclair's restored
   JSR-239 bridge. Hardware-context failure creates a libagl context instead.
6. gralloc uses GPU render targets only after qualification. PPF converts the
   tiled target to rotated linear bottom-screen scanout; CPU post remains the
   fallback.
7. Promote PICA to default only after physical clear/triangle/texture tests,
   repeated context lifecycle, Android UI/app rendering, timeout injection,
   watchdog recovery, and fallback reboot all pass.

Until those gates pass, claiming hardware rendering is primary would recreate
the failure mode shown in the photograph.
