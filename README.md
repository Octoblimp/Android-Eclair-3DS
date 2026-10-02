# Android3DS

Real Android 2.0 (AOSP Eclair) running bare-metal on the New Nintendo 3DS XL.

This is not an emulator and not a Horizon app. Luma3DS chainloads a Linux
kernel, and Android's own init, Dalvik, SurfaceFlinger and stock apps run on
top of it. The Android UI is on the bottom (touch) screen. The top screen
shows the kernel console.

The kernel, ARM9 firmware and FIRM loader come from the
[linux-3ds](https://github.com/linux-3ds) project. Everything Android-side is
AOSP Eclair, ported and patched for the console.

**Current release: Alpha 1.** Settings > About phone > Build number reads
`Android3DS Alpha 1 (a1)`. It boots, joins Wi-Fi, browses the web, and makes
calls and sends texts over Wi-Fi. It is still an alpha: expect slow spots and
the occasional crash.

## What works in Alpha 1

| Area | Status |
| --- | --- |
| Boot | Luma3DS chainload (hold D-pad DOWN at power-on), the Eclair boot animation and boot sound, then the Launcher2 home screen |
| Display | Bottom screen 320x240 for Android, GPU accelerated. Top screen is the kernel console |
| Input | Touchscreen, D-pad, circle pad (works as a trackball), A/B/X/Y, START, SELECT and HOME. LatinIME on-screen keyboard with its dictionary |
| Wi-Fi | 2.4 GHz networks, open or WPA/WPA2-Personal. Networks are remembered |
| Calls and texts | 3DSTelco "mobile data": a phone number, calls in both directions, texts, missed-call notifications, call log and voicemail, all over Wi-Fi |
| Web | The WebKit Browser loads real pages. It has tabs (up to 4) and a Go-to dialog for typing URLs. The circle pad pans the page |
| Audio | Speaker output (CSND) and microphone capture |
| Camera | Outer (back) and inner (front) cameras in the Camera app |
| Time | Automatic time and time zone over the network (Settings > Date & time > Automatic) |
| Settings | Every screen opens: Wi-Fi, 3DSTelco Mobile Data, Wireless ADB, Applications, Developer options, SD card & phone storage, Language & keyboard, Date & time, and About phone, including Status. Settings and app data are saved to the SD card and survive a reboot |
| Apps | Launcher2, Browser, Camera, Phone dialer (contacts and recents), Messaging, Settings, Dev Tools, Global Time, plus diagnostics: MicTest, TouchDiagnostic, GPU-Z, N3DSBenchmark, N3DSSpeedTest |
| Debugging | ADB over Wi-Fi (a root shell) |
| Power | Hold SELECT for the power menu. Hold START for 3 seconds to power off |

### Not working or not planned yet

- **No sleep mode.** The console never suspends. Power it off when you are done.
- **No cellular radio.** The 3DS has none. "Mobile data" here means 3DSTelco
  over Wi-Fi (see below).
- **Wi-Fi limits.** 5 GHz, WPA3-only and enterprise (802.1X) networks are not
  supported.
- **Android 2.0 apps only** (API level 5). There is no Google Play / Market.
- **Single screen.** No 3D, and no dual-screen apps: the top screen is console
  only.
- **The SD card stays mounted.** There is no USB storage mode and no unmount
  button. Power off before you take the card out.

## Controls

| 3DS | Android |
| --- | --- |
| Touchscreen | Touch |
| A | Select / OK |
| Y | Back |
| B or X | Recent apps (hold an app to close it; the last tile closes all) |
| HOME | Home |
| START (tap) | Menu (the options menu of the current app) |
| START (hold 3 s) | Power off |
| SELECT (hold) | Power menu |
| D-pad | Move focus |
| Circle pad | Trackball: move focus, scroll and pan pages |

## Installing

You need:

- a Nintendo 3DS with [Luma3DS](https://github.com/LumaTeam/Luma3DS)
  custom firmware installed;
- an SD card with a few hundred MB free;
- a 2.4 GHz Wi-Fi network, for anything online.

Steps:

1. Download `android3ds_a1.zip` from the
   [Releases page](https://github.com/Octoblimp/Android-Eclair-3DS/releases),
   or build it yourself (see Building). The release zip is ready to use: it
   already has the firmware the console needs, so you can skip the Firmware
   section.
2. Extract it to the **root** of the SD card. Its `linux/` and
   `luma/payloads/` folders merge with what is already there. Do not delete
   your existing `luma/` folder.
3. Put the card back. Hold **D-pad DOWN** while you press POWER. Luma3DS
   starts `luma/payloads/down_firm_linux_loader.firm`, which boots Android3DS.
4. To go back to the normal 3DS system, power off (hold START) and turn the
   console on without holding anything.

To update, extract the newer release zip over the old one the same way.

## Setting up Wi-Fi

1. Open **Settings** (from the app drawer on the home screen).
2. Tap **Wi-Fi settings**.
3. Tick **Wi-Fi** to turn the radio on. Wait a few seconds for the network
   list.
4. Tap your network. Type the password with the on-screen keyboard, then tap
   **Connect**.
5. The network shows **Connected**. It is remembered and rejoins on the next
   boot.

Tips:

- Only 2.4 GHz networks show up. If your router combines both bands under one
  name, the 3DS uses the 2.4 GHz side.
- For a hidden network, use **Add Wi-Fi network** at the bottom of the list.
- If the list stays empty, untick **Wi-Fi**, wait a moment, and tick it again.
- The 3DS's Wi-Fi MAC address is in **Settings > About phone > Status**, and
  also under START (Menu) > **Advanced** on the Wi-Fi screen.

## Setting up mobile data (3DSTelco)

The 3DS has no cellular modem. In Android3DS, "mobile data" is **3DSTelco**. It
gives the console a phone number, and carries its calls and texts over Wi-Fi
through an HTTPS server. The built-in server is `https://3dstelco.divergen.io`.
You can point the 3DS at your own server instead.

1. **Connect to Wi-Fi first** (above). Mobile Data refuses to turn on without it.
2. Note the 3DS's **Wi-Fi MAC address** from Settings > About phone > Status.
3. On the 3DSTelco website, register that MAC address. The site gives you a
   **one-time provisioning code**.
4. On the 3DS, open **Settings > 3DSTelco Mobile Data**.
5. Optional: tap **3DSTelco HTTPS endpoint** only if you use a different server.
   It must be an `https://` address. Changing it clears the old number, so
   enroll again afterwards.
6. Tick **Enable Mobile Data**.
7. Tap **Enroll this 3DS**, type the code, and tap OK. Dashes and spaces are
   ignored, and the code is never saved.
8. After a few seconds, **Phone number** shows your number and
   **Service status** reads **Online over Wi-Fi**.

Then:

- **Calls:** open the Phone dialer. Calls use the speaker.
- **Texts:** use Messaging.
- **Who you can reach:**
  - other 3DS consoles have 3- or 4-digit numbers;
  - web accounts have 10-digit numbers;
  - texts can also go to 6-digit service numbers.
- **Missed calls and voicemail** show in the dialer's Recents. Voicemail is
  downloaded once, then plays offline.

If **Service status** says the call audio relay is offline, texts still work,
but calls will have no audio until the server's relay is back.

## Wireless ADB

1. Open **Settings > Wireless ADB** and tick **Enable wireless ADB**.
2. The screen shows the connection address. From a PC on the same network,
   run:

   ```bash
   adb connect <address>:5555
   ```

This is a **root shell** for anyone on your network. Turn it off when you are
not using it.

## Easter egg

Open **Settings > About phone** and tap **Firmware version** three times
quickly.

## Building

The build runs on Linux or WSL2 (Ubuntu). The large source trees must live on
a Linux filesystem: the kernel tree does not survive a Windows checkout. The
scripts default to `~/android3ds`, so clone there (or set `ANDROID3DS_ROOT`):

```bash
git clone https://github.com/Octoblimp/Android-Eclair-3DS.git ~/android3ds
```

This repository carries the port's own code and the vendored trees (WebKit,
ICU, ...). The Linux kernel, the linux-3ds firmware and loader, Buildroot and
the AOSP projects it modifies come from upstream, plus the changes in
`patches/`. This fetches each one at the exact upstream commit and applies its
patch:

```bash
scripts/fetch_third_party.sh
```

The kernel patch comes with the `.config` the release was built with
(`patches/linux.config`), which the script installs.

Building from a fresh clone has not been tested end to end yet. Expect to
adapt paths and packages on your machine.

### Firmware

The console needs some of Nintendo's firmware, which is not in this
repository. **The release zip already includes it.** Only builders need to
dump their own. Everything goes into
`third_party/buildroot/board/nintendo3ds/rootfs_overlay/usr/lib/firmware/`:

| File | Needed for | Where it comes from |
| --- | --- | --- |
| `ath6k/AR6002/nwm/database.bin`, `main_type4.bin`, `stub_code.bin`, `stub_data.bin` | Wi-Fi (required) | Your console's NWM system module |
| `3ds/dspfirm.cdc` | Nothing yet (optional) | DSP1 homebrew |
| `regulatory.db`, `regulatory.db.p7s` | Wi-Fi channel rules | wireless-regdb, not Nintendo's |

**Wi-Fi firmware.** The 3DS Wi-Fi chip (an Atheros AR6014) boots from four
blobs inside the NWM system module, title `0004013000002D02`. Dump it with
[GodMode9](https://github.com/d0k3/GodMode9):

1. Start GodMode9. In the usual Luma3DS setup, hold START while powering on.
2. Open `[1:] SYSNAND CTRNAND` > `title` > `00040130` > `00002d02` > `content`.
3. Press A on the `.app` file there (its name depends on your system
   version, for example `0000001e.app`). Choose **NCCH image options... >
   Extract .code**, or **Decrypt file (SD output)**. Menu wording varies a
   little between GodMode9 versions. GodMode9 writes the result to `gm9/out/`
   on the SD card.
4. Copy that file to the build machine and run:

   ```bash
   scripts/extract_n3ds_firmware.py path/to/the/file
   ```

The script takes a decrypted `.app`, or its `.code` (compressed or not). It
finds the four blobs through the module's own pointer table and checks each
one by SHA-256 against the firmware this port was tested with (NWM v11264).
Nothing is written unless all four match. Then it puts them into the overlay.

**DSP firmware (optional).** `dspfirm.cdc` is the 3DS DSP firmware. If you
followed the usual Luma3DS setup guide, you already have it at
`sd:/3ds/dspfirm.cdc`. Otherwise run [DSP1](https://github.com/zoogie/DSP1)
once on the console to create it. Android3DS plays sound through CSND, not the
DSP. Without this file the kernel just logs "audio unavailable" for the DSP
driver. To include it anyway:

```bash
scripts/extract_n3ds_firmware.py path/to/the/file --dsp path/to/dspfirm.cdc
```

**Regulatory database.** `regulatory.db` and `regulatory.db.p7s` come from
[wireless-regdb](https://git.kernel.org/pub/scm/linux/kernel/git/wens/wireless-regdb.git).
On Ubuntu, install the `wireless-regdb` package and copy both files from
`/lib/firmware/`.

The release gate (`scripts/verify_release_artifacts.sh`) refuses a build
without the Wi-Fi blobs, and says which file is missing.

### Toolchain and release steps

Setup:

1. Toolchain: Bootlin `armv6-eabihf--glibc--stable-2025.08-1`
   ([toolchains.bootlin.com](https://toolchains.bootlin.com/releases_armv6-eabihf.html)),
   extracted to `toolchain/` in the checkout.
2. The bare-metal ARM9/ARM11 firmware uses the distribution's
   `gcc-arm-none-eabi` package.
3. Several tests run ARM binaries under a static `qemu-arm-static`, kept in
   `toolchain/qemu/`.
4. Machine-specific settings go in `~/.config/android3ds/env`. This file is
   plain shell assignments and is never committed. See `scripts/a3ds_env.sh`
   for the variables:

   ```sh
   # Optional: a second checkout that holds sdcard/ (for example on a Windows drive).
   ANDROID3DS_WIN="/mnt/c/path/to/Android3DS"
   # Optional: only for unattended runs where sudo must not prompt.
   ANDROID3DS_SUDO_PASSWORD=...
   ```

A release is assembled like this. The build scripts for each component
(kernel, framework jars, apps, native stack) are in `scripts/`.

```sh
scripts/sync_android_to_sdcard.sh   # stage /system, /etc, /usr into sdcard/
scripts/build_dexpreopt_qemu.sh     # pre-optimise the framework jars
scripts/prebake_all_app_odex.sh     # pre-optimise the apps
scripts/sync_android_to_sdcard.sh   # stage again with the optimised files
scripts/verify_release_artifacts.sh # release gate: refuses stale or wrong artifacts
scripts/build_sdcard_zip.sh         # pack sdcard/ into sdcard.zip
```

After any framework jar change, re-run the two pre-optimise steps. Otherwise
the system stalls at boot rebuilding them on the console.

[`docs/BUILD.md`](docs/BUILD.md) has the original boot-chain recipe and the
build environment gotchas.

## Repository layout

```
content/      Android-side sources: Settings additions, the stock-app overlays (Phone, Mms, ...), extra apps
native/       native daemons and tools
hal/          hardware HALs (lights, sensors, copybit, input)
scripts/      build, deploy and test scripts, and the release gates
patches/      changes to the upstream trees (kernel, linux-3ds, Buildroot, AOSP), with MANIFEST.tsv
third_party/  upstream sources: vendored here (WebKit, ICU, ...) or fetched by fetch_third_party.sh
sdcard/       build output, the SD card tree the release zip is packed from (only templates are tracked)
tools/        PC-side 3DSTelco diagnostics
docs/         scope, build notes, and research (PICA200 GPU, cameras, 3DSTelco protocol)
```

`patches/` holds plain text diffs. Binary files they leave out are listed in
`patches/BINARIES.tsv`. Some are Nintendo firmware (see Firmware). The rest are
build outputs and media that the build scripts regenerate, and that the
release zip also carries.

## Credits

- [linux-3ds](https://github.com/linux-3ds): the Linux kernel, arm9linuxfw and
  firm_linux_loader this port boots on.
- The Android Open Source Project: Android 2.0 Eclair.
- [Luma3DS](https://github.com/LumaTeam/Luma3DS): the custom firmware that
  chainloads it.
- libn3ds and GBATEK, for the 3DS hardware details.
- [Bootlin](https://toolchains.bootlin.com/): the cross toolchain.

## License

Android3DS's own code is under the [Apache License 2.0](LICENSE), like AOSP
itself, except where a file says otherwise. Third-party code keeps its
upstream license, and each patch in `patches/` carries the license of the
project it changes. The Linux kernel and its patch are GPL-2.0. See
[NOTICE](NOTICE).

This repository contains no Nintendo firmware and no system-module dumps.

Android3DS is not affiliated with or endorsed by Nintendo or Google. Android
is a trademark of Google LLC. Nintendo 3DS is a trademark of Nintendo. Use at
your own risk.
