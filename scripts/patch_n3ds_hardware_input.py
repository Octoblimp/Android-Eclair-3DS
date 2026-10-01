#!/usr/bin/env python3
"""Install the 3DS hardware input bridge and repair touch/MCU signalling.

This is separate from Android policy: it operates at the Linux input layer,
the same layer used by ctr_pwrkey for the known-working START button.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
LINUX = ROOT / "third_party/linux"
PLATFORM = LINUX / "drivers/platform/nintendo3ds"
TOUCH = PLATFORM / "tsc/touch.c"
DTS = LINUX / "arch/arm/boot/dts/nintendo3ds.dtsi"
OVERLAY = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay"
KEYLAYOUT = OVERLAY / "system/usr/keylayout"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


nav_source = r'''// SPDX-License-Identifier: GPL-2.0
/*
 * ctr_navkey.c -- reliable Nintendo 3DS Android navigation bridge
 *
 * ctr_pwrkey proves that an input_handler attached to hid_buttons receives
 * START correctly on this hardware.  Attach at the identical layer and
 * forward Y/B plus the MCU HOME input through one unambiguous keyboard.
 */

#define DRIVER_NAME "3ds-navkey"
#define pr_fmt(fmt) DRIVER_NAME ": " fmt

#include <linux/init.h>
#include <linux/input.h>
#include <linux/jiffies.h>
#include <linux/module.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/workqueue.h>

static struct input_dev *nav_input;
static struct delayed_work select_power_down_work;
static struct delayed_work select_power_up_work;
static bool select_held;

#define SELECT_HOLD_MS 500
#define ANDROID_GLOBAL_ACTION_MS 650

static void ctr_navkey_select_power_up(struct work_struct *work)
{
	pr_debug("SELECT hold: releasing synthetic Android POWER\n");
	input_report_key(nav_input, KEY_POWER, 0);
	input_sync(nav_input);
}

static void ctr_navkey_select_power_down(struct work_struct *work)
{
	if (!select_held)
		return;

	/* N3DS_SELECT_SYNTHETIC_POWER_HOLD: Eclair filters SEARCH before
	 * PhoneWindowManager on this input device. POWER is its native global-
	 * actions route. Generate it only after SELECT is already a long press,
	 * then retain it beyond Android's 500 ms GlobalActions timeout. */
	pr_debug("SELECT held %u ms: pressing synthetic Android POWER\n",
		SELECT_HOLD_MS);
	input_report_key(nav_input, KEY_POWER, 1);
	input_sync(nav_input);
	schedule_delayed_work(&select_power_up_work,
		msecs_to_jiffies(ANDROID_GLOBAL_ACTION_MS));
}

static int ctr_navkey_translate(unsigned int code)
{
	switch (code) {
	case BTN_Y:
		return KEY_BACK;
	case BTN_B:
		return KEY_PROG1;
	case BTN_A:
		return KEY_ENTER;
	case KEY_HOME:
		return KEY_HOME;
	case KEY_UP:
	case KEY_DOWN:
	case KEY_LEFT:
	case KEY_RIGHT:
		return code;
	default:
		return -1;
	}
}

static void ctr_navkey_event(struct input_handle *handle, unsigned int type,
			     unsigned int code, int value)
{
	int output;

	if (type != EV_KEY || value == 2)
		return;
	if (code == BTN_SELECT) {
		select_held = value != 0;
		if (value == 1) {
			cancel_delayed_work(&select_power_up_work);
			schedule_delayed_work(&select_power_down_work,
				msecs_to_jiffies(SELECT_HOLD_MS));
		} else {
			cancel_delayed_work(&select_power_down_work);
		}
		return;
	}
	output = ctr_navkey_translate(code);
	if (output < 0)
		return;

	pr_info("source=\"%s\" code=%u value=%d -> code=%d\n",
		handle->dev->name ? handle->dev->name : "?", code, value,
		output);
	input_report_key(nav_input, output, value);
	input_sync(nav_input);
}

static int ctr_navkey_connect(struct input_handler *handler,
			      struct input_dev *dev,
			      const struct input_device_id *id)
{
	struct input_handle *handle;
	int err;

	/* Never attach to our own translated output device. */
	if (dev == nav_input || (dev->name && !strcmp(dev->name, "n3ds_navigation")))
		return -ENODEV;

	handle = kzalloc(sizeof(*handle), GFP_KERNEL);
	if (!handle)
		return -ENOMEM;
	handle->dev = dev;
	handle->handler = handler;
	handle->name = DRIVER_NAME;

	err = input_register_handle(handle);
	if (err)
		goto err_free;
	err = input_open_device(handle);
	if (err)
		goto err_unregister;

	pr_info("watching navigation keys on \"%s\"\n",
		dev->name ? dev->name : "?");
	return 0;

err_unregister:
	input_unregister_handle(handle);
err_free:
	kfree(handle);
	return err;
}

static void ctr_navkey_disconnect(struct input_handle *handle)
{
	input_close_device(handle);
	input_unregister_handle(handle);
	kfree(handle);
}

static const struct input_device_id ctr_navkey_ids[] = {
	{
		.flags = INPUT_DEVICE_ID_MATCH_EVBIT | INPUT_DEVICE_ID_MATCH_KEYBIT,
		.evbit = { BIT_MASK(EV_KEY) },
		.keybit = { [BIT_WORD(BTN_Y)] = BIT_MASK(BTN_Y) },
	},
	{
		.flags = INPUT_DEVICE_ID_MATCH_EVBIT | INPUT_DEVICE_ID_MATCH_KEYBIT,
		.evbit = { BIT_MASK(EV_KEY) },
		.keybit = { [BIT_WORD(KEY_HOME)] = BIT_MASK(KEY_HOME) },
	},
	{ },
};
MODULE_DEVICE_TABLE(input, ctr_navkey_ids);

static struct input_handler ctr_navkey_handler = {
	.event = ctr_navkey_event,
	.connect = ctr_navkey_connect,
	.disconnect = ctr_navkey_disconnect,
	.name = DRIVER_NAME,
	.id_table = ctr_navkey_ids,
};

static int __init ctr_navkey_init(void)
{
	int err;

	nav_input = input_allocate_device();
	if (!nav_input)
		return -ENOMEM;
	nav_input->name = "n3ds_navigation";
	nav_input->phys = DRIVER_NAME "/input0";
	nav_input->id.bustype = BUS_HOST;
	input_set_capability(nav_input, EV_KEY, KEY_BACK);
	input_set_capability(nav_input, EV_KEY, KEY_PROG1);
	input_set_capability(nav_input, EV_KEY, KEY_HOME);
	input_set_capability(nav_input, EV_KEY, KEY_ENTER);
	input_set_capability(nav_input, EV_KEY, KEY_POWER);
	input_set_capability(nav_input, EV_KEY, KEY_UP);
	input_set_capability(nav_input, EV_KEY, KEY_DOWN);
	input_set_capability(nav_input, EV_KEY, KEY_LEFT);
	input_set_capability(nav_input, EV_KEY, KEY_RIGHT);

	INIT_DELAYED_WORK(&select_power_down_work, ctr_navkey_select_power_down);
	INIT_DELAYED_WORK(&select_power_up_work, ctr_navkey_select_power_up);
	err = input_register_device(nav_input);
	if (err) {
		input_free_device(nav_input);
		nav_input = NULL;
		return err;
	}
	err = input_register_handler(&ctr_navkey_handler);
	if (err) {
		input_unregister_device(nav_input);
		nav_input = NULL;
		return err;
	}
	pr_info("registered Y=BACK B=RECENTS A=OK hold-SELECT=POWER-OPTIONS D-Pad nav physical-HOME=HOME bridge\n");
	return 0;
}

static void __exit ctr_navkey_exit(void)
{
	cancel_delayed_work_sync(&select_power_down_work);
	cancel_delayed_work_sync(&select_power_up_work);
	input_unregister_handler(&ctr_navkey_handler);
	input_unregister_device(nav_input);
}

module_init(ctr_navkey_init);
module_exit(ctr_navkey_exit);
MODULE_DESCRIPTION("Nintendo 3DS Android navigation input bridge");
MODULE_LICENSE("GPL");
'''
(PLATFORM / "ctr_navkey.c").write_text(nav_source)

kconfig_path = PLATFORM / "Kconfig"
kconfig = kconfig_path.read_text()
if "config CTR_NAVKEY" not in kconfig:
    kconfig = replace_once(
        kconfig,
        "config CTR_PWRKEY\n",
        "config CTR_NAVKEY\n"
        "\tbool \"Nintendo 3DS Android navigation bridge\"\n"
        "\tdepends on INPUT\n"
        "\tdefault y\n"
        "\thelp\n"
        "\t  Forward Y, B, and physical HOME through a dedicated input\n"
        "\t  device using the same input-handler path as CTR_PWRKEY.\n\n\n"
        "config CTR_PWRKEY\n",
        "nav Kconfig",
    )
kconfig_path.write_text(kconfig)

makefile_path = PLATFORM / "Makefile"
makefile = makefile_path.read_text()
if "CONFIG_CTR_NAVKEY" not in makefile:
    makefile = replace_once(
        makefile,
        "obj-$(CONFIG_CTR_PWRKEY)\t+= ctr_pwrkey.o\n",
        "obj-$(CONFIG_CTR_PWRKEY)\t+= ctr_pwrkey.o\n"
        "obj-$(CONFIG_CTR_NAVKEY)\t+= ctr_navkey.o\n",
        "nav Makefile",
    )
makefile_path.write_text(makefile)

# The MCU interrupt line is active-low until its status registers are read.
# Edge-falling left the parent GPIO at a permanent count of zero in the
# hardware capture; level-low lets regmap-irq service and acknowledge it.
dts = DTS.read_text()
dts = dts.replace(
    "interrupts-extended = <&gpio3 9 IRQ_TYPE_EDGE_FALLING>;",
    "interrupts-extended = <&gpio3 9 IRQ_TYPE_LEVEL_LOW>;",
)
if "<&gpio3 9 IRQ_TYPE_LEVEL_LOW>" not in dts:
    raise SystemExit("MCU IRQ: active-low level mapping not present")
DTS.write_text(dts)

# Restore the controller-defined pen bit from the original driver.  Only the
# first X word owns this status flag; the five words are coordinate samples,
# not five independent pen-state reports.
touch = TOUCH.read_text()
old_pen = "\ttouch_down_samples = 0;\n\tfor (i = 0; i < N3DS_MEDIAN_TOUCH_SAMPLES; i++) {"
new_pen = "\ttouch_down_samples = !(raw_data[0] & BIT(4));\n\tfor (i = 0; i < N3DS_MEDIAN_TOUCH_SAMPLES; i++) {"
if old_pen in touch:
    touch = replace_once(touch, old_pen, new_pen, "controller pen status")
touch = touch.replace(
    "\t\tif (!(xword & BIT(12)))\n\t\t\ttouch_down_samples++;\n",
    "",
)
touch = touch.replace(
    "\tpendown = touch_down_samples >= 3;",
    "\tpendown = touch_down_samples != 0;",
)

if "N3DS_TOUCH_CALIBRATION" not in touch:
    touch = replace_once(
        touch,
        "#define N3DS_MEDIAN_TOUCH_SAMPLES\t5\n",
        "#define N3DS_MEDIAN_TOUCH_SAMPLES\t5\n"
        "#define N3DS_TOUCH_CALIBRATION\t\t1\n\n"
        "/* N3DS_FULL_ADC_TOUCH_RANGE: conservative full-domain fallback.\n"
        " * Factory HWCAL contains a per-panel two-point transform; module\n"
        " * parameters allow exact values once that data is exposed. */\n"
        "static unsigned int touch_min_x = 256;\n"
        "static unsigned int touch_max_x = 3840;\n"
        "static unsigned int touch_min_y = 256;\n"
        "static unsigned int touch_max_y = 3840;\n"
        "module_param(touch_min_x, uint, 0644);\n"
        "module_param(touch_max_x, uint, 0644);\n"
        "module_param(touch_min_y, uint, 0644);\n"
        "module_param(touch_max_y, uint, 0644);\n",
        "touch calibration parameters",
    )
    touch = replace_once(
        touch,
        "static void touch_input_poll(struct input_dev *input)\n{\n",
        "static u16 touch_scale(u16 raw, unsigned int low, unsigned int high,\n"
        "\t\t       unsigned int pixels)\n"
        "{\n"
        "\tif (high <= low)\n"
        "\t\treturn 0;\n"
        "\tif (raw <= low)\n"
        "\t\treturn 0;\n"
        "\tif (raw >= high)\n"
        "\t\treturn pixels - 1;\n"
        "\treturn (u16)(((u32)(raw - low) * (pixels - 1)) / (high - low));\n"
        "}\n\n"
        "static void touch_input_poll(struct input_dev *input)\n{\n",
        "touch scale helper",
    )
    touch = replace_once(
        touch,
        "\t\tscreen_touch_x = (u16)((u32)raw_touch_x * TOUCH_MAX_X / MAX_12BIT);\n"
        "\t\tscreen_touch_y = (u16)((u32)raw_touch_y * TOUCH_MAX_Y / MAX_12BIT);\n",
        "\t\tscreen_touch_x = touch_scale(raw_touch_x, touch_min_x,\n"
        "\t\t\ttouch_max_x, TOUCH_MAX_X);\n"
        "\t\tscreen_touch_y = touch_scale(raw_touch_y, touch_min_y,\n"
        "\t\t\ttouch_max_y, TOUCH_MAX_Y);\n",
        "calibrated touch scaling",
    )
    touch = replace_once(
        touch,
        "\t\tif (!touch_hid->pendown) {\n"
        "\t\t\ttouch_hid->pendown = true;\n",
        "\t\tif (!touch_hid->pendown) {\n"
        "\t\t\tpr_info(\"pen down raw=(%u,%u) screen=(%u,%u) samplesX=%u,%u,%u,%u,%u samplesY=%u,%u,%u,%u,%u\\n\",\n"
        "\t\t\t\traw_touch_x, raw_touch_y, screen_touch_x, screen_touch_y,\n"
        "\t\t\t\tx_samples[0], x_samples[1], x_samples[2], x_samples[3], x_samples[4],\n"
        "\t\t\t\ty_samples[0], y_samples[1], y_samples[2], y_samples[3], y_samples[4]);\n"
        "\t\t\ttouch_hid->pendown = true;\n",
        "touch down diagnostics",
    )
    touch = replace_once(
        touch,
        "\t} else if (touch_hid->pendown) {\n"
        "\t\ttouch_hid->pendown = false;\n",
        "\t} else if (touch_hid->pendown) {\n"
        "\t\tpr_info(\"pen up\\n\");\n"
        "\t\ttouch_hid->pendown = false;\n",
        "touch up diagnostics",
    )
TOUCH.write_text(touch)

# Only the synthetic bridge is interpreted by Android. This avoids duplicate
# delivery from source and translated devices and makes EventHub selection
# independent of joystick-button keycode support in old Eclair.
KEYLAYOUT.mkdir(parents=True, exist_ok=True)
(KEYLAYOUT / "n3ds_navigation.kl").write_text(
    "# Dedicated kernel-translated navigation device\n"
    "key 102   HOME\n"
    "key 148   B\n"
    "key 158   BACK\n"
    "key 28    DPAD_CENTER\n"
    "key 116   POWER\n"
    "key 103   DPAD_UP\n"
    "key 108   DPAD_DOWN\n"
    "key 105   DPAD_LEFT\n"
    "key 106   DPAD_RIGHT\n"
)
(KEYLAYOUT / "hid_buttons.kl").write_text(
    "# Source buttons are consumed by 3ds-navkey; START remains kernel power.\n"
    "# BTN_A (304) translated to KEY_ENTER by 3ds-navkey\n"
    "# BTN_B (305) translated to KEY_PROG1 by 3ds-navkey\n"
    "# BTN_Y (308) translated to KEY_BACK by 3ds-navkey\n"
    "# BTN_SELECT (314) becomes a timed synthetic KEY_POWER hold in 3ds-navkey\n"
    "# BTN_START (315) consumed by 3ds-pwrkey\n"
)
(KEYLAYOUT / "mcu_buttons.kl").write_text(
    "# MCU KEY_HOME is translated through n3ds_navigation by 3ds-navkey.\n"
)

print("patch_n3ds_hardware_input: START-style nav bridge, MCU level IRQ, calibrated touch")
