#!/usr/bin/env python3
"""Both power buttons must always reach poweroff, whatever else fails.

This replaces a test that asserted the opposite.  The old shutdown script was
fail-closed -- a writer that would not stop, a NUL byte in a log, a storage
error, or an EBUSY unmount each ended in "refusing unsafe poweroff; exit 1" --
and the old test asserted those non-zero exits.  On hardware /mnt/sd can never
be unmounted (it holds the bind mounts and the running script itself), so that
path always triggered: holding SELECT printed that the card was still held
open and left the console powered on.

So the property under test is now the one the hardware actually needs.  The
script is run in a sandbox with stand-ins for every external command it
touches, under each failure the old design vetoed on, and in every case it
must run to completion, invoke poweroff, and exit 0.  The acknowledgement to
the kernel gate is checked too, since that is what turns "poweroff -f did not
return" into a real MCU cut instead of a console left lit for the rest of the
deadline.
"""
from a3ds_paths import A3DS_ROOT

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
WSL_ROOT = Path(A3DS_ROOT)
OVERLAY_REL = Path("third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/ctr_poweroff.sh")

# Stand-ins for everything the script shells out to.  fuser in particular MUST
# be stubbed: the real one is invoked as `fuser -m "$MOUNT_POINT"`, which names
# every process using that whole filesystem, and the script kills what it
# returns -- on a host that is the developer's own session.
FAKES = {
    "fuser": "#!/bin/sh\nexit 1\n",
    "mount": '#!/bin/sh\necho "mount $*" >> "$N3DS_TEST_EVENTS"\nexit 1\n',
    "umount": '#!/bin/sh\necho "umount $*" >> "$N3DS_TEST_EVENTS"\nexit 1\n',
    "sync": '#!/bin/sh\necho sync >> "$N3DS_TEST_EVENTS"\nexit 0\n',
    "dmesg": '#!/bin/sh\ncat "$N3DS_TEST_DMESG" 2>/dev/null\nexit 0\n',
}


def write_exec(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def run_case(script: Path, name: str, *, writers_stuck=False,
             gate_writable=True, storage_error=False):
    tmp = Path(tempfile.mkdtemp(prefix="n3ds-poweroff-"))
    try:
        bindir = tmp / "bin"
        bindir.mkdir()
        for exe, body in FAKES.items():
            write_exec(bindir / exe, body)

        events = tmp / "events"
        events.write_text("", encoding="utf-8")
        dmesg = tmp / "dmesg.txt"
        dmesg.write_text(
            "FAT-fs (vda1): error, invalid access to FAT\n" if storage_error
            else "hello\n", encoding="utf-8")

        write_exec(tmp / "setprop",
                   '#!/bin/sh\necho "setprop $*" >> "$N3DS_TEST_EVENTS"\n')
        # init.svc.* is what wait_for_log_writers polls; "running" forever is
        # the writer-will-not-stop case.
        state = "running" if writers_stuck else "stopped"
        write_exec(tmp / "getprop", "#!/bin/sh\necho %s\n" % state)
        write_exec(tmp / "poweroff",
                   '#!/bin/sh\necho "poweroff $*" >> "$N3DS_TEST_EVENTS"\n'
                   "exit 1\n")

        gate = tmp / "gate"
        gate.write_text("", encoding="utf-8")
        gate.chmod(0o644 if gate_writable else 0o444)
        force_arm = tmp / "force_arm_ms"
        force_arm.write_text("", encoding="utf-8")
        mount_point = tmp / "sd"
        mount_point.mkdir()

        env = dict(os.environ)
        env.update(
            PATH="%s:%s" % (bindir, env.get("PATH", "")),
            N3DS_TEST_EVENTS=str(events),
            N3DS_TEST_DMESG=str(dmesg),
            N3DS_SETPROP=str(tmp / "setprop"),
            N3DS_GETPROP=str(tmp / "getprop"),
            N3DS_POWER_OFF=str(tmp / "poweroff"),
            N3DS_POWER_READY=str(gate),
            N3DS_FORCE_ARM=str(force_arm),
            N3DS_MOUNT_POINT=str(mount_point),
            N3DS_LOG_FINALIZE_TIMEOUT="2",
        )
        result = subprocess.run(["/bin/sh", str(script)], env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=180)
        return (result, events.read_text(encoding="utf-8"),
                gate.read_text(encoding="utf-8").strip())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    script = WSL_ROOT / OVERLAY_REL
    if not script.is_file():
        script = PROJECT / OVERLAY_REL
    if not script.is_file():
        print("ctr_poweroff.sh not present in this tree; nothing to test")
        return

    text = script.read_text(encoding="utf-8")
    assert "N3DS_LOG_FINALIZATION_V2" in text
    assert "wait_for_log_writers" in text
    assert "check_storage_errors" in text
    assert 'echo 1 > "$POWER_READY"' in text
    # A veto anywhere in this file is the regression this test exists for.
    assert "refusing unsafe poweroff" not in text
    assert "umount -l" not in text
    # The observation must come before the acknowledgement, or the gate says
    # "flushed" while a writer is still going.
    assert text.index("wait_for_log_writers()") < text.index(
        'echo 1 > "$POWER_READY"')
    assert text.index("$FORCE_ARM") < text.index("wait_for_log_writers()")

    cases = [
        ("clean shutdown", {}),
        ("writer will not stop", {"writers_stuck": True}),
        ("kernel gate unavailable", {"gate_writable": False}),
        ("storage error reported", {"storage_error": True}),
    ]
    for name, kwargs in cases:
        result, events, gate = run_case(script, name, **kwargs)
        out = result.stdout.decode("utf-8", "replace")
        assert result.returncode == 0, (name, result.returncode, out)
        assert "poweroff -f" in events, (name, events)
        if kwargs.get("gate_writable", True):
            assert gate == "1", (name, gate)
        print("PASS: %s" % name)

    print("PASS: N3DS shutdown always powers off")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print("FAIL: %s" % (exc,), file=sys.stderr)
        raise SystemExit(1)
