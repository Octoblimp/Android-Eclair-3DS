#!/usr/bin/env python3
"""Make bootanimation termination finite and keep the TSC FIFO observable.

Two hardware-log findings are handled here:

* Eclair's movie player checks exitPending() only inside its innermost frame
  loop.  Android3DS' boot animation contains an infinite ``p 0`` part, so a
  SIGTERM merely breaks one pass and the outer repeat loop starts it again.
* The historical 3DS touch driver treats bank 67h register 26h bit 1 as a
  definitive "no data" indication.  That undocumented gate can remain set
  while the FIFO is usable, suppressing every Android touch event.  Poll the
  FIFO unconditionally and retain the status value only for diagnostics.

The patch is deliberately idempotent and fails if the expected source shape
is absent, so rebuild_everything cannot silently publish an old behavior.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
BOOT = ROOT / "third_party/frameworks/base/cmds/bootanimation/BootAnimation.cpp"
TOUCH = ROOT / "third_party/linux/drivers/platform/nintendo3ds/tsc/touch.c"


boot = BOOT.read_text()
if "N3DS_BOOTANIM_EXIT_ALL_LOOPS" not in boot:
    old = """    /* Play the declared parts.  The frame loop is the only place exitPending()
     * is checked, so when the deadline alarm fires the animation halts on
     * whatever frame is showing and that still frame stays up until init
     * sends SIGTERM (ctl.stop bootanim). */
    for (int i=0 ; i<(int)pcount ; i++) {
"""
    new = """    /* N3DS_BOOTANIM_EXIT_ALL_LOOPS: a part count of zero repeats forever.
     * Test the Thread exit flag in every containing loop so SIGALRM/SIGTERM
     * actually unwinds movie(), destroys DisplayHardware, closes fb1, and
     * lets SurfaceFlinger own the panel. */
    for (int i=0 ; i<(int)pcount && !exitPending() ; i++) {
"""
    if boot.count(old) != 1:
        raise SystemExit("bootanimation: expected play-loop preamble once")
    boot = boot.replace(old, new, 1)
    old = "        for (int r=0 ; !part.count || r<part.count ; r++) {\n"
    new = "        for (int r=0 ; (!part.count || r<part.count) && !exitPending() ; r++) {\n"
    if boot.count(old) != 1:
        raise SystemExit("bootanimation: expected repeat loop once")
    boot = boot.replace(old, new, 1)
    old = "            for (int j=0 ; j<(int)fcount ; j++) {\n"
    new = "            for (int j=0 ; j<(int)fcount && !exitPending() ; j++) {\n"
    if boot.count(old) < 1:
        raise SystemExit("bootanimation: expected frame loop")
    # Only the first occurrence after the playback marker is the playback
    # loop; later loops release decoded textures.
    marker = boot.index("N3DS_BOOTANIM_EXIT_ALL_LOOPS")
    pos = boot.index(old, marker)
    boot = boot[:pos] + new + boot[pos + len(old):]
    old = "            usleep(part.pause * ns2us(frameDuration));\n"
    new = "            if (!exitPending() && part.pause > 0)\n                usleep(part.pause * ns2us(frameDuration));\n"
    if boot.count(old) != 1:
        raise SystemExit("bootanimation: expected part pause once")
    boot = boot.replace(old, new, 1)

if "N3DS_BOOTANIM_EXIT_CONFIRMED" not in boot:
    old = """    freeTexture(&scratch);
    return false;
"""
    new = """    /* N3DS_BOOTANIM_EXIT_CONFIRMED */
    if (exitPending())
        LOGI("movie: exit request unwound every playback loop");
    freeTexture(&scratch);
    return false;
"""
    if boot.count(old) != 1:
        raise SystemExit("bootanimation: expected movie epilogue once")
    boot = boot.replace(old, new, 1)

if ("N3DS_BOOTANIM_EXIT_ALL_LOOPS" not in boot or
        "N3DS_BOOTANIM_EXIT_CONFIRMED" not in boot):
    raise SystemExit("bootanimation: termination marker absent")
BOOT.write_text(boot)


touch = TOUCH.read_text()
if "N3DS_TOUCH_FIFO_UNCONDITIONAL" not in touch:
    old = """static int touch_request_data(struct regmap *map, u8 *buffer)
{
	int err;
	unsigned int reg;

	/* acknowledge touch? */
	err = regmap_read(map, TOUCH_REG(0x26), &reg);
	if (err) return err;

	/* no new data available */
	if (reg & BIT(1))
		return -ENODATA;

	return regmap_bulk_read(map, TOUCH_FIFO_REG, buffer, 0x34);
}
"""
    new = """/* N3DS_TOUCH_FIFO_UNCONDITIONAL: 67h:26h bit 1 is not a safe
 * availability gate on retail hardware.  Reading it is still useful as an
 * acknowledgement/status transaction, but a set bit must not discard the
 * complete touch/circle-pad FIFO. */
static int touch_request_data(struct regmap *map, u8 *buffer,
			      unsigned int *status26)
{
	int err;

	err = regmap_read(map, TOUCH_REG(0x26), status26);
	if (err)
		return err;

	return regmap_bulk_read(map, TOUCH_FIFO_REG, buffer, 0x34);
}
"""
    if touch.count(old) != 1:
        raise SystemExit("touch: expected request-data implementation once")
    touch = touch.replace(old, new, 1)
    old = "\tbool sync = false;\n\tint err;\n\n\terr = touch_request_data(touch_hid->map, raw_data);\n\tif (err == -ENODATA)\n\t\treturn;\n\n"
    new = "\tbool sync = false;\n\tunsigned int status26;\n\tint err;\n\n\terr = touch_request_data(touch_hid->map, raw_data, &status26);\n\n"
    if touch.count(old) != 1:
        raise SystemExit("touch: expected poll request call once")
    touch = touch.replace(old, new, 1)
    old = "\tbool pendown;\n\n};\n"
    new = "\tbool pendown;\n\tunsigned int poll_count;\n\n};\n"
    if touch.count(old) != 1:
        raise SystemExit("touch: expected state struct once")
    touch = touch.replace(old, new, 1)
    old = "\tpendown = touch_down_samples != 0;\n\n\tif (pendown) {\n"
    new = """	pendown = touch_down_samples != 0;

	/* One compact sample every ~5 seconds makes a failed hardware test
	 * diagnosable even when no pen transition is recognized. */
	if (!(touch_hid->poll_count++ % 150))
		pr_info("fifo status26=%02x pen=%u x0=%04x y0=%04x med=(%u,%u)\\n",
			status26 & 0xff, pendown, (raw_data[0] << 8) | raw_data[1],
			(raw_data[10] << 8) | raw_data[11],
			touch_median(x_samples), touch_median(y_samples));

	if (pendown) {
"""
    if touch.count(old) != 1:
        raise SystemExit("touch: expected pen decision once")
    touch = touch.replace(old, new, 1)

if "N3DS_TOUCH_FIFO_UNCONDITIONAL" not in touch:
    raise SystemExit("touch: FIFO marker absent")
TOUCH.write_text(touch)

print("patch_n3ds_bootanim_touch: finite boot animation; unconditional touch FIFO")
