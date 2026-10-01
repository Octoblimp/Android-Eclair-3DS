#!/usr/bin/env python3
"""Restore the hardware-proven fb1 scanout and deterministic touch mapping.

The experimental PDC1 A/B flip path left the physical bottom LCD black even
though Android reached Launcher.  Disable that path completely: one owner,
one framebuffer, no PDC register mutation.  Also remove the unsafe touch
"auto-calibration" which could lock after three poll samples from a single
press and stretch ordinary ADC jitter across the entire screen.
"""
from a3ds_paths import A3DS_ROOT

import re
from pathlib import Path


ROOT = Path(A3DS_ROOT)
LINUX = ROOT / "third_party/linux"
DTS = LINUX / "arch/arm/boot/dts/nintendo3ds.dtsi"
TOUCH = LINUX / "drivers/platform/nintendo3ds/tsc/touch.c"
GRALLOC = ROOT / "third_party/libhardware/modules/gralloc/framebuffer.cpp"
PRIV = ROOT / "third_party/libhardware/modules/gralloc/gralloc_priv.h"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# Remove both DT devices introduced solely for the failed flip experiment.
# With no lcd node ctr_lcd cannot probe or touch PDC1 control/timing registers.
dts = DTS.read_text()
dts, count_fb2 = re.subn(
    r"\n\t/\*\n\t \* Bottom screen buffer B.*?\n\t};\n(?=\n\tsoc: soc)",
    "\n",
    dts,
    count=1,
    flags=re.S,
)
dts, count_lcd = re.subn(
    r"\n\t\t/\* Bottom-screen framebuffer controller \(PDC1\).*?\n\t\t};\n(?=\n\t\ttimer:)",
    "\n",
    dts,
    count=1,
    flags=re.S,
)
if "display_bottom2:" in dts or "nintendo,3ds-lcd" in dts:
    raise SystemExit("display recovery: failed to remove experimental DT nodes")
DTS.write_text(dts)


gralloc = GRALLOC.read_text()

if "N3DS_SINGLE_SCANOUT_RECOVERY" not in gralloc:
    # Always transform into fb1, the last scanout path proven visible on hardware.
    gralloc, count_post = re.subn(
        r"\n    /\*\n     \* Blit into the panel buffer PDC1 is NOT scanning.*?\n    }\n\n    return 0;",
        "\n    /* N3DS_SINGLE_SCANOUT_RECOVERY: fb1 is the sole hardware-proven\n"
        "     * scanout owner. Never issue speculative PDC1 flips from userspace. */\n"
        "    n3ds_blit(m, m->n3ds_panel, (const uint16_t*)vaddr);\n\n"
        "    m->base.unlock(&m->base, buffer);\n\n"
        "    return 0;",
        gralloc,
        count=1,
        flags=re.S,
    )

    # Delete fb2 mapping and /dev/ctr_lcd opening in mapFrameBufferLocked().
    gralloc, count_map = re.subn(
        r"\n    /\* --- second panel buffer .*?\n    if \(module->n3ds_lcd_fd >= 0\)\n        LOGI\(\"gralloc: double-buffered bottom screen via /dev/ctr_lcd\"\);\n",
        "\n    LOGI(\"gralloc: single-buffered bottom screen on hardware-proven fb1\");\n",
        gralloc,
        count=1,
        flags=re.S,
    )
    if count_post != 1 or count_map != 1:
        raise SystemExit(
            f"display recovery: post matches={count_post}, map matches={count_map}"
        )

