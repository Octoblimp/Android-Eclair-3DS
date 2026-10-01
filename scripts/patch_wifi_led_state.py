#!/usr/bin/env python3
"""Make the yellow Wi-Fi LED follow the radio enable state.

The old overlay starts `blink_wifi` during boot. That script writes ON,
sleeps, then writes OFF, so it is a diagnostic activity blink rather than an
indicator of Wi-Fi state. The authoritative radio transition lives in
WifiService: it knows when an enable request enters ENABLING, when startup
fails, and when a disable has actually completed. This patch exports those
transitions through a private Android property; init invokes the small I2C
setter for each transition.

The canonical checkout is in WSL and is deliberately patched here instead of
editing the generated SD tree. The script is idempotent and fails closed if
the source layout is not the expected one.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
WIFI_SERVICE = ROOT / (
    "third_party/frameworks/base/services/java/com/android/server/WifiService.java"
)
INIT_RC = ROOT / (
    "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc"
)
LED_SCRIPT = ROOT / (
    "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/wifi_led_state.sh"
)

SERVICE_MARKER = "N3DS_WIFI_LED_STATE"
INIT_MARKER = "N3DS_WIFI_LED_INIT_STATE"
SCRIPT_MARKER = "N3DS_WIFI_LED_I2C_STATE"


LED_SCRIPT_TEXT = r'''#!/bin/sh
# N3DS_WIFI_LED_I2C_STATE: the yellow Wi-Fi indicator is a state LED, not a
# scan/activity blink. The MCU LED child is on Linux I2C bus 2.

BUS=2
ADDR=0x25
REG=0x2a

case "$1" in
    on)
        VALUE=0x01
        ;;
    off)
        VALUE=0x00
        ;;
    *)
        echo "wifi_led_state: invalid state '$1'" > /dev/kmsg
        exit 2
        ;;
esac

/sbin/i2cset -y "$BUS" "$ADDR" "$REG" "$VALUE"
STATUS=$?
echo "wifi_led_state: state=$1 bus=$BUS addr=$ADDR reg=$REG value=$VALUE status=$STATUS" > /dev/kmsg
if [ "$STATUS" -ne 0 ]; then
    exit "$STATUS"
fi
sync
exit 0
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_wifi_service() -> None:
    text = WIFI_SERVICE.read_text()
    if SERVICE_MARKER not in text:
        text = replace_once(
            text,
            "import android.os.Process;\n",
            "import android.os.Process;\nimport android.os.SystemProperties;\n",
            "WifiService SystemProperties import",
        )

        text = replace_once(
            text,
            """        mWifiState = WIFI_STATE_DISABLED;
        boolean wifiEnabled = getPersistedWifiEnabled();
""",
            """        mWifiState = WIFI_STATE_DISABLED;
        boolean wifiEnabled = getPersistedWifiEnabled();

        // N3DS_WIFI_LED_STATE: a restarted system_server begins from the
        // disabled state; clear a stale indicator before restoring Wi-Fi.
        if (!wifiEnabled) {
            setWifiLedState(false);
        }
