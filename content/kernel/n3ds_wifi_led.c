// SPDX-License-Identifier: GPL-2.0
/* Nintendo 3DS yellow WiFi LED, MCU register 0x2a. */

#define DRIVER_NAME "3dsmcu-wifi-led"

#include <linux/kernel.h>
#include <linux/leds.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/property.h>
#include <linux/regmap.h>

struct n3ds_wifi_led {
	struct regmap *map;
	unsigned int reg;
	struct led_classdev cdev;
};

static int n3ds_wifi_led_set(struct led_classdev *cdev,
			     enum led_brightness brightness)
{
	struct n3ds_wifi_led *led =
		container_of(cdev, struct n3ds_wifi_led, cdev);

	/* N3DS_WIFI_LED_REGMAP_STATE: MCU register 0x2a is four bits wide;
	 * any nonzero value lights the dedicated yellow WiFi indicator. */
	return regmap_write(led->map, led->reg, brightness ? 1 : 0);
}

static int n3ds_wifi_led_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct n3ds_wifi_led *led;
	u32 reg;

	if (!dev->parent)
		return -ENODEV;
	if (of_property_read_u32(dev->of_node, "reg", &reg))
		return -EINVAL;

	led = devm_kzalloc(dev, sizeof(*led), GFP_KERNEL);
	if (!led)
		return -ENOMEM;
	led->map = dev_get_regmap(dev->parent, NULL);
	if (!led->map)
		return -ENODEV;
	led->reg = reg;
	led->cdev.name = "n3ds-wifi";
	led->cdev.max_brightness = 1;
	led->cdev.brightness_set_blocking = n3ds_wifi_led_set;
	dev_set_drvdata(dev, led);

	return devm_led_classdev_register(dev, &led->cdev);
}

static int n3ds_wifi_led_remove(struct platform_device *pdev)
{
	struct n3ds_wifi_led *led = dev_get_drvdata(&pdev->dev);

	return n3ds_wifi_led_set(&led->cdev, LED_OFF);
}

static const struct of_device_id n3ds_wifi_led_of_match[] = {
	{ .compatible = "nintendo,3dsmcu-wifi-led" },
	{}
};
MODULE_DEVICE_TABLE(of, n3ds_wifi_led_of_match);

static struct platform_driver n3ds_wifi_led_driver = {
	.probe = n3ds_wifi_led_probe,
	.remove = n3ds_wifi_led_remove,
	.driver = {
		.name = DRIVER_NAME,
		.of_match_table = n3ds_wifi_led_of_match,
	},
};
module_platform_driver(n3ds_wifi_led_driver);

MODULE_DESCRIPTION("Nintendo 3DS WiFi state LED driver");
MODULE_AUTHOR("Android3DS");
MODULE_LICENSE("GPL");