# Strip ioctl mirrors/includes and rewrite stale claims without disturbing the
# calibrated rotate/colour blit or the two private Android canvas buffers.
gralloc = re.sub(
    r"\n// Mirror of the kernel's ioctls.*?#define CTR_LCD_SEL_CURRENT_FB\t\(1 << 4\)\n",
    "\n",
    gralloc,
    count=1,
    flags=re.S,
)
gralloc = gralloc.replace(
    "The transform means a simple page-flip is not the whole story, but the\n"
    " * panel still double-buffers: PDC1 has two scanout buffers (FB_BOT_1 at\n"
    " * fb1, FB_BOT_2 at fb2). fb_post() blits into whichever PDC1 is NOT\n"
    " * currently scanning out, then toggles PDC1's framebuffer-select latch\n"
    " * through /dev/ctr_lcd and waits for the VBlank that applies it. So a\n"
    " * half-composed blit is never visible even though it is a CPU blit --\n"
    " * that is what finally killed the residual tearing artifact.",
    "The transform is posted into the hardware-proven fb1 scanout buffer.\n"
    " * Experimental PDC1 A/B flipping made the bottom LCD entirely black on\n"
    " * hardware, so framebuffer ownership remains single and deterministic."
)
gralloc = gralloc.replace(
    "// Two panel buffers: fb1 = FB_BOT_1, fb2 = FB_BOT_2.  Android's canvas\n"
    "// buffer is blitted into whichever PDC1 is NOT currently scanning out, the\n"
    "// framebuffer-select latch is flipped via /dev/ctr_lcd, and the VBlank\n"
    "// wait keeps us from writing into a buffer the panel is mid-frame on.\n",
    "// Two private RGB565 canvas buffers; both post to the sole fb1 scanout.\n"
)
gralloc = gralloc.replace(
    "    /* no PAGE_FLIP: PDC1's flip goes via /dev/ctr_lcd */",
    "    /* transformed CPU post into fb1; no hardware page flip */"
)
gralloc = gralloc.replace(
    "VBlank is now real (PDC1 IRQ, via /dev/ctr_lcd) but the composition",
    "The composition"
)
gralloc = gralloc.replace(
    " (double-buffered via /dev/ctr_lcd)",
    " (single fb1 scanout)"
)
gralloc = gralloc.replace(
    '         "%.1f x %.1f dpi%s",\n',
    '         "%.1f x %.1f dpi (single fb1 scanout)",\n',
)
gralloc = gralloc.replace(
    "         module->n3ds_y_offset, NUM_BUFFERS, module->xdpi, module->ydpi,\n"
    "         module->n3ds_lcd_fd >= 0 ? \" (single fb1 scanout)\" : \"\");",
    "         module->n3ds_y_offset, NUM_BUFFERS, module->xdpi, module->ydpi);",
)
if "CTR_LCD_IO_FLIP" in gralloc or "n3ds_panel2" in gralloc:
    raise SystemExit("display recovery: flip path survived in framebuffer.cpp")
GRALLOC.write_text(gralloc)

priv = PRIV.read_text()
priv = re.sub(r"\n    uint8_t\* n3ds_panel2.*\n", "\n", priv, count=1)
priv = re.sub(r"\n    int      n3ds_lcd_fd.*\n", "\n", priv, count=1)
priv = re.sub(r"\n    int      n3ds_cur_panel.*\n", "\n", priv, count=1)
PRIV.write_text(priv)


