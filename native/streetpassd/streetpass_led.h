#ifndef ANDROID3DS_STREETPASS_LED_H
#define ANDROID3DS_STREETPASS_LED_H

#include <stdint.h>

/* The hinge/status LED is the kernel 3dsmcu-led multicolor device at MCU
 * register 0x2d.  It is deliberately separate from n3ds-wifi (register
 * 0x2a), which remains owned by Wi-Fi policy. */
#define SP_LED_DEVICE_NAME "2d.mcu-led"

enum sp_led_pattern {
    SP_LED_OFF = 0,
    SP_LED_SOLID_GREEN,
    SP_LED_RAPID_GREEN,
    SP_LED_SLOW_GREEN
};

struct sp_led {
    char led_dir[320];
    enum sp_led_pattern pattern;
    uint64_t next_toggle_ms;
    int level;
    int ready;
};

/* class_dir is injectable for host tests; production passes NULL and uses
 * /sys/class/leds.  Missing hardware is non-fatal and remains fail-closed. */
int sp_led_init(struct sp_led *led, const char *class_dir);
void sp_led_close(struct sp_led *led);
void sp_led_set_state(struct sp_led *led, unsigned runtime_state,
                      int enabled);
void sp_led_tick(struct sp_led *led, uint64_t now_ms);

#endif
