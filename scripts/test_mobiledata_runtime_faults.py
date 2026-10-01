#!/usr/bin/env python3
"""Fault-injection regression for the bounded Mobile Data runtime shell."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/mobiledata.sh"
BOOT = ROOT / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh"
STAGED_BOOT = ROOT / "sdcard/linux/android/etc/boot_progress.sh"


def _shell_path(path: Path) -> str:
    """Render a host path for the Unix shell that executes the fixture.

    The target runtime is POSIX shell code.  WSL already uses POSIX paths,
    while Windows-host test runs use MSYS ``sh`` and need ``cygpath``; a
    Windows ``PATH``/drive path is not a valid shell search path here.
    """
    value = str(path)
    if os.name != "nt":
        return value
    cygpath = shutil.which("cygpath")
    if cygpath:
        converted = subprocess.run(
            [cygpath, "-u", value], capture_output=True, text=True,
            check=False,
        )
        if converted.returncode == 0 and converted.stdout.strip():
            return converted.stdout.strip()
    return value.replace("\\", "/")


def _run(*, modules=False, loaded=False, interface=True, rmmod_rc=0,
         insmod_fail_mode="", apctl_start_rc=0, apctl_stop_rc=0,
         ifconfig_rc=0, recovery=True):
    """Source the runtime with harmless command/property fixtures."""
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        bindir = root / "bin"
        bindir.mkdir()
        props = root / "props"
        events = root / "events"
        recovery_file = root / "wifi_recover"
        if recovery:
            recovery_file.write_text("", encoding="utf-8")
        modules_dir = root / "modules"
        modules_dir.mkdir()
        sysmods = root / "sysmods"
        sysmods.mkdir()
        if modules:
            (modules_dir / "ath6k_legacy.ko").write_bytes(b"fixture")
        if loaded:
            (sysmods / "ath6k_legacy").mkdir()

        def tool(name, body):
            path = bindir / name
            path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
            path.chmod(0o755)

        tool("setprop", "key=$1; shift; value=$*; tmp=\"$MOBILEDATA_PROP_FILE.tmp.$$\"; awk -F= -v k=\"$key\" '$1 != k {print}' \"$MOBILEDATA_PROP_FILE\" 2>/dev/null > \"$tmp\" || true; printf '%s=%s\\n' \"$key\" \"$value\" >> \"$tmp\"; mv \"$tmp\" \"$MOBILEDATA_PROP_FILE\"")
        tool("getprop", "awk -F= -v k=\"$1\" '$1 == k {v=substr($0, index($0, \"=\")+1)} END {if (v != \"\") print v}' \"$MOBILEDATA_PROP_FILE\" 2>/dev/null")
        # Match the Unix ifconfig probe contract used by interface_present:
        # success (0) means that wlan0 exists; any nonzero status means it is
        # absent.  Address configuration is a separate, multi-argument call.
        tool("ifconfig", "if [ \"$#\" -eq 1 ]; then if [ \"$MOBILEDATA_IFACE_PRESENT\" = 1 ]; then exit 0; fi; exit 1; fi; exit \"$MOBILEDATA_IFCONFIG_RC\"")
        tool("rmmod", "printf 'rmmod %s\\n' \"$*\" >> \"$MOBILEDATA_EVENTS\"; if [ \"$MOBILEDATA_RMMOD_RC\" -ne 0 ]; then exit \"$MOBILEDATA_RMMOD_RC\"; fi; rm -rf \"$MOBILEDATA_SYS_MODULE_DIR/ath6k_legacy\"; exit 0")
        tool("insmod", "printf 'insmod %s\\n' \"$*\" >> \"$MOBILEDATA_EVENTS\"; case \"$*\" in *fwmode=2*) [ \"$MOBILEDATA_INSMOD_FAIL_MODE\" = 2 ] && exit 1;; esac; mkdir -p \"$MOBILEDATA_SYS_MODULE_DIR/ath6k_legacy\"; exit 0")
        tool("mobiledata_dhcp", "sleep 2")
        tool("mobiledata_status", "sleep 2")
        tool("killall", "exit 0")
        apctl = root / "mobiledata_apctl"
        apctl.write_text("#!/bin/sh\nprintf 'apctl %s\\n' \"$*\" >> \"$MOBILEDATA_EVENTS\"\ncase \"$1\" in --start) exit \"$MOBILEDATA_APCTL_START_RC\";; --stop) exit \"$MOBILEDATA_APCTL_STOP_RC\";; esac\nexit 0\n", encoding="utf-8")
        apctl.chmod(0o755)
        props.write_text("service.mobiledata.enable=1\nservice.mobiledata.security=open\n", encoding="utf-8")
        env = os.environ.copy()
        shell_bindir = _shell_path(bindir)
        env.update({
            "MOBILEDATA_TEST_MODE": "1",
            "MOBILEDATA_TEST_PATH": shell_bindir + ":/usr/bin:/bin",
            "MOBILEDATA_STATE_DIR": _shell_path(root / "state"),
            "MOBILEDATA_MODULE_ROOTS": _shell_path(modules_dir),
            "MOBILEDATA_SYS_MODULE_DIR": _shell_path(sysmods),
            "MOBILEDATA_SDIO_RECOVER_FILE": (
                _shell_path(recovery_file) if recovery else
                _shell_path(root / "missing_wifi_recover")
            ),
            "MOBILEDATA_APCTL": _shell_path(apctl),
            "MOBILEDATA_DHCPD": _shell_path(bindir / "mobiledata_dhcp"),
            "MOBILEDATA_STATUSD": _shell_path(bindir / "mobiledata_status"),
            "MOBILEDATA_PROP_FILE": _shell_path(props),
            "MOBILEDATA_EVENTS": _shell_path(events),
            "MOBILEDATA_IFACE_PRESENT": "1" if interface else "0",
            "MOBILEDATA_IFCONFIG_RC": str(ifconfig_rc),
            "MOBILEDATA_RMMOD_RC": str(rmmod_rc),
            "MOBILEDATA_INSMOD_FAIL_MODE": insmod_fail_mode,
            "MOBILEDATA_INTERFACE_WAIT_SECONDS": "1",
            "MOBILEDATA_APCTL_START_RC": str(apctl_start_rc),
            "MOBILEDATA_APCTL_STOP_RC": str(apctl_stop_rc),
        })
        result = subprocess.run(
            ["sh", "-c", '. "$MOBILEDATA_SCRIPT"; start_ap'],
            env={**env, "MOBILEDATA_SCRIPT": _shell_path(SCRIPT)},
            capture_output=True, text=True,
        )
        values = {}
        for line in props.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            values[key] = value
        events_text = events.read_text(encoding="utf-8") if events.exists() else ""
        return result.returncode, values, events_text


def main():
    syntax = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert syntax.returncode == 0, syntax.stderr
    boot_text = BOOT.read_text(encoding="utf-8")
    assert "mobiledata:" in boot_text
    assert boot_text == STAGED_BOOT.read_text(encoding="utf-8")

    rc, props, events = _run(interface=True)
    assert rc == 0 and props["sys.mobiledata.module"] == "builtin"
    assert props["sys.mobiledata.stage"] == "ready"
    assert "apctl --start" in events
    assert "rmmod" not in events and "insmod" not in events

    rc, props, events = _run(interface=False)
    assert rc != 0 and props["sys.mobiledata.error"] == "station_rebind_failed"
    assert props["sys.mobiledata.boundary"] == "driver_missing"
    assert props["sys.mobiledata.module"] == "missing"
    assert props["sys.mobiledata.rollback"] == "restored"

    rc, props, events = _run(modules=True, loaded=True, rmmod_rc=1)
    assert rc != 0 and props["sys.mobiledata.boundary"] == "module_unload_failed"
    assert "insmod" not in events

    rc, props, events = _run(modules=True, loaded=True, recovery=False)
    assert rc != 0
    assert props["sys.mobiledata.boundary"] == "sdio_recovery_unavailable"
    assert "insmod" not in events

    rc, props, events = _run(modules=True, loaded=True, insmod_fail_mode="2")
    assert rc != 0 and props["sys.mobiledata.boundary"] == "module_load_failed"
    assert "fwmode=1" in events and props["sys.mobiledata.rollback"] == "restored"

    rc, props, events = _run(interface=True, apctl_start_rc=1)
    assert rc != 0 and props["sys.mobiledata.error"] == "ap_controller_failed"
    assert props["sys.mobiledata.boundary"] == "ap_controller_failed"
    assert props["sys.mobiledata.rollback"] == "restored"

    rc, props, events = _run(interface=True, ifconfig_rc=1, apctl_stop_rc=1)
    assert rc != 0 and props["sys.mobiledata.error"] == "station_restore_failed"
    assert props["sys.mobiledata.boundary"] == "address_config_failed"
    assert props["sys.mobiledata.rollback"] == "failed"
    assert "apctl --start" in events and "apctl --stop" in events

    print("mobiledata_runtime_faults: PASS (built-in/reloadable/rollback diagnostics)")


if __name__ == "__main__":
    main()