# Deterministic touch mapping. Runtime extrema are not calibration points:
# three samples can all come from one held contact, causing tiny jitter to be
# expanded to 320x240 and making taps jump into the status bar.
touch = TOUCH.read_text()
touch = touch.replace(
    "#define CAL_MIN_SAMPLES\t\t\t3\n"
    "#define CAL_MIN_SPREAD\t\t\t32\n"
    "#define CAL_EDGE_MARGIN_DIV\t\t8\n\n",
    "",
)
touch = touch.replace(
    "/* Runtime auto-calibration.  Every real panel has its own raw ADC range;\n"
    " * hardcoding a guessed one squashes the whole usable range into a corner\n"
    " * (e.g. every tap landing on the status bar).  We track the observed raw\n"
    " * min/max as the user touches around the panel and rescale those bounds to\n"
    " * the full logical surface, expanding only as new extremes are seen. */\n",
    "/* N3DS_FIXED_TOUCH_CALIBRATION: bounds derived from hardware captures.\n"
    " * Arbitrary runtime touches are not known calibration targets, so they\n"
    " * must never redefine the coordinate transform. */\n",
)
touch = touch.replace(
    "/* Fallback bounds used only until auto-calibration has seen enough spread.\n"
    " * Derived from captured on-device taps (raw X ~588-732, raw Y ~915-1305);\n"
    " * module parameters allow exact on-device values without rebuilding once\n"
    " * raw diagnostics are captured. */\n"
    "static unsigned int touch_min_x = 480;\n"
    "static unsigned int touch_max_x = 840;\n"
    "static unsigned int touch_min_y = 800;\n"
    "static unsigned int touch_max_y = 1450;\n",
    "/* N3DS_FULL_ADC_TOUCH_RANGE: the unconditional FIFO hardware run proved\n"
    " * that real contacts span most of the 12-bit ADC domain (X 509..3627,\n"
    " * Y 1021..3366).  The earlier narrow bounds came from a different FIFO\n"
    " * interpretation and clamped nearly every contact to (319,239), which\n"
    " * WindowManager's 180-degree display transform turned into the status\n"
    " * bar corner.  Keep the conservative inset from the original driver\n"
    " * until factory HWCAL is available. */\n"
    "static unsigned int touch_min_x = 256;\n"
    "static unsigned int touch_max_x = 3840;\n"
    "static unsigned int touch_min_y = 256;\n"
    "static unsigned int touch_max_y = 3840;\n",
)
if ("N3DS_FULL_ADC_TOUCH_RANGE" not in touch and
        "static unsigned int touch_min_x = 256;" in touch and
        "static unsigned int touch_max_x = 3840;" in touch and
        "static unsigned int touch_min_y = 256;" in touch and
        "static unsigned int touch_max_y = 3840;" in touch):
    touch = touch.replace(
        "static unsigned int touch_min_x = 256;\n",
        "/* N3DS_FULL_ADC_TOUCH_RANGE */\n"
        "static unsigned int touch_min_x = 256;\n",
        1,
    )
touch = re.sub(
    r"\n\t/\* Auto-calibration state \*/.*?\n\tu16 cal_max_y;\n",
    "\n",
    touch,
    count=1,
    flags=re.S,
)
touch = re.sub(
    r"\n/\* Feed a raw sample into the auto-calibrator.*?\n}\n(?=\nstatic void touch_input_poll)",
    "\n",
    touch,
    count=1,
    flags=re.S,
)
touch = touch.replace(
    "\tunsigned int low_x;\n\tunsigned int high_x;\n"
    "\tunsigned int low_y;\n\tunsigned int high_y;\n",
    "",
)
touch = re.sub(
    r"\n\t\ttouch_cal_update\(touch_hid, raw_touch_x, raw_touch_y\);.*?"
    r"\n\t\ttouch_cal_bounds\(touch_hid, &low_x, &high_x, &low_y, &high_y\);\n",
    "\n",
    touch,
    count=1,
    flags=re.S,
)
touch = touch.replace(
    "screen_touch_x = touch_scale(raw_touch_x, low_x, high_x,\n"
    "\t\t\tTOUCH_MAX_X);\n"
    "\t\tscreen_touch_y = touch_scale(raw_touch_y, low_y, high_y,\n"
    "\t\t\tTOUCH_MAX_Y);",
    "screen_touch_x = touch_scale(raw_touch_x, touch_min_x, touch_max_x,\n"
    "\t\t\tTOUCH_MAX_X);\n"
    "\t\tscreen_touch_y = touch_scale(raw_touch_y, touch_min_y, touch_max_y,\n"
    "\t\t\tTOUCH_MAX_Y);",
)
if "touch_cal_update" in touch or "cal_done" in touch:
    raise SystemExit("touch recovery: unsafe runtime calibration survived")
if "N3DS_FIXED_TOUCH_CALIBRATION" not in touch:
    raise SystemExit("touch recovery: deterministic calibration marker missing")
if "N3DS_FULL_ADC_TOUCH_RANGE" not in touch:
    raise SystemExit("touch recovery: full-range calibration marker missing")
TOUCH.write_text(touch)

print("patch_n3ds_display_touch_recovery: visible fb1 scanout; fixed touch transform")
