#!/usr/bin/env python3
"""Replace touch input, fix Launcher teardown, and enable stable KTR SMP/L2."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
LINUX = ROOT / "third_party/linux"
TOUCH = LINUX / "drivers/platform/nintendo3ds/tsc/touch.c"
DTSI = LINUX / "arch/arm/boot/dts/nintendo3ds.dtsi"
KTR = LINUX / "arch/arm/boot/dts/nintendo3ds_ktr.dts"
MACHINE = LINUX / "arch/arm/mach-ctr/main_ctr.c"
LAUNCHER = ROOT / "third_party/launcher2/src/com/android/launcher2/AllAppsView.java"
LOADER = ROOT / "third_party/firm_linux_loader/arm11/source"


TOUCH.write_text(r'''// SPDX-License-Identifier: GPL-2.0-or-later
/* Android-oriented Nintendo 3DS resistive touchscreen driver.
 *
 * N3DS_ANDROID_DIRECT_TOUCH
 * N3DS_MEDIAN_TOUCH_SAMPLES
 * N3DS_TOUCH_CALIBRATION
 * N3DS_FIXED_TOUCH_CALIBRATION
 * N3DS_FULL_ADC_TOUCH_RANGE
 * N3DS_TOUCH_FIFO_UNCONDITIONAL
 *
 * This intentionally replaces the inherited combined touchscreen/circle-pad
 * input device. Android Eclair classifies an EV_ABS+EV_REL hybrid poorly and
 * a direct touchscreen must never also behave like a relative mouse. This
 * driver owns only the panel contact. Circle-pad support belongs in a separate
 * input device/driver.
 */

#define DRIVER_NAME "android3ds-touch"
#define pr_fmt(fmt) DRIVER_NAME ": " fmt

#include <linux/input.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/regmap.h>

#define POLL_INTERVAL_MS 16
#define SAMPLE_COUNT 5
#define ADC_MASK 0x0fff
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 240
#define TOUCH_REG(reg) ((0x67 << 7) | (reg))
#define TOUCH_FIFO_REG ((0xFB << 7) | 0x01)

/* Conservative endpoints from the complete retail-hardware capture. Factory
 * HWCAL can override these as module parameters when its storage is exposed. */
static unsigned int raw_min_x = 256;
static unsigned int raw_max_x = 3840;
static unsigned int raw_min_y = 256;
static unsigned int raw_max_y = 3840;
module_param(raw_min_x, uint, 0644);
module_param(raw_max_x, uint, 0644);
module_param(raw_min_y, uint, 0644);
module_param(raw_max_y, uint, 0644);

struct android3ds_touch {
	struct regmap *map;
	struct input_dev *input;
	bool down;
	u16 last_x;
	u16 last_y;
	unsigned int polls;
};

static int android3ds_touch_hw_init(struct regmap *map)
{
	static const struct reg_sequence init[] = {
		REG_SEQ(TOUCH_REG(0x24), 0x98, 10),
		REG_SEQ(TOUCH_REG(0x26), 0x00, 10),
		REG_SEQ(TOUCH_REG(0x25), 0x43, 10),
		REG_SEQ(TOUCH_REG(0x24), 0x18, 10),
		REG_SEQ(TOUCH_REG(0x17), 0x43, 10),
		REG_SEQ(TOUCH_REG(0x19), 0x69, 10),
		REG_SEQ(TOUCH_REG(0x1b), 0x80, 10),
		REG_SEQ(TOUCH_REG(0x27), 0x11, 10),
		REG_SEQ(TOUCH_REG(0x26), 0xec, 10),
		REG_SEQ(TOUCH_REG(0x24), 0x18, 10),
		REG_SEQ(TOUCH_REG(0x25), 0x53, 10),
	};
	int ret;

	ret = regmap_multi_reg_write(map, init, ARRAY_SIZE(init));
	if (ret)
		return ret;
	ret = regmap_update_bits(map, TOUCH_REG(0x26), 0x80, 0x80);
	if (ret)
		return ret;
	ret = regmap_update_bits(map, TOUCH_REG(0x24), 0x80, 0x00);
	if (ret)
		return ret;
	return regmap_update_bits(map, TOUCH_REG(0x25), 0x3c, 0x10);
}

static u16 median5(u16 *v)
{
	int i, j;
	for (i = 1; i < SAMPLE_COUNT; i++) {
		u16 n = v[i];
		for (j = i; j && v[j - 1] > n; j--)
			v[j] = v[j - 1];
		v[j] = n;
	}
	return v[2];
}

static u16 scale_axis(u16 raw, unsigned int low, unsigned int high,
		      unsigned int pixels)
{
	if (high <= low || raw <= low)
		return 0;
	if (raw >= high)
		return pixels - 1;
	return ((u32)(raw - low) * (pixels - 1)) / (high - low);
}

static void android3ds_touch_poll(struct input_dev *input)
{
	struct android3ds_touch *ts = input_get_drvdata(input);
	u8 fifo[0x34] __aligned(sizeof(u32));
	u16 xs[SAMPLE_COUNT], ys[SAMPLE_COUNT], raw_x, raw_y, x, y;
	unsigned int status;
	bool down;
	int i, ret;

	ret = regmap_read(ts->map, TOUCH_REG(0x26), &status);
	if (!ret)
		ret = regmap_bulk_read(ts->map, TOUCH_FIFO_REG, fifo, sizeof(fifo));
	if (ret)
		return;

	down = !(fifo[0] & BIT(4));
	for (i = 0; i < SAMPLE_COUNT; i++) {
		xs[i] = (((u16)fifo[i * 2] << 8) | fifo[i * 2 + 1]) & ADC_MASK;
		ys[i] = (((u16)fifo[10 + i * 2] << 8) | fifo[11 + i * 2]) & ADC_MASK;
	}
	raw_x = median5(xs);
	raw_y = median5(ys);

	if (!(ts->polls++ % 300))
		pr_info("probe status=%02x pen=%u raw=(%u,%u) logical=(%u,%u)\n",
			status & 0xff, down, raw_x, raw_y, ts->last_x, ts->last_y);

	if (down) {
		x = scale_axis(raw_x, raw_min_x, raw_max_x, SCREEN_WIDTH);
		y = scale_axis(raw_y, raw_min_y, raw_max_y, SCREEN_HEIGHT);
		ts->last_x = x;
		ts->last_y = y;
		input_report_abs(input, ABS_X, x);
		input_report_abs(input, ABS_Y, y);
		input_report_abs(input, ABS_PRESSURE, 1);
		input_report_key(input, BTN_TOUCH, 1);
		input_sync(input);
		if (!ts->down)
			pr_info("DOWN raw=(%u,%u) logical=(%u,%u)\n", raw_x, raw_y, x, y);
	} else if (ts->down) {
		input_report_abs(input, ABS_PRESSURE, 0);
		input_report_key(input, BTN_TOUCH, 0);
		input_sync(input);
		pr_info("UP logical=(%u,%u)\n", ts->last_x, ts->last_y);
	}
	ts->down = down;
}

static int android3ds_touch_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct android3ds_touch *ts;
	struct input_dev *input;
	int ret;

	ts = devm_kzalloc(dev, sizeof(*ts), GFP_KERNEL);
	input = devm_input_allocate_device(dev);
	if (!ts || !input)
		return -ENOMEM;
	ts->map = dev_get_regmap(dev->parent, NULL);
	if (!ts->map)
		return -ENODEV;

	input->name = "Android3DS Direct Touchscreen";
	input->phys = DRIVER_NAME "/input0";
	input->id.bustype = BUS_HOST;
	input->dev.parent = dev;
	input_set_drvdata(input, ts);
	input_set_abs_params(input, ABS_X, 0, SCREEN_WIDTH - 1, 0, 0);
	input_set_abs_params(input, ABS_Y, 0, SCREEN_HEIGHT - 1, 0, 0);
	input_set_abs_params(input, ABS_PRESSURE, 0, 1, 0, 0);
	input_set_capability(input, EV_KEY, BTN_TOUCH);
	set_bit(INPUT_PROP_DIRECT, input->propbit);
	ts->input = input;
	platform_set_drvdata(pdev, ts);

	ret = android3ds_touch_hw_init(ts->map);
	if (ret)
		return ret;
	ret = input_setup_polling(input, android3ds_touch_poll);
	if (ret)
		return ret;
	input_set_poll_interval(input, POLL_INTERVAL_MS);
	ret = input_register_device(input);
	if (!ret)
		pr_info("registered pure Android direct-touch device 320x240\n");
	return ret;
}

static const struct of_device_id android3ds_touch_of_match[] = {
	{ .compatible = "nintendo,android3ds-touchscreen" },
	{ }
};
MODULE_DEVICE_TABLE(of, android3ds_touch_of_match);

static struct platform_driver android3ds_touch_driver = {
	.probe = android3ds_touch_probe,
	.driver = {
		.name = DRIVER_NAME,
		.of_match_table = android3ds_touch_of_match,
	},
};
module_platform_driver(android3ds_touch_driver);
MODULE_DESCRIPTION("Android direct-touch driver for Nintendo 3DS");
MODULE_LICENSE("GPL");
''')

dtsi = DTSI.read_text()
dtsi = dtsi.replace('compatible = "nintendo,3dstsc-touch";',
                    'compatible = "nintendo,android3ds-touchscreen";')
dtsi = dtsi.replace('\t\t\t\t\ttouchscreen-size-x = <4096>;\n'
                    '\t\t\t\t\ttouchscreen-size-y = <4096>;\n'
                    '\t\t\t\t\ttouchscreen-inverted-y;\n'
                    '\t\t\t\t\ttouchscreen-swapped-x-y;\n',
                    '\t\t\t\t\t/* Driver reports final Android 320x240 coordinates. */\n'
                    '\t\t\t\t\ttouchscreen-size-x = <320>;\n'
                    '\t\t\t\t\ttouchscreen-size-y = <240>;\n')
DTSI.write_text(dtsi)

launcher = LAUNCHER.read_text()
old = '''        destroyRenderScript();
        mRS = null;
        mRollo = null;
'''
new = '''        // N3DS_SOFTWARE_ALL_APPS_TEARDOWN: surfaceChanged() deliberately
        // selects software mode and never creates RenderScript. The framework
        // helper dereferences its null RS object, so do not enter it.
        if (!mSoftwareMode && mRS != null) {
            destroyRenderScript();
        }
        mRS = null;
        mRollo = null;
'''
if "N3DS_NATIVE_ALL_APPS_DRAWER" in launcher:
    # The native GridView replacement owns no RenderScript/Surface resources.
    pass
elif "N3DS_SOFTWARE_ALL_APPS_TEARDOWN" not in launcher:
    if launcher.count(old) != 1:
        raise SystemExit("Launcher teardown hunk not found exactly once")
    launcher = launcher.replace(old, new, 1)
LAUNCHER.write_text(launcher)

ktr = KTR.read_text()
ktr = ktr.replace(
    '''\t\t * maxcpus=1 IS NOT A TEST -- IT IS THE SUPPORTED BOOT
\t\t * CONFIGURATION FOR THIS PORT. Do not remove it without a
\t\t * hardware-confirmed SMP fix in hand.
''',
    '''\t\t * maxcpus=1 was the supported safety configuration until the
\t\t * CPU1 boot-ROM SGI EOI repair described at the end of this history.
''',
    1)
ktr = ktr.replace(
    '''\t\t *    work. Fix it, boot it, and only then delete this line. */''',
    '''\t\t *    work. 2026-08-13: smp_start now EOIs and drains CPU1's
\t\t *    boot-ROM SGI before entering Linux, matching the working 2/3 path.
\t\t *    A later isolated page-fault crash must not be used to disable the
\t\t *    otherwise hardware-proven four-core KTR configuration. */''',
    1)
ktr = ktr.replace(' consoleblank=0 maxcpus=1";', ' consoleblank=0";', 1)
ktr = ktr.replace('\t\tstatus = "disabled";\n', '\t\tstatus = "okay";\n', 1)
if (any('maxcpus=' in line for line in ktr.splitlines()
        if 'bootargs = ' in line) or 'status = "okay";' not in ktr):
    raise SystemExit("KTR four-core SMP/L2 state not enabled")
KTR.write_text(ktr)

machine = MACHINE.read_text()
if "N3DS_KTR_PERFORMANCE_PROOF" not in machine:
    marker = '''static void __init ctr_dt_init_machine(void)
{
	printk("ctr_dt_init_machine\\n");
'''
    replacement = '''static void __init ctr_dt_init_machine(void)
{
	printk("ctr_dt_init_machine\\n");
	/* N3DS_KTR_PERFORMANCE_PROOF: loader programmed PDN before Linux. */
	if (of_machine_is_compatible("nintendo,ktr")) {
		void __iomem *socmode = ioremap(0x10141300, 4);
		void __iomem *l2 = ioremap(0x17e10000, 4);
		pr_info("New3DS performance: SOCMODE=0x%04x PL310_CTRL=0x%08x\\n",
			ioread16(socmode), ioread32(l2));
		iounmap(l2);
		iounmap(socmode);
	}
'''
    if machine.count(marker) != 1:
        raise SystemExit("machine init marker missing")
    machine = machine.replace(marker, replacement, 1)
    machine = machine.replace('\t.dt_compat\t= ctr_dt_platform_compat,\n',
        '\t.dt_compat\t= ctr_dt_platform_compat,\n'
        '\t.l2c_aux_val\t= 0,\n'
        '\t.l2c_aux_mask\t= ~0UL,\n', 1)
MACHINE.write_text(machine)

smp = (LOADER / "smp.c").read_text()
smp = smp.replace('\tdownclock();\n\tsetup_overlays();\n\t// upclock();\n',
                  '\tdownclock();\n\tsetup_overlays();\n\t/* N3DS_FULL_CLOCK_RESTORED */\n\tupclock();\n')
if "N3DS_FULL_CLOCK_RESTORED" not in smp:
    setup = smp.index("\tsetup_overlays();\n", smp.index("static void online_cores23"))
    clock = smp.index("\tupclock();\n", setup)
    smp = smp[:clock] + "\t/* N3DS_FULL_CLOCK_RESTORED */\n" + smp[clock:]
if "N3DS_FULL_CLOCK_RESTORED" not in smp:
    raise SystemExit("loader re-upclock marker absent")
(LOADER / "smp.c").write_text(smp)

start = (LOADER / "start.S").read_text()
if "N3DS_CPU1_SGI_EOI" not in start:
    old = '''\tands r0, r0, #3
\t@ Fall through into smp_boot
'''
    new = '''\tands r0, r0, #3
\t/* N3DS_CPU1_SGI_EOI: CPU1 alone enters through the boot-ROM SGI stub.
\t * Cores 2/3 explicitly EOI their wake SGI in core23_entry(); mirror that
\t * for CPU1 so its GIC running priority does not mask every later Linux IPI. */
\tcmp r0, #1
\tldreq r2, =0x17E00110
\tmoveq r3, #1
\tstreq r3, [r2]
\t/* N3DS_CPU1_SGI_EOI_DSB: complete the distributor write before Linux. */
\tmcreq p15, 0, r3, c7, c10, 4
\t@ Fall through into smp_boot
'''
    if start.count(old) != 1:
        raise SystemExit("CPU1 smp_start hunk missing")
    start = start.replace(old, new, 1)
if "N3DS_CPU1_SGI_EOI" in start and "N3DS_CPU1_SGI_EOI_DSB" not in start:
    start = start.replace('\tstreq r3, [r2]\n\t@ Fall through into smp_boot\n',
                          '\tstreq r3, [r2]\n'
                          '\t/* N3DS_CPU1_SGI_EOI_DSB */\n'
                          '\tmcreq p15, 0, r3, c7, c10, 4\n'
                          '\t@ Fall through into smp_boot\n', 1)
(LOADER / "start.S").write_text(start)

print("patch_n3ds_touch_launcher_smp: new direct touch; Launcher fix; KTR SMP/L2/clock")