""",
            "WifiService startup LED reset",
        )

        text = replace_once(
            text,
            """        setWifiEnabledState(enable ? WIFI_STATE_ENABLING : WIFI_STATE_DISABLING, uid);

        if (enable) {
""",
            """        // N3DS_WIFI_LED_STATE: enabling is already a user-visible ON state.
        // Keep the LED on through scanning, association, and disconnected idle;
        // only a completed disable or a failed enable turns it back off.
        if (enable) {
            setWifiLedState(true);
        }
        setWifiEnabledState(enable ? WIFI_STATE_ENABLING : WIFI_STATE_DISABLING, uid);

        if (enable) {
""",
            "WifiService enable transition",
        )

        text = replace_once(
            text,
            """                Log.e(TAG, "Failed to load Wi-Fi driver.");
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
""",
            """                Log.e(TAG, "Failed to load Wi-Fi driver.");
                setWifiLedState(false);
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
""",
            "WifiService driver failure LED transition",
        )
        text = replace_once(
            text,
            """                Log.e(TAG, "Failed to start supplicant daemon.");
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
""",
            """                Log.e(TAG, "Failed to start supplicant daemon.");
                setWifiLedState(false);
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
""",
            "WifiService supplicant failure LED transition",
        )

        text = replace_once(
            text,
            """        if (persist) {
            persistWifiEnabled(enable);
        }
        setWifiEnabledState(eventualWifiState, uid);
""",
            """        if (persist) {
            persistWifiEnabled(enable);
        }
        // N3DS_WIFI_LED_STATE: turn OFF only after stop/unload succeeded.
        // A failed disable reports UNKNOWN and deliberately leaves the LED ON.
        if (!enable) {
            setWifiLedState(false);
        }
        setWifiEnabledState(eventualWifiState, uid);
""",
            "WifiService completed disable LED transition",
        )

        anchor = """    private void setWifiEnabledState(int wifiState, int uid) {
"""
        helper = """    private void setWifiLedState(boolean enabled) {
        // N3DS_WIFI_LED_STATE: init owns the hardware I2C transaction; this
        // property keeps the framework transition independent of scan events.
        final String state = enabled ? "on" : "off";
        SystemProperties.set("sys.wifi.led", state);
        Log.i(TAG, "N3DS_WIFI_LED_STATE " + state);
    }

"""
        text = replace_once(text, anchor, helper + anchor, "WifiService LED helper anchor")

    required = (
        SERVICE_MARKER,
        'SystemProperties.set("sys.wifi.led", state);',
        "setWifiLedState(true);",
        "setWifiLedState(false);",
        "restarted system_server begins from the",
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError(f"WifiService LED patch incomplete: {missing}")
    WIFI_SERVICE.write_text(text)


def patch_init() -> None:
    text = INIT_RC.read_text()
    if INIT_MARKER not in text:
        text = replace_once(
            text,
            """    # The MCU (including its LED child at 0x25) is on controller 2
    # (/dev/i2c-2, Linux device name 2-0025), not controller 1.
    chmod 0666 /dev/i2c-2
    start blink_wifi
""",
            """    # N3DS_WIFI_LED_INIT_STATE: initialize OFF, then let WifiService
    # drive ON/OFF through the property actions below. Never blink here:
    # scanning, association, and disconnected idle are still Wi-Fi ON.
    chmod 0666 /dev/i2c-2
    setprop sys.wifi.led off
""",
            "init boot Wi-Fi LED block",
        )

        old_service = """service blink_wifi /etc/blink_wifi.sh
    class default
    oneshot
    user root
    group root
"""
        new_services = """# N3DS_WIFI_LED_INIT_STATE: each transition is a short, privileged
# I2C transaction. Both services are oneshot and disabled; property actions
# below start them on radio enable/disable and during shutdown.
service wifi_led_on /etc/wifi_led_state.sh on
    class default
    disabled
    oneshot
    user root
    group root

service wifi_led_off /etc/wifi_led_state.sh off
    class default
    disabled
    oneshot
    user root
    group root

on property:sys.wifi.led=on
    start wifi_led_on

on property:sys.wifi.led=off
    start wifi_led_off

# Leave the hardware in the safe OFF state during orderly shutdown. The
# radio path normally turns it off first; these triggers cover power-menu and
# framework shutdown paths that do not call WifiService.setWifiEnabled(false).
on property:sys.powerctl=*
    start wifi_led_off

on property:sys.shutdown.requested=*
    start wifi_led_off
"""
        text = replace_once(text, old_service, new_services, "init blink_wifi service")

    required = (
        INIT_MARKER,
        "on property:sys.wifi.led=on",
        "on property:sys.wifi.led=off",
        "service wifi_led_on /etc/wifi_led_state.sh on",
        "service wifi_led_off /etc/wifi_led_state.sh off",
        "on property:sys.powerctl=*",
        "on property:sys.shutdown.requested=*",
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError(f"init.rc Wi-Fi LED patch incomplete: {missing}")
    INIT_RC.write_text(text)


def patch_script() -> None:
    if LED_SCRIPT.exists():
        text = LED_SCRIPT.read_text()
        # The later kernel-regmap integration intentionally replaces this
        # bootstrap raw-I2C setter.  Accept that final state so the complete
        # patch sequence remains idempotent on an already-built tree.
        if "N3DS_WIFI_LED_REGMAP_STATE" in text:
            LED_SCRIPT.chmod(0o755)
            return
        if SCRIPT_MARKER not in text:
            raise RuntimeError(f"existing LED script lacks {SCRIPT_MARKER}: {LED_SCRIPT}")
        if text != LED_SCRIPT_TEXT:
            raise RuntimeError(f"existing LED script differs from expected state setter: {LED_SCRIPT}")
        LED_SCRIPT.chmod(0o755)
        return
    LED_SCRIPT.write_text(LED_SCRIPT_TEXT)
    LED_SCRIPT.chmod(0o755)


def main() -> None:
    for path in (WIFI_SERVICE, INIT_RC):
        if not path.exists():
            raise SystemExit(f"missing canonical source: {path}")
    patch_wifi_service()
    patch_init()
    patch_script()
    print("patch_wifi_led_state: WifiService/init/I2C setter installed")


if __name__ == "__main__":
    main()
