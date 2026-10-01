#!/usr/bin/env python3
"""N3DS_WIFI_KEEP_RADIO_POWERED.

wifi_unload_driver() deliberately keeps ath6kl resident (a module round trip
is fatal on this AR6002 SDIO part) but still cut the MCU radio power line.
The AR6002 holds its BMI-downloaded firmware in RAM, so that power cut wipes
the running target out from under a driver that stays bound with wlan0 still
registered.  The next wifi_load_driver() then sees check_driver_loaded()==1
and wlan0 present, skips insmod entirely and reports
"N3DS_WIFI_DRIVER_LOAD ready interface=wlan0" at attempts=1 -- on a chip with
no firmware.  That is the observed "turned it on, it says scanning, it never
scans" regression: boot takes attempts=23 (a real insmod), the manual
re-enable takes attempts=1 (no insmod at all).

Fix: the MCU power line now only moves when the module actually moves.
"""
from a3ds_paths import A3DS_ROOT
import io
import re
import sys

PATH = f"{A3DS_ROOT}/third_party/libhardware_legacy/wifi/wifi.c"

src = io.open(PATH, encoding="utf-8").read()
orig = src

# ---------------------------------------------------------------- helper ---
helper = '''
/* N3DS_WIFI_KEEP_RADIO_POWERED: the MCU I2C line at 0x25:0x2a is the AR6002's
 * power rail, not a soft "radio off" switch.  The target holds the firmware
 * downloaded over BMI in its own RAM, so dropping this line destroys the
 * running target and resets the SDIO function.  ath6kl stays bound and wlan0
 * stays registered across that, which is precisely the state
 * check_driver_loaded() cannot distinguish from a healthy load -- so the next
 * wifi_load_driver() skips insmod and hands the framework a dead radio that
 * accepts a scan request and never answers it.
 *
 * The line is therefore only ever moved together with the module itself.  The
 * property is a breadcrumb so a load can recognise a radio that some other
 * path (an older build, a forced unload) power-cycled underneath a resident
 * module and force the reload that is the only possible recovery.
 */
static void wifi_radio_power(int on) {
    system(on ? "i2cset -y 1 0x25 0x2a 0x01" : "i2cset -y 1 0x25 0x2a 0x00");
    property_set("n3ds.wifi.radio_power", on ? "1" : "0");
}

'''

anchor = "static int check_driver_loaded() {"
if "wifi_radio_power" not in src:
    assert anchor in src, "check_driver_loaded anchor missing"
    src = src.replace(anchor, helper.lstrip("\n") + anchor, 1)

# ------------------------------------------------------------ load path ---
src = src.replace(
    '    LOGI("N3DS_WIFI_DRIVER_LOAD begin path=%s", module_path);\n'
    '    system("i2cset -y 1 0x25 0x2a 0x01");\n',
    '    LOGI("N3DS_WIFI_DRIVER_LOAD begin path=%s", module_path);\n'
    '    wifi_radio_power(1);\n',
    1)

# Every remaining bare power-down inside wifi_load_driver()'s error paths.
src = src.replace('        system("i2cset -y 1 0x25 0x2a 0x00");\n',
                  '        wifi_radio_power(0);\n')

# Recovery for a resident module whose radio was power-cycled underneath it.
stale = '''    if (check_driver_loaded() && access(WIFI_DRIVER_INTERFACE_PATH, F_OK) != 0) {
        LOGW("N3DS_WIFI_DRIVER_LOAD stale_module_no_interface, forcing reload");
        rmmod(DRIVER_MODULE_NAME);
    }
'''
stale_new = '''    if (check_driver_loaded() && access(WIFI_DRIVER_INTERFACE_PATH, F_OK) != 0) {
        LOGW("N3DS_WIFI_DRIVER_LOAD stale_module_no_interface, forcing reload");
        rmmod(DRIVER_MODULE_NAME);
    }

    /* N3DS_WIFI_DEAD_TARGET_RELOAD: wlan0 present proves nothing once the
     * rail has been cut -- the firmware lives in target RAM.  Only a module
     * round trip can re-run BMI, so take the unreliable reload over handing
     * the framework an interface that will never answer a scan. */
    if (check_driver_loaded()) {
        char powered[PROPERTY_VALUE_MAX];
        property_get("n3ds.wifi.radio_power", powered, "1");
        if (strcmp(powered, "1") != 0) {
            LOGW("N3DS_WIFI_DRIVER_LOAD radio was power-cycled while resident; "
                 "firmware is gone, forcing reload");
            rmmod(DRIVER_MODULE_NAME);
        }
    }
'''
assert stale in src, "stale-module block missing"
src = src.replace(stale, stale_new, 1)

# ---------------------------------------------------------- unload path ---
old_unload = '''        if (check_driver_loaded() && rmmod(DRIVER_MODULE_NAME) != 0) {
            property_set(DRIVER_PROP_NAME, "failed");
            return -1;
        }
    } else {
        LOGI("N3DS_WIFI_DRIVER_UNLOAD keeping ath6kl resident (reload is fatal "
             "on AR6002 SDIO); powering radio down only");
    }
    system("i2cset -y 1 0x25 0x2a 0x00");
'''
new_unload = '''        if (check_driver_loaded() && rmmod(DRIVER_MODULE_NAME) != 0) {
            property_set(DRIVER_PROP_NAME, "failed");
            return -1;
        }
        /* The module is out, so nothing is bound to the target any more and
         * the rail can go down.  The next load re-runs BMI from scratch. */
        wifi_radio_power(0);
    } else {
        /* N3DS_WIFI_KEEP_RADIO_POWERED: see wifi_radio_power().  Cutting the
         * rail here is what broke the manual re-enable -- the module stayed
         * resident over a target that had lost its firmware, so the next load
         * skipped insmod (attempts=1 instead of the boot path's attempts=23)
         * and Settings sat on "scanning" forever. */
        LOGI("N3DS_WIFI_DRIVER_UNLOAD keeping ath6kl resident and powered "
             "(reload is fatal on AR6002 SDIO, and the rail holds its "
             "firmware); interface stays up for the next enable");
    }
'''
assert old_unload in src, "unload block missing"
src = src.replace(old_unload, new_unload, 1)

# The stale block's doc comment above wifi_unload_driver() promised the radio
# would still be powered down; keep the comment honest.
src = src.replace(
    ''' * attempt -- the part that actually can succeed on a retry. The radio itself
 * is still powered down through the MCU I2C line below, so an "off" toggle
 * still stops drawing power.''',
    ''' * attempt -- the part that actually can succeed on a retry. The MCU rail is
 * deliberately left up in that case: it is the target's power supply, not a
 * soft radio switch, and dropping it wipes the BMI-loaded firmware out from
 * under the still-bound driver (N3DS_WIFI_KEEP_RADIO_POWERED).''',
    1)

if src == orig:
    sys.stderr.write("no changes made\\n")
    sys.exit(1)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + PATH)
