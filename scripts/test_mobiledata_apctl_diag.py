#!/usr/bin/env python3
"""Pin capture of mobiledata_apctl's exit status and stderr (A7).

The 2026-09-01 capture reached `error ap_controller_failed` 121 ms after
`interface_ready` with no `mobiledata_apctl:` line anywhere, because the
invocation discarded stderr and dropped the exit code.  A usage error (exit 2)
reports nothing to /dev/kmsg at all, so that failure class was invisible.

The helper is extracted from the shipped script and actually run against a fake
controller here, so a helper that swallows the exit status cannot pass.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OVERLAY = Path(f"{A3DS_ROOT}/third_party/buildroot/board/"
               "nintendo3ds/rootfs_overlay/etc/mobiledata.sh")
DEPLOYED = Path(f"{A3DS_ROOT}/sdcard/linux/android/etc/"
                "mobiledata.sh")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_mobiledata_apctl_diag",
        HERE / "patch_mobiledata_apctl_diag.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def helper_source(text):
    """The APCTL diagnostic helpers, standalone and sourceable."""
    start = text.index("APCTL_ERR=/tmp/mobiledata_apctl.err")
    end = text.index("trace() {", start)
    return text[start:end]


def run_helper(helpers, exit_code, stderr_text, args="--start wlan0 3DS open"):
    """Source the real helpers and run run_apctl against a fake controller."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "helpers.sh").write_text(helpers)
        fake = tmp / "fake_apctl"
        fake.write_text("#!/bin/sh\n"
                        "printf '%s' \"$FAKE_STDERR\" >&2\n"
                        "echo ignored-stdout\n"
                        f"exit {exit_code}\n")
        os.chmod(fake, 0o755)
        harness = tmp / "harness.sh"
        harness.write_text(
            f"APCTL={fake}\n"
            f". {tmp / 'helpers.sh'}\n"
            "kmsg() { echo \"KMSG:$1\"; }\n"
            f"run_apctl {args}\n"
            "echo \"RC:$?\"\n")
        proc = subprocess.run(
            ["sh", str(harness)],
            capture_output=True, text=True,
            env={**os.environ, "FAKE_STDERR": stderr_text,
                 "APCTL_ERR": str(tmp / "apctl.err")})
        return proc.stdout


def main():
    patcher = load_patcher()
    text = OVERLAY.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from mobiledata.sh")
    check(patcher.patch_text(text) == text, "patcher is not idempotent")

    syntax = subprocess.run(["sh", "-n", str(OVERLAY)], capture_output=True,
                            text=True)
    check(syntax.returncode == 0,
          f"sh -n rejected the script: {syntax.stderr.strip()}")

    if DEPLOYED.is_file():
        check(DEPLOYED.read_text(encoding="utf-8") == text,
              "the deployed SD copy has drifted from rootfs_overlay/etc; "
              "run sync_android_to_sdcard.sh")
    else:
        failures.append(f"deployed copy not found at {DEPLOYED}")

    # No start/stop invocation may discard the controller's stderr again.
    check('"$APCTL" --start' not in text,
          "an --start invocation still bypasses run_apctl")
    check('"$APCTL" --stop' not in text,
          "the --stop invocation still bypasses run_apctl")
    check(text.count("run_apctl --start") == 2,
          "expected both --start call sites to go through run_apctl")
    check("run_apctl --stop" in text,
          "the --stop call site does not go through run_apctl")

    # The invocation must be bracketed, so a controller that dies without
    # reporting a stage still leaves two lines instead of one.
    check('trace controller_start begin "$MODULE_MODE"' in text,
          "no trace line before the controller is invoked")
    begin_at = text.index('trace controller_start begin')
    call_at = text.index("run_apctl --start")
    check(begin_at < call_at,
          "the controller_start begin trace must precede the invocation")

    # --- run the real helper -----------------------------------------------
    helpers = helper_source(text)
    check("run_apctl()" in helpers, "run_apctl() not found in the helper block")

    out = run_helper(helpers, 0, "")
    check("RC:0" in out, f"success exit status not propagated: {out!r}")
    check("KMSG:mobiledata: apctl begin" in out,
          f"no begin line on the success path: {out!r}")
    check("KMSG:mobiledata: apctl rc=0" in out,
          f"success exit status not reported: {out!r}")
    check("apctl err:" not in out,
          f"stderr reported on a successful run: {out!r}")

    out = run_helper(helpers, 2, "usage: mobiledata_apctl --start <if>\n")
    check("RC:2" in out, f"usage exit status not propagated: {out!r}")
    check("KMSG:mobiledata: apctl rc=2" in out,
          f"usage exit status not reported: {out!r}")
    check("KMSG:mobiledata: apctl err: usage: mobiledata_apctl --start <if>"
          in out,
          f"stderr not captured -- this is the whole point: {out!r}")

    out = run_helper(helpers, 1, "")
    check("RC:1" in out, f"failure exit status not propagated: {out!r}")
    check("KMSG:mobiledata: apctl rc=1" in out,
          f"failure exit status not reported: {out!r}")

    # Bounded: a controller that floods stderr must not flood the kernel log.
    out = run_helper(helpers, 1, "x" * 20000 + "\n")
    reported = sum(len(line) for line in out.splitlines()
                   if "apctl err:" in line)
    check(reported <= 1200,
          f"stderr capture is unbounded: {reported} bytes reached kmsg")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_mobiledata_apctl_diag: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
