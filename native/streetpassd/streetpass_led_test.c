#include "streetpass_journal.h"
#include "streetpass_led.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static void make_file(const char *path, const char *value)
{
    FILE *file = fopen(path, "w");
    assert(file != NULL);
    assert(fputs(value, file) >= 0);
    assert(fclose(file) == 0);
}

static void read_file(const char *path, char *value, size_t capacity)
{
    FILE *file = fopen(path, "r");
    assert(file != NULL);
    assert(fgets(value, (int)capacity, file) != NULL);
    assert(fclose(file) == 0);
}

int main(void)
{
    char root[] = "/tmp/streetpass-led-XXXXXX";
    char device[256];
    char colors[64];
    char brightness[16];
    char colors_path[320];
    char brightness_path[320];
    struct sp_led led;

    assert(mkdtemp(root) != NULL);
    snprintf(device, sizeof(device), "%s/%s", root, SP_LED_DEVICE_NAME);
    assert(mkdir(device, 0700) == 0);
    {
        char path[320];
        snprintf(path, sizeof(path), "%s/multi_intensity", device);
        make_file(path, "0 0 0\n");
        snprintf(path, sizeof(path), "%s/brightness", device);
        make_file(path, "0\n");
    }

    assert(sp_led_init(&led, root) == 0);
    sp_led_set_state(&led, SP_STATE_DISABLED, 0);
    snprintf(brightness_path, sizeof(brightness_path), "%s/brightness", device);
    read_file(brightness_path, colors, sizeof(colors));
    assert(strcmp(colors, "0") == 0 || strcmp(colors, "0\n") == 0);

    sp_led_set_state(&led, SP_STATE_SEARCHING, 1);
    assert(led.pattern == SP_LED_RAPID_GREEN);
    snprintf(colors_path, sizeof(colors_path), "%s/multi_intensity", device);
    read_file(colors_path, brightness, sizeof(brightness));
    assert(strcmp(brightness, "0 255 0") == 0 ||
           strcmp(brightness, "0 255 0\n") == 0);

    read_file(brightness_path, colors, sizeof(colors));
    assert(strcmp(colors, "255") == 0 || strcmp(colors, "255\n") == 0);
    sp_led_tick(&led, led.next_toggle_ms);
    read_file(brightness_path, colors, sizeof(colors));
    assert(strcmp(colors, "0") == 0 || strcmp(colors, "0\n") == 0);

    sp_led_set_state(&led, SP_STATE_DEGRADED, 1);
    assert(led.pattern == SP_LED_SLOW_GREEN);
    read_file(brightness_path, colors, sizeof(colors));
    assert(strcmp(colors, "255") == 0 || strcmp(colors, "255\n") == 0);
    sp_led_tick(&led, led.next_toggle_ms);
    read_file(brightness_path, colors, sizeof(colors));
    assert(strcmp(colors, "0") == 0 || strcmp(colors, "0\n") == 0);

    sp_led_set_state(&led, SP_STATE_EXCHANGING, 1);
    assert(led.pattern == SP_LED_SOLID_GREEN);
    read_file(brightness_path, colors, sizeof(colors));
    assert(strcmp(colors, "255") == 0 || strcmp(colors, "255\n") == 0);
    sp_led_set_state(&led, SP_STATE_STARTING, 1);
    assert(led.pattern == SP_LED_RAPID_GREEN);
    sp_led_set_state(&led, SP_STATE_AUTHENTICATING, 1);
    assert(led.pattern == SP_LED_RAPID_GREEN);
    sp_led_set_state(&led, SP_STATE_DISCONNECTED, 1);
    assert(led.pattern == SP_LED_RAPID_GREEN);
    sp_led_set_state(&led, SP_STATE_EXCHANGING, 0);
    assert(led.pattern == SP_LED_OFF);
    sp_led_close(&led);
    read_file(brightness_path, colors, sizeof(colors));
    assert(strcmp(colors, "0") == 0 || strcmp(colors, "0\n") == 0);

    {
        char path[320];
        snprintf(path, sizeof(path), "%s/multi_intensity", device);
        assert(unlink(path) == 0);
        snprintf(path, sizeof(path), "%s/brightness", device);
        assert(unlink(path) == 0);
    }
    assert(rmdir(device) == 0);
    assert(rmdir(root) == 0);
    puts("streetpass LED tests: PASS");
    return 0;
}
