#include "streetpass_led.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define SP_LED_CLASS_DIR "/sys/class/leds"
#define SP_LED_RAPID_INTERVAL_MS 250u
#define SP_LED_SLOW_INTERVAL_MS 1000u

/* Keep the state values local to avoid coupling this small hardware helper
 * to the journal header's ABI. */
#define SP_STATE_DISABLED 0u
#define SP_STATE_STARTING 1u
#define SP_STATE_SEARCHING 2u
#define SP_STATE_AUTHENTICATING 3u
#define SP_STATE_EXCHANGING 4u
#define SP_STATE_DEGRADED 5u
#define SP_STATE_DISCONNECTED 6u
#define SP_STATE_ERROR 7u

static uint64_t monotonic_ms(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0)
        return 0;
    return (uint64_t)now.tv_sec * 1000u +
           (uint64_t)now.tv_nsec / 1000000u;
}

static int write_value(const char *directory, const char *name,
                       const char *value)
{
    char path[384];
    int fd;
    size_t length;
    ssize_t written;

    if (snprintf(path, sizeof(path), "%s/%s", directory, name) < 0)
        return -ENAMETOOLONG;
    /* O_TRUNC is ignored by sysfs attributes and keeps the host fake-sysfs
     * regression honest when a shorter value replaces 255. */
    fd = open(path, O_WRONLY | O_TRUNC);
    if (fd < 0)
        return -errno;
    length = strlen(value);
    written = write(fd, value, length);
    close(fd);
    if (written != (ssize_t)length)
        return written < 0 ? -errno : -EIO;
    return 0;
}

static int find_device(struct sp_led *led, const char *class_dir)
{
    char path[384];
    struct stat metadata;

    if (!class_dir)
        class_dir = SP_LED_CLASS_DIR;
    if (snprintf(led->led_dir, sizeof(led->led_dir), "%s/%s",
                 class_dir, SP_LED_DEVICE_NAME) < 0 ||
        strlen(led->led_dir) >= sizeof(led->led_dir))
        return -ENAMETOOLONG;
    if (stat(led->led_dir, &metadata) != 0 || !S_ISDIR(metadata.st_mode))
        return -ENODEV;
    if (snprintf(path, sizeof(path), "%s/multi_intensity", led->led_dir) < 0 ||
        stat(path, &metadata) != 0 || !S_ISREG(metadata.st_mode))
        return -ENODEV;
    if (snprintf(path, sizeof(path), "%s/brightness", led->led_dir) < 0 ||
        stat(path, &metadata) != 0 || !S_ISREG(metadata.st_mode))
        return -ENODEV;
    return 0;
}

static int write_level(struct sp_led *led, int level)
{
    char value[8];
    int result;

    snprintf(value, sizeof(value), "%d", level ? 255 : 0);
    result = write_value(led->led_dir, "brightness", value);
    if (!result)
        led->level = level ? 1 : 0;
    return result;
}

static int write_green(struct sp_led *led, int level)
{
    int result;

    /* led.c consumes RGB subchannel intensities before overall brightness. */
    result = write_value(led->led_dir, "multi_intensity", "0 255 0");
    if (result)
        return result;
    return write_level(led, level);
}

static void mark_unavailable(struct sp_led *led)
{
    /* A failed color write must not leave a stale bright status asserted when
     * the brightness attribute is still usable.  If the endpoint itself has
     * disappeared, the best-effort write is harmless and ready=0 prevents
     * guessed fallback GPIO/I2C access. */
    (void)write_level(led, 0);
    led->ready = 0;
    led->pattern = SP_LED_OFF;
    led->level = 0;
    led->next_toggle_ms = 0;
}

int sp_led_init(struct sp_led *led, const char *class_dir)
{
    int result;

    if (!led)
        return -EINVAL;
    memset(led, 0, sizeof(*led));
    led->pattern = SP_LED_OFF;
    result = find_device(led, class_dir);
    if (result)
        return result;
    led->ready = 1;
    result = write_green(led, 0);
    if (result)
        mark_unavailable(led);
    return result;
}

void sp_led_close(struct sp_led *led)
{
    if (!led)
        return;
    if (led->ready) {
        /* Cleanup is best effort: shutdown must not be held hostage by a
         * disappearing sysfs endpoint, but a live endpoint is always driven
         * dark before streetpassd exits. */
        (void)write_green(led, 0);
    }
    led->pattern = SP_LED_OFF;
    led->level = 0;
    led->ready = 0;
}

static enum sp_led_pattern pattern_for_state(unsigned runtime_state,
                                             int enabled)
{
    if (!enabled || runtime_state == SP_STATE_DISABLED)
        return SP_LED_OFF;
    if (runtime_state == SP_STATE_EXCHANGING)
        return SP_LED_SOLID_GREEN;
    if (runtime_state == SP_STATE_DEGRADED || runtime_state == SP_STATE_ERROR)
        return SP_LED_SLOW_GREEN;
    /* STARTING, SEARCHING, AUTHENTICATING, and DISCONNECTED are enabled but
     * not authenticated/connected: make that boundary visible as a rapid
     * flash rather than claiming a solid connected state. */
    return SP_LED_RAPID_GREEN;
}

void sp_led_set_state(struct sp_led *led, unsigned runtime_state, int enabled)
{
    enum sp_led_pattern pattern;
    uint64_t now;
    int result;

    if (!led)
        return;
    pattern = pattern_for_state(runtime_state, enabled);
    if (!led->ready || led->pattern != pattern) {
        if (!led->ready)
            return; /* no guessed GPIO/I2C fallback; remain fail-closed */
        now = monotonic_ms();
        led->pattern = pattern;
        led->level = 0;
        switch (pattern) {
        case SP_LED_OFF:
            result = write_green(led, 0);
            led->next_toggle_ms = 0;
            break;
        case SP_LED_SOLID_GREEN:
            result = write_green(led, 1);
            led->next_toggle_ms = 0;
            break;
        case SP_LED_RAPID_GREEN:
            result = write_green(led, 1);
            led->next_toggle_ms = now + SP_LED_RAPID_INTERVAL_MS;
            break;
        case SP_LED_SLOW_GREEN:
            result = write_green(led, 1);
            led->next_toggle_ms = now + SP_LED_SLOW_INTERVAL_MS;
            break;
        default:
            result = -EINVAL;
            break;
        }
        if (result)
            mark_unavailable(led);
    }
}

void sp_led_tick(struct sp_led *led, uint64_t now_ms)
{
    uint64_t interval;

    if (!now_ms)
        now_ms = monotonic_ms();
    if (!led || !led->ready || led->pattern == SP_LED_OFF ||
        led->pattern == SP_LED_SOLID_GREEN || !led->next_toggle_ms ||
        now_ms < led->next_toggle_ms)
        return;
    interval = led->pattern == SP_LED_RAPID_GREEN
                   ? SP_LED_RAPID_INTERVAL_MS : SP_LED_SLOW_INTERVAL_MS;
    if (write_level(led, !led->level) != 0) {
        mark_unavailable(led);
        return;
    }
    do {
        led->next_toggle_ms += interval;
    } while (led->next_toggle_ms <= now_ms);
}
