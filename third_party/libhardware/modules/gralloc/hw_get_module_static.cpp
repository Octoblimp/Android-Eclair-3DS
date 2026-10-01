/*
 * Android3DS: a static hw_get_module().
 *
 * libhardware/hardware.c's hw_get_module() finds a HAL by building a filename
 * from ro.hardware / ro.product.board / ro.board.platform / ro.arch, then
 * dlopen()ing /system/lib/hw/<name>.<variant>.so and reading the "HMI" symbol
 * out of it.
 *
 * That cannot work here. Every binary in this image is statically linked, and
 * bionic's dlopen() is a stub that unconditionally returns NULL for a static
 * executable -- only the dynamic linker has a real implementation and it never
 * runs for one. (This is the same thing that killed libandroid_servers.so; see
 * docs/HANDOFF.md's "dlopen() from a static binary can't work" recap. It is
 * documented in scripts/build_libdl.sh's own header too.)
 *
 * So the HAL modules this port actually has are linked in directly and looked
 * up from this table instead. Linking this file ahead of libhardware.a in the
 * link line makes it win the hw_get_module symbol; libhardware.a's own
 * hardware.o then has no undefined reference pulling it in, so the dlopen
 * version never enters the binary at all.
 *
 * Adding a HAL: build its module into the same archive with
 * -DHAL_MODULE_INFO_SYM=<unique_name>, declare that symbol here, and add a row
 * to sBuiltinModules. Nothing else changes.
 */

#define LOG_TAG "HAL"

#include <string.h>
#include <errno.h>
#include <hardware/hardware.h>
#include <hardware/gralloc.h>
#include <hardware/lights.h>
#include <hardware/copybit.h>
#include <cutils/log.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <dirent.h>

/*
 * The gralloc module, built from libhardware/modules/gralloc with
 * -DHAL_MODULE_INFO_SYM=n3ds_gralloc_module so the symbol name is unique and
 * can be referenced from here by name rather than found in a .so.
 */
extern "C" struct hw_module_t n3ds_gralloc_module;
/* N3DS_BUILTIN_COPYBIT */
extern "C" struct copybit_module_t n3ds_copybit_module;

/* -------------------------------------------------------------------------
 * N3DS Lights HAL implementation
 * ------------------------------------------------------------------------- */
static char s_led_multi_path[256];
static char s_led_brightness_path[256];
static int s_led_paths_inited = 0;

static void init_led_paths() {
    if (s_led_paths_inited) return;
    s_led_paths_inited = 1;

    DIR* dir = opendir("/sys/class/leds");
    if (!dir) return;

    struct dirent* ent;
    while ((ent = readdir(dir)) != NULL) {
        if (strstr(ent->d_name, "mcu-led") || strstr(ent->d_name, "mcu_led")) {
            snprintf(s_led_multi_path, sizeof(s_led_multi_path), "/sys/class/leds/%s/multi_intensity", ent->d_name);
            snprintf(s_led_brightness_path, sizeof(s_led_brightness_path), "/sys/class/leds/%s/brightness", ent->d_name);
            break;
        }
    }
    closedir(dir);
}

static int set_light_wifi(struct light_device_t* dev, struct light_state_t const* state) {
    init_led_paths();

    if (!s_led_multi_path[0] || !s_led_brightness_path[0]) {
        return -ENODEV;
    }

    int fd = open(s_led_multi_path, O_WRONLY);
    if (fd >= 0) {
        char buf[64];
        int color = state->color & 0x00ffffff;
        int r = (color >> 16) & 0xff;
        int g = (color >> 8) & 0xff;
        int b = color & 0xff;
        int len = snprintf(buf, sizeof(buf), "%d %d %d\n", r, g, b);
        write(fd, buf, len);
        close(fd);
    }

    fd = open(s_led_brightness_path, O_WRONLY);
    if (fd >= 0) {
        char buf[64];
        int brightness = (state->color >> 24) & 0xff;
        if (brightness == 0 && (state->color & 0x00ffffff) != 0) {
            brightness = 255;
        }
        int len = snprintf(buf, sizeof(buf), "%d\n", brightness);
        write(fd, buf, len);
        close(fd);
    }
    return 0;
}

static int open_lights(const struct hw_module_t* module, char const* name,
        struct hw_device_t** device) {
    int (*set_light)(struct light_device_t* dev, struct light_state_t const* state);

    if (0 == strcmp(LIGHT_ID_WIFI, name) || 0 == strcmp(LIGHT_ID_NOTIFICATIONS, name)) {
        set_light = set_light_wifi;
    } else {
        return -EINVAL;
    }

    struct light_device_t *dev = (struct light_device_t*)malloc(sizeof(struct light_device_t));
    memset(dev, 0, sizeof(*dev));

    dev->common.tag = HARDWARE_DEVICE_TAG;
    dev->common.version = 0;
    dev->common.module = (struct hw_module_t*)module;
    dev->common.close = (int (*)(struct hw_device_t*))free;
    dev->set_light = set_light;

    *device = (struct hw_device_t*)dev;
    return 0;
}

static struct hw_module_methods_t lights_module_methods = {
    .open = open_lights,
};

static struct hw_module_t n3ds_lights_module = {
    .tag = HARDWARE_MODULE_TAG,
    .version_major = 1,
    .version_minor = 0,
    .id = LIGHTS_HARDWARE_MODULE_ID,
    .name = "N3DS Lights Module",
    .author = "Octoblimp",
    .methods = &lights_module_methods,
    .dso = 0,
    .reserved = {0},
};

/* ------------------------------------------------------------------------- */

struct builtin_module {
    const char* id;
    struct hw_module_t* module;
};

static const struct builtin_module sBuiltinModules[] = {
    { GRALLOC_HARDWARE_MODULE_ID, &n3ds_gralloc_module },
    { COPYBIT_HARDWARE_MODULE_ID,
      &n3ds_copybit_module.common },
    { LIGHTS_HARDWARE_MODULE_ID, &n3ds_lights_module },
};

extern "C" int hw_get_module(const char* id, const struct hw_module_t** module)
{
    if (id == NULL || module == NULL)
        return -EINVAL;

    for (unsigned i = 0;
         i < sizeof(sBuiltinModules) / sizeof(sBuiltinModules[0]); i++) {
        if (!strcmp(id, sBuiltinModules[i].id)) {
            *module = sBuiltinModules[i].module;
            /* N3DS_QUIET_BUILTIN_HAL_LOOKUP: this is a hot path;
             * successful lookups are routine, not log events. */
            return 0;
        }
    }

    LOGW("hw_get_module('%s'): no built-in module (dlopen is not available in "
         "a static binary -- see hw_get_module_static.cpp)", id);
    *module = NULL;
    return -ENOENT;
}
