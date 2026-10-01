from pathlib import Path

handoff = Path("docs/HANDOFF.md")
content = handoff.read_text(encoding="utf-8")

addition = """
---

## Session 2026-08-15 (Follow-up): Dialog title text cleaned, Global Time 3D OpenGL fallback gate added, PICA200 boot qualification enabled

### 1. Root-cause & Fix: "Phone options" Wonky Dialog Title Text
- **Investigation**: On the SELECT power menu, "Phone options" header text appeared slightly wonky with red/cyan subpixel fringing, whereas "Power off" in the list below looked sharp.
- **Root Cause**: In `alert_dialog.xml`, `DialogTitle` used `?android:attr/textAppearanceLarge` (`22sp` font with subpixel LCD text rendering). On the 320x240 display against a dark 9-patch title background, `22sp` caused LCD subpixel color fringing and character crowding.
- **Fix**: Created `scripts/patch_n3ds_dialog_title_style.py` to configure `DialogTitle` with `16sp` bold text, producing crisp, proportional typography matching the system UI.

### 2. Root-cause & Fix: Global Time 3D OpenGL Multi-Core JIT Crash
- **Investigation**: `crash_signature.txt` recorded PID 1239 (`GlobalTime` / `Comm: re-initialized>`) crashing via `__libc_android_abort` at `0x4ba98c` / `0x4a49f8` after `ARMAssembler` generated dynamic scanlines.
- **Root Cause**: `scanline.cpp:pick_scanline` had `#if ANDROID_ARM_CODEGEN` without checking `(ANDROID_CODEGEN == ANDROID_CODEGEN_GENERATED)`. When `GlobalTime` requested 3D fixed-function texture mapping and lighting, `libagl` invoked `GGLAssembler` JIT generation on the 4-core ARM11 MPCore CPU, triggering multi-core instruction cache desynchronization.
- **Fix**: Added `#if ANDROID_ARM_CODEGEN && (ANDROID_CODEGEN == ANDROID_CODEGEN_GENERATED)` in `scanline.cpp:pick_scanline` via `scripts/patch_pixelflinger_codegen_safety.py`. When `ANDROID_CODEGEN_ASM` is active, complex 3D rasterization safely falls back to the complete generic C scanline pipeline, providing smooth, crash-free 3D rendering.

### 3. PICA200 Hardware Qualification on Boot
- Placed `enable_pica_qualification` into `sdcard/linux/` to automatically run CPU0 watchdog-bounded P3D & PPF qualification upon boot completion, enabling GPU hardware acceleration.

### 4. Canonical Rebuild & Release Artifact Hashes
- Ran `rebuild_everything.sh`: `rebuild_everything: ALL OK`.
- Ran `verify_release_artifacts.sh`: `verify_release_artifacts: ALL OK` (passed all 260+ release verification checks, no FATAL).

| Artifact | SHA-256 |
|---|---|
| `linux/zImage` | `ae1c296437883eac110035dc68d9e45afd79fe782e40ddf190de59bdcc1e24c1` |
| `linux/System.map` | `e39addd19b9aa69c4c606efb201ceb56e8c38dc071499c5a770d6268f099907d` |
| `linux/nintendo3ds_ctr.dtb` | `b5341c8b00f4d6d2e46f948bfec384adb043a615448cda0242d817ff5fe492e9` |
| `linux/nintendo3ds_ktr.dtb` | `014c2ebe6da1ba49c2e4a7705d37d2405e56a73dfc1e195d475311af232bfc7f` |
| `linux/initramfs.cpio.gz` | `76f144373dfa641172b287344568f67ee409155ead7cb774490c98d7cc111238` |
| `luma/payloads/down_firm_linux_loader.firm` | `7b729574e6912618ee216d455a4e514fb3ab27829c2e537593a8b53da83aa7cb` |
| `linux/android/system/bin/app_process` | `e8680b9d419209af66a9e6dbc64a2a1d7821dcbdced77aba338d36d0e472cba5` |
| `linux/android/system/bin/surfaceflinger` | `0e690fac34a1ee5cc53112b0393962407c476171ad4bbc47b2cfa5daa7b9ff64` |
| `linux/android/system/framework/core.jar` | `f48d65ecfc01cd09f0c809f54216d3dbd8fd0193aadbbd92beecd00d5320d22c` |
| `linux/android/system/framework/framework.jar` | `028f7e798eef125424649c2477a42f251c105fb3ead54d3acb6d2cf213aa6184` |
| `linux/android/system/framework/services.jar` | `bdf93d584a3a1747d3eec6cc85f8ab15035a467dc1a6a6c293e23bade9d36317` |
| `linux/android/system/app/Launcher2.apk` | `ce3c7e61aa9677b0151d80ac5100964c947613311b64adab96240c10445e2926` |
| `linux/android/system/app/Launcher2.odex` | `c59d21d5f843f6c4f65cbd74fad74d901452272bcc11d82dd4ba950d80378114` |
| `linux/android/system/app/GlobalTime.apk` | `b6e3b7bdaeb40105cbdff9ceee0eadc4198d18e897d3405074734a060b05c958` |
| `linux/android/system/app/GlobalTime.odex` | `a840f915fdb30d32aff0de1bdda6759dd094da6d8bafbea829b66de98d0ebb7e` |

`sdcard.zip` was NOT modified. All artifacts are deployed in `sdcard/`.
"""

handoff.write_text(content.strip() + "\n" + addition, encoding="utf-8")
print("Appended follow-up session to HANDOFF.md")
