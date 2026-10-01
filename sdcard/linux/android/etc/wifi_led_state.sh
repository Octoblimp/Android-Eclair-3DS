#!/bin/sh
# N3DS_WIFI_LED_REGMAP_STATE: the MCU I2C address is kernel-owned.  Use the
# LED-class endpoint backed by the parent's serialized regmap, never i2cset.

LED=/sys/class/leds/n3ds-wifi/brightness

case "$1" in
    on) VALUE=1 ;;
    off) VALUE=0 ;;
    *)
        echo "wifi_led_state: invalid state '$1'" > /dev/kmsg
        exit 2
        ;;
esac

if [ ! -w "$LED" ]; then
    echo "wifi_led_state: missing writable $LED state=$1" > /dev/kmsg
    exit 1
fi

echo "$VALUE" > "$LED"
STATUS=$?
echo "wifi_led_state: state=$1 led=$LED value=$VALUE status=$STATUS" > /dev/kmsg
exit "$STATUS"
