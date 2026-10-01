#!/usr/bin/env python3
"""Regression checks for the state-driven yellow Wi-Fi LED integration.

The canonical Android/Buildroot checkout is in WSL, so tests apply the
idempotent patch to fresh Windows mirrors in a temporary directory. This
catches source-layout drift and verifies that no scan callback is involved.
"""

import importlib.util
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WIFI_MIRROR = ROOT / "third_party/frameworks/base/services/java/com/android/server/WifiService.java"
INIT_MIRROR = ROOT / "sdcard/linux/android/etc/init.rc"


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "wifi_led_patcher", ROOT / "scripts/patch_wifi_led_state.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    assert WIFI_MIRROR.is_file(), WIFI_MIRROR
    assert INIT_MIRROR.is_file(), INIT_MIRROR
    service_before = WIFI_MIRROR.read_text()
    fresh_service = """package com.android.server;

import android.os.Process;

class WifiService {
    private int mWifiState;

    public boolean startScan(boolean forceActive) {
        return true;
    }

    WifiService() {
        mWifiState = WIFI_STATE_DISABLED;
        boolean wifiEnabled = getPersistedWifiEnabled();
    }

    private boolean getPersistedWifiEnabled() {
        return false;
    }

    private boolean setWifiEnabledBlocking(boolean enable, boolean persist, int uid) {
        final int eventualWifiState = enable ? WIFI_STATE_ENABLED : WIFI_STATE_DISABLED;
        if (mWifiState == eventualWifiState) {
            return true;
        }
        setWifiEnabledState(enable ? WIFI_STATE_ENABLING : WIFI_STATE_DISABLING, uid);

        if (enable) {
            if (!WifiNative.loadDriver()) {
                Log.e(TAG, "Failed to load Wi-Fi driver.");
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
                return false;
            }
            if (!WifiNative.startSupplicant()) {
                WifiNative.unloadDriver();
                Log.e(TAG, "Failed to start supplicant daemon.");
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
                return false;
            }
        } else {
            if (!WifiNative.stopSupplicant()) {
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
                return false;
            }
            if (!WifiNative.unloadDriver()) {
                setWifiEnabledState(WIFI_STATE_UNKNOWN, uid);
                return false;
            }
        }

        if (persist) {
            persistWifiEnabled(enable);
        }
        setWifiEnabledState(eventualWifiState, uid);
        return true;
    }

    private void setWifiEnabledState(int wifiState, int uid) {
    }

    private void updateWifiState() {
        boolean wifiEnabled = getPersistedWifiEnabled();
    }
}
"""
    init_before = INIT_MIRROR.read_text()
    # The fresh fixture deliberately has a second persisted-state lookup in
    # updateWifiState(); a broad getter-only replacement would patch the wrong
    # method or abort. The real mirror is checked separately below.
    assert fresh_service.count("boolean wifiEnabled = getPersistedWifiEnabled();") == 2
    patcher = load_patcher()

    # Exercise fresh application with an explicit unpatched fixture. The
    # deployed mirror is allowed to be current; in that case its patched LED
    # hunk is reversed in memory only, while all unrelated init content stays.
    fresh_init = init_before
    if patcher.INIT_MARKER in fresh_init:
        new_boot = (
            "    # N3DS_WIFI_LED_INIT_STATE: initialize OFF, then let WifiService\n"
            "    # drive ON/OFF through the property actions below. Never blink here:\n"
            "    # scanning, association, and disconnected idle are still Wi-Fi ON.\n"
            "    chmod 0666 /dev/i2c-2\n"
            "    setprop sys.wifi.led off\n"
        )
        old_boot = (
            "    # The MCU (including its LED child at 0x25) is on controller 2\n"
            "    # (/dev/i2c-2, Linux device name 2-0025), not controller 1.\n"
            "    chmod 0666 /dev/i2c-2\n"
            "    start blink_wifi\n"
        )
        assert new_boot in fresh_init
        fresh_init = fresh_init.replace(new_boot, old_boot, 1)
        service_start = fresh_init.index(
            "# N3DS_WIFI_LED_INIT_STATE: each transition is a short, privileged"
        )
        fresh_init = fresh_init[:service_start] + (
            "service blink_wifi /etc/blink_wifi.sh\n"
            "    class default\n"
            "    oneshot\n"
            "    user root\n"
            "    group root\n"
        )
    assert "start blink_wifi" in fresh_init
    assert "service blink_wifi /etc/blink_wifi.sh" in fresh_init
    scan_method_count = fresh_service.count("public boolean startScan(")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        patcher.WIFI_SERVICE = temp / "WifiService.java"
        patcher.INIT_RC = temp / "init.rc"
        patcher.LED_SCRIPT = temp / "wifi_led_state.sh"
        patcher.WIFI_SERVICE.write_text(fresh_service)
        patcher.INIT_RC.write_text(fresh_init)

        patcher.main()
        first_service = patcher.WIFI_SERVICE.read_text()
        first_init = patcher.INIT_RC.read_text()
        first_script = patcher.LED_SCRIPT.read_text()
        patcher.main()
        assert first_service == patcher.WIFI_SERVICE.read_text()
        assert first_init == patcher.INIT_RC.read_text()
        assert first_script == patcher.LED_SCRIPT.read_text()

    # Separately verify the current deployed mirror, which may already have
    # the init/script half of the change, is accepted and remains idempotent.
    if patcher.INIT_MARKER in init_before:
        assert "start blink_wifi" not in init_before
        assert "service blink_wifi " not in init_before
        deployed_script = ROOT / "sdcard/linux/android/etc/wifi_led_state.sh"
        assert deployed_script.is_file()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            patcher.WIFI_SERVICE = temp / "WifiService.java"
            patcher.INIT_RC = temp / "init.rc"
            patcher.LED_SCRIPT = temp / "wifi_led_state.sh"
            patcher.WIFI_SERVICE.write_text(service_before)
            patcher.INIT_RC.write_text(init_before)
            patcher.LED_SCRIPT.write_text(deployed_script.read_text())
            patcher.main()
            first_current = (
                patcher.WIFI_SERVICE.read_text(),
                patcher.INIT_RC.read_text(),
                patcher.LED_SCRIPT.read_text(),
            )
            patcher.main()
            assert first_current == (
                patcher.WIFI_SERVICE.read_text(),
                patcher.INIT_RC.read_text(),
                patcher.LED_SCRIPT.read_text(),
            )

    service = first_service
    init = first_init
    script = first_script

    assert service.count("N3DS_WIFI_LED_STATE") >= 3
    assert "import android.os.SystemProperties;" in service
    assert 'SystemProperties.set("sys.wifi.led", state);' in service
    enable = service.index("if (enable) {\n            setWifiLedState(true);")
    enabling = service.index(
        "setWifiEnabledState(enable ? WIFI_STATE_ENABLING : WIFI_STATE_DISABLING, uid);"
    )
    load_driver = service.index("WifiNative.loadDriver()", enabling)
    assert enable < enabling < load_driver
    assert service.count("setWifiLedState(false);") == 4
    startup = service.index("restarted system_server begins from the")
    assert service.index("setWifiLedState(false);", startup) < enabling
    assert service.count("boolean wifiEnabled = getPersistedWifiEnabled();") == fresh_service.count(
        "boolean wifiEnabled = getPersistedWifiEnabled();"
    )
    update_state = service.index("private void updateWifiState()")
    assert "setWifiLedState(false);" not in service[update_state:]
    driver_fail = service.index("Failed to load Wi-Fi driver")
    supplicant_fail = service.index("Failed to start supplicant daemon")
    completed_disable = service.index(
        "// N3DS_WIFI_LED_STATE: turn OFF only after stop/unload succeeded."
    )
    assert driver_fail < service.index("setWifiLedState(false);", driver_fail)
    assert supplicant_fail < service.index("setWifiLedState(false);", supplicant_fail)
    unload = service.index("WifiNative.unloadDriver()", service.index("} else {"))
    assert unload < completed_disable
    assert scan_method_count == service.count("public boolean startScan(")

    assert "N3DS_WIFI_LED_INIT_STATE" in init
    assert "start blink_wifi" not in init
    assert "service blink_wifi " not in init
    assert "setprop sys.wifi.led off" in init
    assert "on property:sys.wifi.led=on" in init
    assert "start wifi_led_on" in init
    assert "on property:sys.wifi.led=off" in init
    assert "start wifi_led_off" in init
    assert "on property:sys.powerctl=*" in init
    assert "on property:sys.shutdown.requested=*" in init
    assert "service wifi_led_on /etc/wifi_led_state.sh on" in init
    assert "service wifi_led_off /etc/wifi_led_state.sh off" in init

    assert "N3DS_WIFI_LED_I2C_STATE" in script
    assert "BUS=2" in script
    assert "ADDR=0x25" in script
    assert "REG=0x2a" in script
    assert "on)" in script and "VALUE=0x01" in script
    assert "off)" in script and "VALUE=0x00" in script
    assert "exit 2" in script
    assert "sleep" not in script
    assert script.startswith("#!/bin/sh")
    print("wifi_led_state: PASS")


if __name__ == "__main__":
    main()
