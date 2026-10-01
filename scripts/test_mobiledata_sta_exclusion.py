#!/usr/bin/env python3
"""Regression for the Mobile Data station-stack exclusion.

The AR6014 target holds exactly one role at a time.  Before this guard the
soft-AP path committed an AP profile and then lost it about a second later,
because wpa_supplicant was still running and its next station connect drove
``ar6k_cfg80211_connect()``, which forces ``arNetworkType = INFRA_NETWORK``
and replaces the profile the target was holding.  The observable symptom was
``controller_start ok`` followed by a station connect on the AP's own channel
and then ``clients=0`` forever with no beacon visible to any client.

What has to stay true is an ordering, not a message: nothing may hold wlan0
or reload ath6kl between the supplicant stop and the fwmode=2 rebind, and the
supplicant has to be re-armed once the station firmware is back.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc"
          / "mobiledata.sh")
STAGED = ROOT / "sdcard/linux/android/etc/mobiledata.sh"

SETPROP_BODY = r'''key=$1; shift; value=$*
printf 'setprop %s %s\n' "$key" "$value" >> "$MOBILEDATA_EVENTS"
set_prop() {
  tmp="$MOBILEDATA_PROP_FILE.tmp.$$"
  awk -F= -v k="$1" '$1 != k {print}' "$MOBILEDATA_PROP_FILE" 2>/dev/null \
      > "$tmp" || true
  printf '%s=%s\n' "$1" "$2" >> "$tmp"
  mv "$tmp" "$MOBILEDATA_PROP_FILE"
}
set_prop "$key" "$value"
'''

# init reaping the service is what makes the runtime's bounded wait terminate
# on a real device; a "stubborn" fixture omits this to model a supplicant that
# survives its service PID (the diagnostic wrapper runs it inside a pipeline).
CTL_HOOK = r'''case "$key/$value" in
  ctl.stop/wpa_supplicant) set_prop init.svc.wpa_supplicant stopped;;
  ctl.start/wpa_supplicant) set_prop init.svc.wpa_supplicant running;;
esac
'''

GETPROP_BODY = (
    'awk -F= -v k="$1" \'$1 == k {v=substr($0, index($0, "=")+1)} '
    'END {if (v != "") print v}\' "$MOBILEDATA_PROP_FILE" 2>/dev/null'
)


def _shell_path(path: Path) -> str:
    """Render a host path for the Unix shell that executes the fixture."""
    value = str(path)
    if os.name != "nt":
        return value
    cygpath = shutil.which("cygpath")
    if cygpath:
        converted = subprocess.run(
            [cygpath, "-u", value], capture_output=True, text=True, check=False,
        )
        if converted.returncode == 0 and converted.stdout.strip():
            return converted.stdout.strip()
    return value.replace("\\", "/")


def _run(entry, *, supplicant="running", driver_status="ok",
         reloadable=True, stubborn=False):
    """Source the runtime and call one entry point against fixtures.

    Every property write lands in the same event log as the module and
    AP-controller calls, because the ordering between them is the assertion.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        bindir = root / "bin"
        bindir.mkdir()
        props = root / "props"
        events = root / "events"
        recovery_file = root / "wifi_recover"
        recovery_file.write_text("", encoding="utf-8")
        modules_dir = root / "modules"
        modules_dir.mkdir()
        sysmods = root / "sysmods"
        sysmods.mkdir()
        if reloadable:
            (modules_dir / "ath6k_legacy.ko").write_bytes(b"fixture")
            (sysmods / "ath6k_legacy").mkdir()

        def tool(name, body):
            path = bindir / name
            path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
            path.chmod(0o755)

        tool("setprop", SETPROP_BODY + ("" if stubborn else CTL_HOOK))
        tool("getprop", GETPROP_BODY)
        tool("ifconfig", "exit 0")
        tool("rmmod", 'printf "rmmod %s\\n" "$*" >> "$MOBILEDATA_EVENTS"; '
                      'rm -rf "$MOBILEDATA_SYS_MODULE_DIR/ath6k_legacy"; exit 0')
        tool("insmod", 'printf "insmod %s\\n" "$*" >> "$MOBILEDATA_EVENTS"; '
                       'mkdir -p "$MOBILEDATA_SYS_MODULE_DIR/ath6k_legacy"; '
                       'exit 0')
        tool("mobiledata_dhcp", "sleep 2")
        tool("mobiledata_status", "sleep 2")
        # Deterministic: the runtime must decide from init.svc.*, never from a
        # stray wpa_supplicant on the build host.
        tool("pidof", "exit 1")
        tool("busybox", 'printf "busybox %s\\n" "$*" >> "$MOBILEDATA_EVENTS"; '
                        'exit 1')
        tool("killall", 'printf "killall %s\\n" "$*" >> "$MOBILEDATA_EVENTS"; '
                        'exit 0')
        apctl = root / "mobiledata_apctl"
        apctl.write_text(
            '#!/bin/sh\nprintf "apctl %s\\n" "$*" >> "$MOBILEDATA_EVENTS"\n'
            'exit 0\n', encoding="utf-8")
        apctl.chmod(0o755)

        seed = ["service.mobiledata.enable=1",
                "service.mobiledata.security=open"]
        if supplicant:
            seed.append("init.svc.wpa_supplicant=" + supplicant)
        if driver_status:
            seed.append("wlan.driver.status=" + driver_status)
        props.write_text("\n".join(seed) + "\n", encoding="utf-8")

        env = os.environ.copy()
        env.update({
            "MOBILEDATA_TEST_MODE": "1",
            "MOBILEDATA_TEST_PATH": _shell_path(bindir) + ":/usr/bin:/bin",
            "MOBILEDATA_STATE_DIR": _shell_path(root / "state"),
            "MOBILEDATA_MODULE_ROOTS": _shell_path(modules_dir),
            "MOBILEDATA_SYS_MODULE_DIR": _shell_path(sysmods),
            "MOBILEDATA_SDIO_RECOVER_FILE": _shell_path(recovery_file),
            "MOBILEDATA_APCTL": _shell_path(apctl),
            "MOBILEDATA_DHCPD": _shell_path(bindir / "mobiledata_dhcp"),
            "MOBILEDATA_STATUSD": _shell_path(bindir / "mobiledata_status"),
            "MOBILEDATA_PROP_FILE": _shell_path(props),
            "MOBILEDATA_EVENTS": _shell_path(events),
            "MOBILEDATA_IFACE_PRESENT": "1",
            "MOBILEDATA_IFCONFIG_RC": "0",
            "MOBILEDATA_RMMOD_RC": "0",
            "MOBILEDATA_INSMOD_FAIL_MODE": "",
            "MOBILEDATA_INTERFACE_WAIT_SECONDS": "1",
            "MOBILEDATA_APCTL_START_RC": "0",
            "MOBILEDATA_APCTL_STOP_RC": "0",
            # Keep the bounded waits short; their length is a device tuning
            # decision, their existence is what this test pins.
            "MOBILEDATA_STA_SUSPEND_SECONDS": "3",
            "MOBILEDATA_STA_UNLOAD_SECONDS": "1",
            "MOBILEDATA_SCRIPT": _shell_path(SCRIPT),
        })
        result = subprocess.run(
            ["sh", "-c", '. "$MOBILEDATA_SCRIPT"; ' + entry],
            env=env, capture_output=True, text=True,
        )
        lines = (events.read_text(encoding="utf-8").splitlines()
                 if events.exists() else [])
        values = {}
        for line in props.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            values[key] = value
        return result, lines, values


