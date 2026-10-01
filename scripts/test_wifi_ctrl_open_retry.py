#!/usr/bin/env python3
"""Pin the bounded wait for wpa_supplicant's control socket (W11).

`init.svc.wpa_supplicant=running` is published when init forks the service, not
when the socket exists, so the single-shot open in wifi_connect_to_supplicant()
raced and lost on hardware.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/libhardware_legacy/wifi/wifi.c")
APP_PROCESS = Path(f"{A3DS_ROOT}/sdcard/linux/android/system/bin/"
                   "app_process")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_wifi_ctrl_open_retry", HERE / "patch_wifi_ctrl_open_retry.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from wifi.c")
    check(patcher.patch_text(text) == text, "patcher is not idempotent")

    check("static struct wpa_ctrl *wifi_ctrl_open_retry(" in text,
          "wifi_ctrl_open_retry() helper missing")
    check("ctrl_conn = wifi_ctrl_open_retry(ifname, sizeof(ifname));" in text,
          "wifi_connect_to_supplicant() does not use the retrying open")

    # The wait must be bounded, and long enough to beat the observed race.
    tries = re.search(r"#define WIFI_CTRL_OPEN_TRIES\s+(\d+)", text)
    delay = re.search(r"#define WIFI_CTRL_OPEN_DELAY_US\s+(\d+)", text)
    check(tries is not None and delay is not None,
          "the retry bounds are no longer compile-time constants")
    if tries and delay:
        total_ms = int(tries.group(1)) * int(delay.group(1)) // 1000
        check(2000 <= total_ms <= 15000,
              f"total wait is {total_ms} ms; it must beat the supplicant "
              f"startup race without stalling Wi-Fi enable")

    helper = text[text.index("static struct wpa_ctrl *wifi_ctrl_open_retry("):
                  text.index("int wifi_connect_to_supplicant()")]

    # A supplicant that died must not cost the full wait.
    check('strcmp(supp_status, "running") != 0' in helper,
          "the retry loop never rechecks that the supplicant is still running")
    check("Supplicant stopped while waiting for its control socket" in helper,
          "the early-give-up path is silent")

    # IFACE_DIR is created by the supplicant, so it must be retested each pass.
    check(helper.count("access(IFACE_DIR, F_OK) == 0") == 1
          and helper.index("access(IFACE_DIR, F_OK) == 0")
          > helper.index("for (attempt = 0;"),
          "the socket path is computed outside the retry loop; a first attempt "
          "before the supplicant creates IFACE_DIR would poison every retry")

    # The old single-shot open must be gone from the caller.
    caller = text[text.index("int wifi_connect_to_supplicant()"):]
    caller = caller[:caller.index("\nint wifi_send_command")]
    check("ctrl_conn = wpa_ctrl_open(ifname);" not in caller,
          "wifi_connect_to_supplicant() still opens ctrl_conn without retrying")
    check("monitor_conn = wpa_ctrl_open(ifname);" in caller,
          "monitor_conn open was lost")

    # No busy-wait: there must be a sleep on every retry pass.
    check("usleep(WIFI_CTRL_OPEN_DELAY_US);" in helper,
          "the retry loop does not sleep between attempts")

    # libhardware_legacy is statically linked into app_process.
    if not APP_PROCESS.is_file():
        failures.append(f"app_process not found at {APP_PROCESS}")
    else:
        blob = APP_PROCESS.read_bytes()
        check(b"Supplicant stopped while waiting for its control socket" in blob,
              "deployed app_process predates the ctrl-socket retry patch")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_wifi_ctrl_open_retry: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
