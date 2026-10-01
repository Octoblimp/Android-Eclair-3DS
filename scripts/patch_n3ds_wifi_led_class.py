#!/usr/bin/env python3
"""Use the MCU regmap/LED class for the yellow WiFi state indicator."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path
import shutil


PROJECT = Path(__file__).resolve().parents[1]
LINUX = Path(f"{A3DS_ROOT}/third_party/linux")
FRAMEWORK = Path(f"{A3DS_ROOT}/third_party/frameworks/base")
OVERLAY = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/rootfs_overlay")
DRIVER_TEMPLATE = PROJECT / "content/kernel/n3ds_wifi_led.c"
DRIVER = LINUX / "drivers/platform/nintendo3ds/mcu/wifi_led.c"
MAKEFILE = LINUX / "drivers/platform/nintendo3ds/Makefile"
DTS = LINUX / "arch/arm/boot/dts/nintendo3ds.dtsi"
SERVICE_PATHS = (
    FRAMEWORK / "services/java/com/android/server/WifiService.java",
    PROJECT / "third_party/frameworks/base/services/java/com/android/server/WifiService.java",
)
SCRIPT_PATHS = (
    OVERLAY / "etc/wifi_led_state.sh",
    PROJECT / "sdcard/linux/android/etc/wifi_led_state.sh",
)

MARKER = "N3DS_WIFI_LED_REGMAP_STATE"
REASSERT_MARKER = "N3DS_WIFI_LED_SCAN_REASSERT"

SCRIPT = r'''#!/bin/sh
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
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_kernel() -> None:
    shutil.copyfile(DRIVER_TEMPLATE, DRIVER)

    make = MAKEFILE.read_text()
    line = "obj-$(CONFIG_CTR_MCULED)\t+= mcu/wifi_led.o\n"
    if line not in make:
        anchor = "obj-$(CONFIG_CTR_MCULED)\t+= mcu/led.o\n"
        make = replace_once(make, anchor, anchor + line, "WiFi LED Makefile")
        MAKEFILE.write_text(make)

    dts = DTS.read_text()
    if 'compatible = "nintendo,3dsmcu-wifi-led";' not in dts:
        anchor = '''\t\t\t\tmcu-led@2d {
\t\t\t\t\tcompatible = "nintendo,3dsmcu-led";
\t\t\t\t\treg = <0x2D>;
\t\t\t\t};
'''
        node = '''
\t\t\t\t/* N3DS_WIFI_LED_REGMAP_STATE: dedicated yellow indicator. */
\t\t\t\tmcu-wifi-led@2a {
\t\t\t\t\tcompatible = "nintendo,3dsmcu-wifi-led";
\t\t\t\t\treg = <0x2A>;
\t\t\t\t};
'''
        dts = replace_once(dts, anchor, node + "\n" + anchor, "WiFi LED DT node")
        DTS.write_text(dts)


def patch_service(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text()
    if REASSERT_MARKER in text:
        if "N3DS_WIFI_LED_SCAN_REASSERT enabled" not in text:
            text = replace_once(
                text,
                """                if (mWifiState == WIFI_STATE_ENABLED) {
                    setWifiLedState(true);
                }
""",
                """                if (mWifiState == WIFI_STATE_ENABLED) {
                    Log.i(TAG, "N3DS_WIFI_LED_SCAN_REASSERT enabled");
                    setWifiLedState(true);
                }
""",
                "scan LED reassert diagnostic",
            )
            path.write_text(text)
        return
    if REASSERT_MARKER not in text:
        receiver = '''            if (action.equals(Intent.ACTION_SCREEN_ON)) {
'''
        replacement = '''            if (action.equals(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION)) {
                /* N3DS_WIFI_LED_SCAN_REASSERT: Nintendo firmware owns the LED
                 * during RF scan activity and clears it at completion.  Reapply
                 * the authoritative framework enabled state afterward. */
                if (mWifiState == WIFI_STATE_ENABLED) {
                    Log.i(TAG, "N3DS_WIFI_LED_SCAN_REASSERT enabled");
                    setWifiLedState(true);
                }
                return;
            } else if (action.equals(Intent.ACTION_SCREEN_ON)) {
'''
        text = replace_once(text, receiver, replacement, "scan LED reassert receiver")
        register = '''        intentFilter.addAction(Intent.ACTION_SCREEN_ON);
'''
        text = replace_once(
            text,
            register,
            '''        intentFilter.addAction(WifiManager.SCAN_RESULTS_AVAILABLE_ACTION);
''' + register,
            "scan LED reassert registration",
        )
        path.write_text(text)


def main() -> None:
    for path in (LINUX, FRAMEWORK, OVERLAY, DRIVER_TEMPLATE):
        if not path.exists():
            raise SystemExit(f"missing WiFi LED prerequisite: {path}")
    patch_kernel()
    for path in SERVICE_PATHS:
        patch_service(path)
    for path in SCRIPT_PATHS:
        if path.parent.is_dir():
            path.write_text(SCRIPT)
            path.chmod(0o755)
    print("patch_n3ds_wifi_led_class: regmap LED and scan reassert installed")


if __name__ == "__main__":
    main()