def _first(lines, needle):
    for index, line in enumerate(lines):
        if needle in line:
            return index
    return -1


def main():
    syntax = subprocess.run(["sh", "-n", str(SCRIPT)],
                            capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr

    text = SCRIPT.read_text(encoding="utf-8")
    assert "N3DS_MOBILE_DATA_STA_EXCLUSION" in text
    assert text == STAGED.read_text(encoding="utf-8"), \
        "overlay and staged Mobile Data runtime drifted"

    # --- the AP path must evict the station stack before it touches wlan0 ---
    result, lines, props = _run("start_ap")
    assert result.returncode == 0, result.stderr
    stop_supplicant = _first(lines, "setprop ctl.stop wpa_supplicant")
    stop_dhcp = _first(lines, "setprop ctl.stop dhcpcd")
    assert stop_supplicant >= 0, lines
    assert stop_dhcp >= 0, lines

    rmmod = _first(lines, "rmmod")
    insmod = _first(lines, "insmod")
    apstart = _first(lines, "apctl --start")
    assert insmod >= 0 and apstart >= 0, lines
    assert 0 <= rmmod and stop_supplicant < rmmod, (
        "supplicant must stop before the module is unloaded", lines)
    assert stop_supplicant < insmod, (
        "supplicant must stop before the fwmode=2 rebind", lines)
    assert stop_supplicant < apstart, (
        "supplicant must stop before the AP controller starts", lines)
    assert "fwmode=2" in lines[insmod], lines[insmod]
    # The AP owns the radio at the end of a successful start.
    assert _first(lines[apstart:], "setprop ctl.start wpa_supplicant") < 0, \
        "start_ap must not re-arm the station supplicant"
    assert props["sys.mobiledata.stage"] == "ready"

    # --- and it must give the station stack back on the way out ---
    # Run the real sequence in one sourcing: stop_ap on its own has no AP to
    # restore, and the supplicant it would resume was never stopped.
    result, lines, props = _run("start_ap; stop_ap")
    assert result.returncode == 0, result.stderr
    ap_rebind = _first(lines, "fwmode=2")
    assert ap_rebind >= 0, lines
    tail = lines[ap_rebind:]
    restore = _first(tail, "fwmode=1")
    resume = _first(tail, "setprop ctl.start wpa_supplicant")
    assert restore >= 0, ("station firmware was never restored", lines)
    assert resume >= 0, ("the supplicant was never re-armed", lines)
    assert restore < resume, (
        "the supplicant must only restart once station firmware is back", lines)
    assert props["sys.mobiledata.state"] in ("disconnected", "disabled")

    # --- a device with no station stack at all is not an AP failure ---
    result, lines, props = _run(
        "start_ap", supplicant="stopped", driver_status="unloaded")
    assert result.returncode == 0, result.stderr
    assert _first(lines, "killall wpa_supplicant") < 0, \
        "no supplicant means nothing to force-kill"
    assert props["sys.mobiledata.stage"] == "ready"

    # --- a supplicant init cannot reap gets force-killed, and the AP still
    # --- comes up: a station stack that refuses to die must not be able to
    # --- veto tethering.
    result, lines, props = _run("start_ap", stubborn=True)
    assert result.returncode == 0, result.stderr
    killed = _first(lines, "killall wpa_supplicant")
    apstart = _first(lines, "apctl --start")
    assert killed >= 0, ("a stuck supplicant must be force-killed", lines)
    assert apstart >= 0 and killed < apstart, lines
    assert props["sys.mobiledata.stage"] == "ready"

    print("mobiledata_sta_exclusion: PASS "
          "(supplicant evicted before rebind, restored after stop)")


if __name__ == "__main__":
    main()
