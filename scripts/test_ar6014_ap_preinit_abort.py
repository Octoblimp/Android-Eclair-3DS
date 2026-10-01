#!/usr/bin/env python3
"""Pin the AP bring-up abort and the end of phantom commit successes (A11).

#255 timestamped the target assert at 132.048, after the last pre-init command
(0x004c at 132.047) and before the commit was submitted (0x004e at 132.061).
The WMI history ring recorded three sends and stopped.  So the commit never
reached a live target, and the ``status=0`` printed next to it was the host
reading back its own queue insertion.

Two things have to hold from now on: the pre-init sequence must stop at the
command that kills the target rather than running on and implicating the last
one, and no code path may report an AP as up on the strength of a host-side
zero returned by a dead target.
"""
from a3ds_paths import A3DS_ROOT

import importlib.util
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
           "ath6k_legacy/os/linux/ar6000_drv.c")
INITRAMFS = Path(f"{A3DS_ROOT}/sdcard/linux/initramfs.cpio.gz")

failures = []


def check(condition, message):
    if not condition:
        failures.append(message)


def load_patcher():
    spec = importlib.util.spec_from_file_location(
        "patch_ar6014_ap_preinit_abort",
        HERE / "patch_ar6014_ap_preinit_abort.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    patcher = load_patcher()
    text = SRC.read_text(encoding="utf-8")

    check(patcher.MARKER in text, "marker missing from ar6000_drv.c")
    check(patcher.patch_driver(text) == text, "patcher is not idempotent")

    # The target's death has to be recorded where it happens.
    check("static atomic_t n3ds_target_failed = ATOMIC_INIT(0);" in text,
          "the target-failure flag is missing")
    check(text.count("atomic_set(&n3ds_target_failed, 1);") == 1,
          "the flag is not set exactly once, in the failure handler")
    assert_print = text.find('"ar6000_target_failure: target asserted \\n"')
    flag_set = text.find("atomic_set(&n3ds_target_failed, 1);")
    check(assert_print != -1 and flag_set != -1,
          "could not locate the target-failure handler landmarks")
    if assert_print != -1 and flag_set != -1:
        check(0 < flag_set - assert_print < 400,
              "the flag is set far from the assert print; the register dump "
              "and target log fetch in between take long enough that a caller "
              "polling the flag would miss the window")

    # maxcpus=1 makes this a correctness requirement, not a style preference.
    check("static int n3ds_target_settle(unsigned int msecs)" in text,
          "the settle helper is missing")
    check("msleep(msecs);" in text,
          "the settle helper does not sleep; this port runs maxcpus=1, so a "
          "busy-wait would hold the only CPU and the event path that sets the "
          "flag could never run")
    check("A_MDELAY" not in text.split("n3ds_target_settle")[-1][:200],
          "the settle helper busy-waits")

    # The sequence must name the command that killed the target.
    check("if (n3ds_target_settle(5)) {" in text,
          "the pre-init step macro does not check for a dead target")
    check('A_PRINTF("AR6002 AP: preinit ABORTED after cmd=0x%04x %s\\n",'
          in text,
          "an aborted pre-init does not name the command it stopped after")
    check("AR6002 AP: preinit ABORTED before it began, target already " in text,
          "a pre-init started against an already-dead target is not reported")

    # Default off: the decisive A/B against a bare commit.
    check("static int n3ds_ap_preinit = 0;" in text,
          "n3ds_ap_preinit does not default off; with the commit exonerated "
          "the sequence is the only remaining suspect and skipping it is both "
          "the A/B and a plausible fix")
    check("module_param(n3ds_ap_preinit, int, 0644);" in text,
          "n3ds_ap_preinit is not a module parameter, so the sequence cannot "
          "be sent again without rebuilding")

    # No path may declare an AP up on a queue result.
    check("AR6002 AP: commit cmd=0x%04x SKIPPED, target asserted " in text,
          "the commit does not refuse to submit into a dead target")
    check("if (status == 0 && n3ds_target_settle(20)) {" in text,
          "the commit does not re-check the target after submitting; "
          "wmi_cmd_send() returns host queue success, not an acknowledgement")
    check("AR6002 AP: commit cmd=0x%04x TARGET ASSERTED after submit" in text,
          "a post-submit assert is not reported")

    # The re-check must feed the existing rollback rather than sit beside it.
    recheck = text.find("if (status == 0 && n3ds_target_settle(20)) {")
    rollback = text.find("AP commit rejected by host transport: %d")
    check(recheck != -1 and rollback != -1 and recheck < rollback,
          "the post-submit check does not run before the rollback, so a dead "
          "target would still leave AP state behind")

    if not INITRAMFS.is_file():
        failures.append(f"initramfs not found at {INITRAMFS}")
    else:
        blob = subprocess.run(
            ["bash", "-c",
             f"gzip -dc {INITRAMFS} | cpio -i --to-stdout "
             f"n3ds/modules/ath6kl.ko 2>/dev/null"],
            capture_output=True).stdout
        check(len(blob) > 0, "could not extract ath6kl.ko from the initramfs")
        if blob:
            check(b"AR6002 AP: commit cmd=0x%04x TARGET ASSERTED after submit"
                  in blob,
                  "baked initramfs module predates the AP abort work")

    if failures:
        for message in failures:
            print(f"FAIL: {message}")
        return 1
    print("test_ar6014_ap_preinit_abort: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
