#!/usr/bin/env python3
"""Pin the content-selected wpa_supplicant key log (W10).

The SD-card supplicant log is a tail of a rotated live log, so it only ever
covers the last ~100 s of a boot.  Both associations in the 2026-09-01 capture
happened before that window and were lost.  The key log is selected by content
instead, so it covers the whole boot.

This test runs the real awk program out of the shipped script against sample
supplicant output, so a regex that silently matches nothing cannot pass.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVERLAY = Path(f"{A3DS_ROOT}/third_party/buildroot/board/"
               "nintendo3ds/rootfs_overlay/etc/wpa_supplicant_diag.sh")
DEPLOYED = Path(f"{A3DS_ROOT}/sdcard/linux/android/etc/"
                "wpa_supplicant_diag.sh")

# Lines that must survive, drawn verbatim from the 2026-09-01 capture, plus the
# success-path lines no capture has contained yet.
MUST_KEEP = [
    "nl80211: MLME connect failed: ret=-114 (Operation already in progress)",
    "wlan0: Trying to associate with 8c:dd:0b:00:53:c8 (SSID='HomeWifi' freq=2437 MHz)",
    "wlan0: Associated with 8c:dd:0b:00:53:c8",
    "wlan0: CTRL-EVENT-CONNECTED - Connection to 8c:dd:0b:00:53:c8 completed",
    "wlan0: State: ASSOCIATING -> ASSOCIATED",
    "WPA: RX EAPOL from 8c:dd:0b:00:53:c8",
    "RSN: PMKID from Authenticator",
    "wlan0: Authentication with 8c:dd:0b:00:53:c8 timed out.",
    "wpa_driver_nl80211_disconnect(reason_code=2)",
    "wlan0: Added BSSID 8c:dd:0b:00:53:c8 into ignore list, ignoring for 10 seconds",
    "wlan0: Consecutive connection failures: 4",
    "wlan0: Association request to the driver failed",
    "SME: Trying to authenticate with 8c:dd:0b:00:53:c8",
    "wlan0: CTRL-EVENT-DISCONNECTED bssid=8c:dd:0b:00:53:c8 reason=3",
]

# Lines that must not fill the file up.  These are the bulk of `-d` output.
MUST_DROP = [
    "nl80211: Received scan results (12 BSSes)",
    "BSS: Add new id 3 BSSID 8c:dd:0b:00:53:c8 SSID 'HomeWifi' freq 2437",
    "  hexdump(len=32): 01 02 03 04 05 06 07 08",
    "wlan0: Cancelling scan request",
    "TDLS: Remove peers on interface deinit",
]

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_wpa_supplicant_key_log",
        HERE / "patch_wpa_supplicant_key_log.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def shell_value(text, name):
    match = re.search(r"^%s='([^']*)'$" % re.escape(name), text, re.M)
    if match:
        return match.group(1)
    match = re.search(r"^%s=(\S+)$" % re.escape(name), text, re.M)
    return match.group(1) if match else None


def awk_program(text):
    """Extract the awk program body from the shipped script."""
    start = text.index("-v bytes=\"$start_bytes\" '")
    start = text.index("'", start + len("-v bytes=\"$start_bytes\" ")) + 1
    end = text.index("}' &", start) + 1
    return text[start:end]


def run_awk(program, key_re, key_max, lines):
    """Run the real awk program and return (live_lines, key_lines)."""
    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "live"
        key_path = Path(tmp) / "key"
        rotate_path = Path(tmp) / "rotate"
        proc = subprocess.run(
            ["awk",
             "-v", f"out_path={out_path}",
             "-v", f"tmp_path={rotate_path}",
             "-v", "max=196608",
             "-v", "keep=131072",
             "-v", f"key_path={key_path}",
             "-v", f"key_max={key_max}",
             "-v", f"key_re={key_re}",
             "-v", "bytes=0",
             program],
            input="\n".join(lines) + "\n",
            text=True, capture_output=True)
        if proc.returncode != 0:
            return None, None, proc.stderr.strip()
        live = out_path.read_text().splitlines() if out_path.exists() else []
        key = key_path.read_text().splitlines() if key_path.exists() else []
        return live, key, ""


def main():
    patcher = load_patcher()
    text = OVERLAY.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from wpa_supplicant_diag.sh")
    check(patcher.patch_text(text) == text, "patcher is not idempotent")

    syntax = subprocess.run(["sh", "-n", str(OVERLAY)], capture_output=True,
                            text=True)
    check(syntax.returncode == 0,
          f"sh -n rejected the script: {syntax.stderr.strip()}")

    # The overlay is canonical and sync_android_to_sdcard.sh pushes it; a
    # drifted SD copy is what actually runs on the device.
    if DEPLOYED.is_file():
        check(DEPLOYED.read_text(encoding="utf-8") == text,
              "the deployed SD copy has drifted from rootfs_overlay/etc; "
              "run sync_android_to_sdcard.sh")
    else:
        failures.append(f"deployed copy not found at {DEPLOYED}")

    key_re = shell_value(text, "KEY_RE")
    key_max = shell_value(text, "KEY_MAX_BYTES")
    check(key_re is not None, "KEY_RE not found")
    check(key_max is not None, "KEY_MAX_BYTES not found")

    check(shell_value(text, "KEY_LOG") == "/mnt/sd/linux/wpa_supplicant.key.log",
          "the key log does not land on the SD card where it can be pulled")

    # The key file must never be rotated -- that is the entire point.
    key_block = text[text.index("snapshot_key()"):text.index("snapshot()\n{")]
    check("tail -c" not in key_block,
          "the key snapshot rotates; the beginning of the boot would be lost")
    check("-gt \"$key_committed\"" in key_block,
          "the key snapshot rewrites the card even when nothing changed")

    # Both snapshot paths must be reached from the TERM/HUP trap too.
    check("snapshot_key" in text[text.index("snapshot()\n{"):],
          "snapshot() does not commit the key log")
    check("trap 'snapshot; exit 143' HUP INT TERM" in text,
          "the final-snapshot trap was lost")

    check('"$KEY"' in text[text.index("rm -f \"$STATUS\""):],
          "the key temp file is not cleaned up")

    # --- the part that cannot be checked by reading: run the real awk ------
    if key_re and key_max:
        program = awk_program(text)
        live, key, err = run_awk(program, key_re, key_max,
                                 MUST_KEEP + MUST_DROP)
        check(not err, f"awk rejected the program: {err}")
        if not err:
            check(len(live) == len(MUST_KEEP) + len(MUST_DROP),
                  f"the live log lost lines: {len(live)} of "
                  f"{len(MUST_KEEP) + len(MUST_DROP)}")
            for line in MUST_KEEP:
                check(line in key, f"key log dropped a needed line: {line!r}")
            for line in MUST_DROP:
                check(line not in key,
                      f"key log kept bulk output: {line!r}")

        # The cap must actually stop the file growing.
        flood = ["wlan0: State: ASSOCIATING -> ASSOCIATED"] * 200
        live, key, err = run_awk(program, key_re, 512, flood)
        check(not err, f"awk rejected the program under flood: {err}")
        if not err:
            size = sum(len(line) + 1 for line in key)
            check(size <= 512 + 128,
                  f"key log cap not enforced: {size} bytes past a 512 cap")
            check(len(key) > 0, "key log cap suppressed everything")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_wpa_supplicant_key_log: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
