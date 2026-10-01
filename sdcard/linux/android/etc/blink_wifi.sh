#!/bin/sh
# The MCU is Linux I2C bus 2 (device 2-0025), not bus 1.
# Keep this one-shot bounded to two writes and optional readbacks.  Each
# result is a single /dev/kmsg line so boot diagnostics retain command status.

BUS=2
ADDR=0x25
REG=0x2a

log_result() {
    echo "blink_wifi: $*" > /dev/kmsg
}

write_led() {
    value="$1"
    /sbin/i2cset -y "$BUS" "$ADDR" "$REG" "$value"
    status=$?
    log_result "i2cset bus=$BUS addr=$ADDR reg=$REG value=$value status=$status"
    return "$status"
}

read_led() {
    if [ ! -x /sbin/i2cget ]; then
        log_result "i2cget unavailable bus=$BUS addr=$ADDR reg=$REG"
        return 0
    fi

    value=$(/sbin/i2cget -y "$BUS" "$ADDR" "$REG" 2>/dev/null)
    status=$?
    log_result "i2cget bus=$BUS addr=$ADDR reg=$REG value=${value:-unavailable} status=$status"
    return 0
}

log_result "start bus=$BUS addr=$ADDR reg=$REG"
write_led 0x01 || exit $?
sleep 1
read_led
write_led 0x00 || exit $?
read_led
sync
log_result "complete status=0"
exit 0
