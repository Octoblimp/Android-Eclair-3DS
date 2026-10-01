# Scope

Android3DS runs real **AOSP Android 2.0 (Eclair)** bare-metal on the **New
Nintendo 3DS XL**, in place of Nintendo's Horizon OS. It is not a Horizon-hosted
app, not an emulator, and not a look-alike of Android: it is the actual Eclair
codebase (bionic, Dalvik, frameworks, stock apps) on real hardware, on a
`linux-3ds` kernel.

The README's **What works in Alpha 1** section is the current feature list.
This file covers the hard limits: read it before assuming a feature works.

## Hard constraints

- **No GPU acceleration.** Rendering is software only: libagl and
  PixelFlinger, with ashmem gralloc. A fail-closed Linux PICA200
  ownership/qualification driver exists, but it is deliberately boot-inert and
  accepts only a FINALIZE test stream. It is not a rendering driver.
  - Probe-time GPU access and unconditional PICA-DMA gralloc caused a physical
    hard lock. Both are forbidden.
  - Before any GPU path becomes the default, all of these are needed: physical
    qualification, handle-based DMA relocation, PSC/PPF IRQ ownership,
    EGL/GLES 1.1, and gralloc import.
  - The public devkitPro stack is not a Linux driver. libctru submits through
    Horizon's privileged `gsp::Gpu` service, and citro3d exposes a PICA-native
    API rather than OpenGL ES. Do not add a direct-MMIO shortcut.
  - See `docs/PICA200_RESEARCH.md`.
  - Eclair predates GPU-mandatory compositing, so the OS and stock apps work
    without a GPU. The GL call sites removed during bring-up (for example
    `Canvas(GL)` and `ViewRoot`'s EGL path) were removed because no driver backs
    them yet. That is not a permanent decision.
- **No sleep.** Eclair asks for suspend-to-RAM on every screen timeout, and
  there is no resume path on this hardware. The kernel refuses the request.
- **One display.** Eclair's WindowManager and SurfaceFlinger assume a single
  screen, so Android runs on the bottom screen and the top screen is the
  kernel console. Dual-screen apps or two-task multitasking would need
  framework patches that do not exist.
- **No full-system emulator.** Citra emulates Horizon, not a chainloaded Linux
  kernel. Userspace pieces are tested under `qemu-arm` before they ship.
  Everything involving the kernel or the hardware needs a real console with
  Luma3DS-class custom firmware.
- **Wi-Fi is 2.4 GHz only** (the AR6014 chip), with open or
  WPA/WPA2-Personal networks. The supplicant is built without EAP or WPA3.
- **No cellular radio.** "Mobile data" is 3DSTelco: calls and texts over Wi-Fi
  through an HTTPS server. See `docs/TELCO_VOIP_PROTOCOL.md`.
- **Cameras:** the outer (back) and inner (front) sensors are supported. The
  second outer sensor (the 3D pair) is not used.
- **Audio** goes through CSND, not the Teak DSP.

## What this is not

- Not compatible with apps built for later Android versions. This really is
  Android 2.0, with its app compatibility ceiling (API level 5).
- Not a certified or supported Nintendo product. It needs custom firmware
  (Luma3DS-class) already installed on the console.
