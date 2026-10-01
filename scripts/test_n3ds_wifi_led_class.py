#!/usr/bin/env python3
"""Regression checks for kernel-owned yellow WiFi LED state."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
LINUX = Path(f"{A3DS_ROOT}/third_party/linux")


def main() -> None:
    driver = (LINUX / "drivers/platform/nintendo3ds/mcu/wifi_led.c").read_text()
    dts = (LINUX / "arch/arm/boot/dts/nintendo3ds.dtsi").read_text()
    make = (LINUX / "drivers/platform/nintendo3ds/Makefile").read_text()
    service = Path(
        f"{A3DS_ROOT}/third_party/frameworks/base/services/java/com/android/server/WifiService.java"
    ).read_text()
    script = (PROJECT / "sdcard/linux/android/etc/wifi_led_state.sh").read_text()
    assert "N3DS_WIFI_LED_REGMAP_STATE" in driver
    assert 'led->cdev.name = "n3ds-wifi";' in driver
    assert "regmap_write(led->map, led->reg, brightness ? 1 : 0)" in driver
    assert 'compatible = "nintendo,3dsmcu-wifi-led";' in dts
    assert "reg = <0x2A>;" in dts
    assert "mcu/wifi_led.o" in make
    assert "N3DS_WIFI_LED_SCAN_REASSERT" in service
    assert "N3DS_WIFI_LED_SCAN_REASSERT enabled" in service
    assert "WifiManager.SCAN_RESULTS_AVAILABLE_ACTION" in service
    assert "if (mWifiState == WIFI_STATE_ENABLED)" in service
    assert "LED=/sys/class/leds/n3ds-wifi/brightness" in script
    assert "/sbin/i2cset" not in script and "/usr/sbin/i2cset" not in script
    print("n3ds_wifi_led_class: PASS")


if __name__ == "__main__":
    main()
