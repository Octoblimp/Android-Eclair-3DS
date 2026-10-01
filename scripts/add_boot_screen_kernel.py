"""Phase 5 (boot sequence), kernel-side changes:

1. Enable CONFIG_LOGO + CONFIG_LOGO_LINUX_CLUT224 so the (now
   Android-themed, see gen_android_boot_logo.py) boot logo actually
   gets compiled in and shown by fbcon -- confirmed via .config this
   was previously unset.
2. Add `quiet` to both DTS chosen/bootargs. Confirmed via boot logs
   that a huge amount of driver printk() (AR6002 diagnostics
   especially) currently reaches the physical console at default
   loglevel -- `quiet` raises console_loglevel to KERN_WARNING,
   hiding all that chatter (still in dmesg/the ring buffer, just not
   painted over the boot logo) while leaving real KERN_ERR+ crashes
   visible on-screen.
3. touch.c: the on-screen keyboard driver currently calls
   vkb_draw_bottom_lcd() unconditionally at probe time (confirmed by
   reading the file directly) -- draws the full keyboard grid on the
   bottom screen immediately at boot, before there's any reason to
   show it (autologin means no text entry is needed at boot). Removed
   so the bottom screen stays black (already cleared to black by the
   same init function) until something actually needs the keyboard.
   No other code path currently draws to the bottom screen (verified
   via grep across the tree).
"""
from a3ds_paths import A3DS_ROOT

LINUX = f"{A3DS_ROOT}/third_party/linux"
DEFCONFIG = f"{LINUX}/arch/arm/configs/nintendo3ds_defconfig"
CTR_DTS = f"{LINUX}/arch/arm/boot/dts/nintendo3ds_ctr.dts"
KTR_DTS = f"{LINUX}/arch/arm/boot/dts/nintendo3ds_ktr.dts"
TOUCH_C = f"{LINUX}/drivers/platform/nintendo3ds/tsc/touch.c"

# 1. defconfig
with open(DEFCONFIG) as f:
    defconfig = f.read()
assert "CONFIG_LOGO" not in defconfig
defconfig = defconfig.rstrip("\n") + "\nCONFIG_LOGO=y\nCONFIG_LOGO_LINUX_CLUT224=y\n"
with open(DEFCONFIG, "w") as f:
    f.write(defconfig)

# 2. bootargs in both DTS files
for path in (CTR_DTS, KTR_DTS):
    with open(path) as f:
        c = f.read()
    old = 'bootargs = "keep_bootcon fbcon=rotate:1 fbcon=font:VGA8x8";'
    assert c.count(old) == 1, f"{path}: bootargs line not found verbatim"
    new = 'bootargs = "keep_bootcon quiet vt.global_cursor_default=0 fbcon=rotate:1 fbcon=font:VGA8x8";'
    c = c.replace(old, new)
    with open(path, "w") as f:
        f.write(c)

# 3. touch.c: stop auto-drawing the vkb grid at probe time
with open(TOUCH_C) as f:
    c = f.read()
old = """	nintendo3ds_bottom_lcd_clear_screen(COLOR_BLACK);
	vkb_draw_bottom_lcd(vkb);

	return 0;
}"""
assert c.count(old) == 1, "vkb_init tail not found verbatim"
new = """	/* Boot sequence (Phase 5): leave the bottom screen black at
	 * init -- only clear it, don't draw the keyboard grid. Autologin
	 * means no text entry is needed at boot, and nothing else draws
	 * to this screen (verified via grep), so drawing the full grid
	 * unconditionally here used to paint over what should be a black
	 * screen until something actually needs keyboard input. Real
	 * show/hide-on-demand is future work; this just stops the
	 * always-on draw. */
	nintendo3ds_bottom_lcd_clear_screen(COLOR_BLACK);

	return 0;
}"""
c = c.replace(old, new)
with open(TOUCH_C, "w") as f:
    f.write(c)

print("OK")
