/*
 * hal/lights/lights.c -- Nintendo New 3DS lights HAL
 *
 * Backs LIGHT_ID_NOTIFICATIONS/LIGHT_ID_ATTENTION/LIGHT_ID_BATTERY
 * with the console's single physical RGB notification LED, driven by
 * the kernel's CTR_MCULED driver (drivers/platform/nintendo3ds/mcu/led.c),
 * which registers a standard Linux led-class-multicolor device -- see
 * that file for confirmation of the sysfs ABI used here
 * (multi_intensity + brightness, per
 * Documentation/ABI/testing/sysfs-class-led-driver-multicolor).
 *
 * LIGHT_ID_BACKLIGHT/KEYBOARD/BUTTONS are intentionally NOT backed
 * here -- they're different physical hardware (panel_reg/
 * backlight_reg regulators, not this RGB LED) and out of scope for
 * this module; open() returns -EINVAL for them rather than silently
 * misrouting to the wrong LED.
 *
 * Cross-compiled against glibc (this project's kernel/buildroot
 * toolchain), NOT bionic -- there is no Android userspace to load
 * this .so yet (Phase 6). This validates the module compiles
 * correctly against the real Eclair ABI headers and links to a
 * well-formed HMI symbol; it will need rebuilding against bionic once
 * Phase 6's toolchain exists, same caveat as Phase 3's kernel work.
 */

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/stat.h>

#include <hardware/lights.h>

#define LEDS_CLASS_DIR "/sys/class/leds"

/* Find the one led-class-multicolor device in the system (the CTR
 * RGB notification LED) by looking for a leds/<name>/multi_intensity
 * file -- discovered at runtime rather than hardcoded, since the
 * exact sysfs name (of_device_make_bus_id-derived, e.g. "2d.mcu-led")
 * isn't confirmed from a real boot log yet. */
static int find_multicolor_led(char *out, size_t outlen)
{
	DIR *d;
	struct dirent *e;
	char path[320];
	struct stat st;
	int found = 0;

	d = opendir(LEDS_CLASS_DIR);
	if (!d)
		return -ENODEV;

	while ((e = readdir(d)) != NULL) {
		if (e->d_name[0] == '.')
			continue;
		snprintf(path, sizeof(path), "%s/%s/multi_intensity",
			 LEDS_CLASS_DIR, e->d_name);
		if (stat(path, &st) == 0) {
			snprintf(out, outlen, "%s/%s", LEDS_CLASS_DIR, e->d_name);
			found = 1;
			break;
		}
	}
	closedir(d);
	return found ? 0 : -ENODEV;
}

static int write_sysfs(const char *led_dir, const char *file, const char *value)
{
	char path[384];
	int fd, ret;
	size_t len;

	snprintf(path, sizeof(path), "%s/%s", led_dir, file);
	fd = open(path, O_WRONLY);
	if (fd < 0)
		return -errno;

	len = strlen(value);
	ret = write(fd, value, len);
	close(fd);

	return (ret == (int)len) ? 0 : -EIO;
}

struct ctr_light_device {
	struct light_device_t base;
	char led_dir[300];
};

static int ctr_set_light(struct light_device_t *dev, struct light_state_t const *state)
{
	struct ctr_light_device *ld = (struct ctr_light_device *)dev;
	unsigned int color = state->color;
	unsigned char r = (color >> 16) & 0xFF;
	unsigned char g = (color >> 8) & 0xFF;
	unsigned char b = color & 0xFF;
	char buf[32];
	int ret;

	/* Set the R/G/B ratios, then overall brightness=255 so
	 * led_mc_calc_color_components() (kernel side) reproduces
	 * them exactly: intensity * brightness / max_brightness ==
	 * intensity when brightness == max_brightness == 255. */
	snprintf(buf, sizeof(buf), "%u %u %u", r, g, b);
	ret = write_sysfs(ld->led_dir, "multi_intensity", buf);
	if (ret)
		return ret;

	return write_sysfs(ld->led_dir, "brightness", "255");
}

static int ctr_light_close(struct hw_device_t *dev)
{
	free(dev);
	return 0;
}

static int ctr_light_open(const struct hw_module_t *module, const char *id,
			   struct hw_device_t **device)
{
	struct ctr_light_device *ld;

	if (strcmp(id, LIGHT_ID_NOTIFICATIONS) != 0 &&
	    strcmp(id, LIGHT_ID_ATTENTION) != 0 &&
	    strcmp(id, LIGHT_ID_BATTERY) != 0) {
		/* Backlight/keyboard/buttons are different physical
		 * hardware -- not backed by this module, see file
		 * header. */
		return -EINVAL;
	}

	ld = calloc(1, sizeof(*ld));
	if (!ld)
		return -ENOMEM;

	if (find_multicolor_led(ld->led_dir, sizeof(ld->led_dir)) != 0) {
		free(ld);
		return -ENODEV;
	}

	ld->base.common.tag = HARDWARE_DEVICE_TAG;
	ld->base.common.version = 0;
	ld->base.common.module = (struct hw_module_t *)module;
	ld->base.common.close = ctr_light_close;
	ld->base.set_light = ctr_set_light;

	*device = &ld->base.common;
	return 0;
}

static struct hw_module_methods_t lights_module_methods = {
	.open = ctr_light_open,
};

struct hw_module_t HAL_MODULE_INFO_SYM = {
	.tag = HARDWARE_MODULE_TAG,
	.version_major = 1,
	.version_minor = 0,
	.id = LIGHTS_HARDWARE_MODULE_ID,
	.name = "Nintendo New 3DS lights HAL",
	.author = "android3ds project",
	.methods = &lights_module_methods,
};
