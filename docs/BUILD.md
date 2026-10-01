# Boot-chain build recipe

This is how the boot chain is built: the kernel, the ARM9 firmware and the
FIRM loader. It started as the project's first phase, which reproduced the
upstream `linux-3ds` boot chain unmodified. For the full Android release
flow (staging, pre-optimisation, release gates, `sdcard.zip`), see the
README's **Building** section.

Status: this chain boots on a real New 3DS XL. The framebuffer console,
touchscreen, circle pad, D-pad, MCU/battery and the SD-backed initramfs all
came up on the first try.

## Environment gotchas (read first)

- **The kernel and buildroot trees cannot live on Windows NTFS**, not even
  mounted through WSL (`/mnt/c/...`). Cloning `linux-3ds/linux` onto NTFS
  fails outright, because the tree contains
  `drivers/gpu/drm/nouveau/nvkm/subdev/i2c/aux.c` and `aux` is a reserved
  device name on Windows. Clone both `third_party/linux` and
  `third_party/buildroot` inside WSL2's native filesystem
  (`~/android3ds/...`), never under `/mnt/c/...`.
- **WSL2 imports the Windows `PATH` by default, and buildroot refuses to run
  when `PATH` contains spaces.** It does, through the `C:\Program Files\...`
  entries. Either add this to `/etc/wsl.conf` and restart WSL:
  ```
  [interop]
  appendWindowsPath = false
  ```
  or export a clean `PATH` per build command
  (`/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` plus the
  toolchain's `bin/`). The build scripts do the latter, so either works.
- **devkitARM is not used.** Invoked directly on Windows for
  `arm9linuxfw`/`firm_linux_loader`, it failed with a sandbox-related
  "Cannot create temporary file in C:\WINDOWS\" error. Those are small
  bare-metal builds, so they are built inside WSL2 with the native
  `gcc-arm-none-eabi` package instead.
- `firm_linux_loader`'s Makefiles do not set `CC` themselves. Build with
  `make CC=arm-none-eabi-gcc` (the top-level `Makefile` builds both `arm9/`
  and `arm11/`).
- `firmtool`, which produces the final `.firm`, is not on PyPI under that
  name. Install it from source:
  `pip3 install --break-system-packages --user git+https://github.com/TuxSH/firmtool.git`,
  and put `~/.local/bin` on `PATH`.

## Toolchains

- **Kernel and buildroot (ARM11, glibc userland):** the Bootlin prebuilt
  `armv6-eabihf--glibc--stable-2025.08-1` toolchain
  (https://toolchains.bootlin.com/releases_armv6-eabihf.html), extracted to
  `toolchain/` in the checkout. It provides `arm-buildroot-linux-gnueabihf-*`
  and a convenience `arm-linux-*` prefix. The kernel is built with
  `CROSS_COMPILE=arm-linux-`.
- **Android userspace** (bionic, Dalvik, frameworks, apps) uses the same GCC
  with `-nostdinc`/`-nostdlib` and bionic's headers. The original 2009
  `arm-eabi-4.4.0` prebuilt does not run on current hosts.
- **arm9linuxfw and firm_linux_loader (bare-metal ARM9/ARM11):** the
  distribution's `gcc-arm-none-eabi` package. Neither devkitARM nor the
  Bootlin toolchain targets bare-metal `arm-none-eabi` correctly here.

## What gets built (in `third_party/`)

1. **Kernel:** `scripts/build_kernel.sh` (`make ARCH=arm CROSS_COMPILE=arm-linux-`
   in `third_party/linux`). Output: `arch/arm/boot/zImage` and the
   `nintendo3ds_{ktr,ctr}.dtb` device trees (New 3DS / Old 3DS).
2. **initramfs:** `scripts/build_minimal_initramfs.sh`. It holds Android's
   `init` and `init.rc`, a busybox early userland, and the Wi-Fi driver,
   firmware and supplicant. `/system`, `/etc` and `/usr` are bind-mounted
   from the SD card.
3. **arm9linuxfw:** `make` in `third_party/arm9linuxfw`. Output: `arm9linuxfw.bin`.
4. **firm_linux_loader:** `make CC=arm-none-eabi-gcc` in
   `third_party/firm_linux_loader`. `scripts/build_firm_loader.sh` deploys it
   as the single payload `luma/payloads/down_firm_linux_loader.firm`.

## SD card layout

The loader expects these paths. They are hardcoded in
`firm_linux_loader/common/linux_config.h`:

```
sd:/linux/zImage
sd:/linux/initramfs.cpio.gz
sd:/linux/nintendo3ds_ktr.dtb    <- picked automatically on New 3DS
sd:/linux/nintendo3ds_ctr.dtb    <- picked automatically on Old 3DS / 2DS
sd:/linux/arm9linuxfw.bin
sd:/luma/payloads/down_firm_linux_loader.firm   <- the only loader payload
```

The loader detects New 3DS or Old 3DS at runtime and picks the matching
`.dtb`. Android itself lives under `sd:/linux/android/`. `sdcard/` in this
repo is that exact tree, and `sdcard.zip` is packed from it.

## SD card writes

The upstream `arm9linuxfw` virtio-blk SD device (`source/vdev/sdcard.c`)
implemented only the read path, and advertised `VIRTIO_BLK_F_RO`. The
lower-level `sdmmc_sdcard_writesectors()` it could call already existed.
The patch:

- removes the read-only flag;
- implements the write-descriptor path, tracking header versus payload per
  job, because a write sends a second `HOST_TO_VDEV` descriptor.

This works below the filesystem, at the raw-sector level, so a bug here
could hit any sector on the card. Back up your SD card before trying new
builds.

## Getting diagnostics off the device

- Boot and crash logs land in `sd:/linux/`: for example `boot_progress.txt`,
  `logcat.txt` and `crash_pstore.txt`. Power off with a START hold so the
  FAT volume is flushed, then read the card on a PC.
- Once Wi-Fi is up, Settings > Wireless ADB gives an `adb` root shell over
  the network.

## Testing on hardware

1. Copy `sdcard/` (or extract `sdcard.zip`) onto the root of the 3DS's SD
   card, merging with the existing `luma/` folder.
2. Power on holding **D-pad DOWN**. Luma3DS launches
   `luma/payloads/down_firm_linux_loader.firm` directly: the `down_` prefix
   is Luma's convention for binding a payload to a button.
3. The top screen shows the kernel console. Android comes up on the bottom
   screen.
