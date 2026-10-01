#!/usr/bin/env python3
"""Stop attributing the AP assert to the wrong command (A11).

Build #255's compact register dump and widened trace window finally let the
Mobile Data bring-up survive its own failure, and the timeline it produced
retires the theory this file's predecessor was built on::

    [132.046] AR6002 AP: preinit cmd=0x004c acl_policy submit
    [132.047] AR6002 AP: preinit cmd=0x004c acl_policy status=0
    [132.048] ar6000_target_failure: target asserted
    ...
    [132.061] AR6002 AP: commit cmd=0x004e submit ...
    [132.061] AR6002 AP: commit cmd=0x004e status=0

The target died at 132.048, thirteen milliseconds *before* the commit was
submitted, and the WMI history ring agrees: it holds three sends (0x004a,
0x004b, 0x004c) and nothing else.  So `WMI_AP_CONFIG_COMMIT_CMDID` is
exonerated -- and worse, its `status=0` is a phantom.  `wmi_cmd_send()`
reports that the host queued the command, not that a target received it, so
every line after 132.048 is the host talking to a corpse and reading its own
success back.  The AP-ready path then declared the AP up.

Three changes, all aimed at never being lied to like that again:

*   `ar6000_target_failure()` records the death in an atomic, so any code
    that runs afterwards can ask whether the target is still alive.
*   `N3DS_AP_PREINIT_STEP` settles for 5 ms after each command and checks
    that flag, so the sequence stops at the command that killed the target
    and names it, instead of running to the end and blaming the last one.
    `msleep()` rather than `A_MDELAY()` on purpose: this port runs
    `maxcpus=1`, and a busy-wait would never let the event path that sets the
    flag run at all.
*   `ar6000_ap_mode_profile_commit()` refuses to submit into a dead target,
    and re-checks after submitting, so a queue-level `status=0` can no longer
    be reported as an AP that came up.

The default for `n3ds_ap_preinit` also flips from 1 to 0.  With the commit
cleared of suspicion, the pre-init sequence is the only remaining candidate,
and skipping it is simultaneously the decisive A/B and a plausible fix: if
the AP beacons without it, the sequence was the bug; if the target still
asserts, it asserts on the commit alone and the fault is in the 54-byte
payload after all.  `n3ds_ap_preinit=1` re-enables the sequence, now with the
abort logic to name the guilty command.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_AP_PREINIT_ABORT"

FLAG_OLD = """static void ar6000_target_failure(void *Instance, int Status)
{
    struct ar6_softc *ar = (struct ar6_softc *)Instance;
"""

FLAG_NEW = """/* N3DS_AR6014_AP_PREINIT_ABORT: wmi_cmd_send() returns host queue success,
 * not a target acknowledgement, so once the target has asserted every
 * subsequent command still reports status=0.  Record the death here and let
 * the AP path ask, instead of reading its own writes back as progress. */
static atomic_t n3ds_target_failed = ATOMIC_INIT(0);

/* N3DS_AR6014_AP_PREINIT_ABORT: sleep, do not spin.  This port runs
 * maxcpus=1; mdelay() would hold the only CPU and the event path that sets
 * the flag above could never run, so the check would always read 0. */
static int n3ds_target_settle(unsigned int msecs)
{
    msleep(msecs);
    return atomic_read(&n3ds_target_failed);
}

static void ar6000_target_failure(void *Instance, int Status)
{
    struct ar6_softc *ar = (struct ar6_softc *)Instance;
"""

SET_OLD = """        printk(KERN_ERR "ar6000_target_failure: target asserted \\n");
"""

SET_NEW = """        printk(KERN_ERR "ar6000_target_failure: target asserted \\n");

        /* N3DS_AR6014_AP_PREINIT_ABORT: set before anything else in this
         * handler -- the register dump and log fetch below take long enough
         * that a caller polling the flag would otherwise miss the window. */
        atomic_set(&n3ds_target_failed, 1);
"""

PARAM_OLD = """/* N3DS_AR6014_AP_PREINIT_SEQUENCE: stock ath6kl programs the AP parameters
 * before it commits a profile; this driver sends the commit alone, so the
 * target has been asked to bring an AP up against state it was never given.
 * That is a plausible cause of the firmware assert seen on both Mobile Data
 * attempts, and even if it is not, announcing each command ID before sending
 * it localises the assert to one command instead of "AP bring-up". */
static int n3ds_ap_preinit = 1;
"""

PARAM_NEW = """/* N3DS_AR6014_AP_PREINIT_SEQUENCE: stock ath6kl programs the AP parameters
 * before it commits a profile, and this driver used to send the commit alone.
 *
 * N3DS_AR6014_AP_PREINIT_ABORT: that reasoning was sound and the conclusion
 * was wrong.  #255 timestamped the assert at 132.048, between the last
 * pre-init command (0x004c, 132.047) and the commit (0x004e, 132.061), and
 * the WMI history ring recorded exactly three sends.  The target dies inside
 * this sequence, not on the commit, so the sequence defaults off now: that
 * is both the clean A/B against the bare commit and, if one of these five
 * commands is unimplemented in NWM, the fix.  Set n3ds_ap_preinit=1 to send
 * it again -- the step macro below will then stop at the command that kills
 * the target and print its ID. */
static int n3ds_ap_preinit = 0;
"""

MACRO_OLD = """#define N3DS_AP_PREINIT_STEP(_ar, _what, _id, _call) do {                     \\
    A_PRINTF("AR6002 AP: preinit cmd=0x%04x %s submit\\n",                     \\
             (unsigned int)(_id), (_what));                                   \\
    A_PRINTF("AR6002 AP: preinit cmd=0x%04x %s status=%d\\n",                  \\
             (unsigned int)(_id), (_what), (_call));                          \\
} while (0)
"""

MACRO_NEW = """/* N3DS_AR6014_AP_PREINIT_ABORT: settle after each command and stop at the
 * first one the target does not survive.  Without this the sequence runs to
 * completion against a dead target, every command reports status=0, and the
 * assert gets blamed on whatever happened to be last. */
#define N3DS_AP_PREINIT_STEP(_ar, _what, _id, _call) do {                     \\
    A_PRINTF("AR6002 AP: preinit cmd=0x%04x %s submit\\n",                     \\
             (unsigned int)(_id), (_what));                                   \\
    A_PRINTF("AR6002 AP: preinit cmd=0x%04x %s status=%d\\n",                  \\
             (unsigned int)(_id), (_what), (_call));                          \\
    if (n3ds_target_settle(5)) {                                              \\
        A_PRINTF("AR6002 AP: preinit ABORTED after cmd=0x%04x %s\\n",          \\
                 (unsigned int)(_id), (_what));                               \\
        return;                                                               \\
    }                                                                         \\
} while (0)
"""

ENTRY_OLD = """    if (!n3ds_ap_preinit) {
        A_PRINTF("AR6002 AP: preinit disabled by n3ds_ap_preinit=0\\n");
        return;
    }
"""

ENTRY_NEW = """    if (!n3ds_ap_preinit) {
        A_PRINTF("AR6002 AP: preinit disabled by n3ds_ap_preinit=0\\n");
        return;
    }

    /* N3DS_AR6014_AP_PREINIT_ABORT: if the target is already gone, say so
     * here rather than sending five commands into it and reporting five
     * successes. */
    if (atomic_read(&n3ds_target_failed)) {
        A_PRINTF("AR6002 AP: preinit ABORTED before it began, target already "
                 "asserted\\n");
        return;
    }
"""

COMMIT_OLD = """    n3ds_ar6000_ap_preinit(ar);

    /* N3DS_AR6014_AP_PREINIT_SEQUENCE: the last line before the target dies,
"""

COMMIT_NEW = """    n3ds_ar6000_ap_preinit(ar);

    /* N3DS_AR6014_AP_PREINIT_ABORT: do not submit a profile into a dead
     * target.  wmi_ap_profile_commit() would queue it and return 0, the
     * caller would take that for an AP that came up, and Mobile Data would
     * report success while nothing beaconed -- which is what #255 did. */
    if (atomic_read(&n3ds_target_failed)) {
        A_PRINTF("AR6002 AP: commit cmd=0x%04x SKIPPED, target asserted "
                 "during bring-up\\n",
                 (unsigned int)WMI_AP_CONFIG_COMMIT_CMDID);
        ar->ap_profile_flag = 0;
        return -EIO;
    }

    /* N3DS_AR6014_AP_PREINIT_SEQUENCE: the last line before the target dies,
"""

SUBMIT_OLD = """    status = wmi_ap_profile_commit(ar->arWmi, &p);
    A_PRINTF("AR6002 AP: commit cmd=0x%04x status=%d\\n",
             (unsigned int)WMI_AP_CONFIG_COMMIT_CMDID, status);
    if (status != 0) {
"""

SUBMIT_NEW = """    status = wmi_ap_profile_commit(ar->arWmi, &p);
    A_PRINTF("AR6002 AP: commit cmd=0x%04x status=%d\\n",
             (unsigned int)WMI_AP_CONFIG_COMMIT_CMDID, status);

    /* N3DS_AR6014_AP_PREINIT_ABORT: status is a queue result.  Give the
     * target long enough to assert on what was just queued and check for
     * real, so the rollback below runs instead of the AP being declared up
     * on the strength of a host-side zero. */
    if (status == 0 && n3ds_target_settle(20)) {
        A_PRINTF("AR6002 AP: commit cmd=0x%04x TARGET ASSERTED after submit\\n",
                 (unsigned int)WMI_AP_CONFIG_COMMIT_CMDID);
        status = -EIO;
    }

    if (status != 0) {
"""

HUNKS = (
    ("target-failure flag and settle helper", FLAG_OLD, FLAG_NEW),
    ("record the assert", SET_OLD, SET_NEW),
    ("default the pre-init sequence off", PARAM_OLD, PARAM_NEW),
    ("abort the sequence at the guilty command", MACRO_OLD, MACRO_NEW),
    ("refuse to start against a dead target", ENTRY_OLD, ENTRY_NEW),
    ("refuse to commit against a dead target", COMMIT_OLD, COMMIT_NEW),
    ("no phantom commit success", SUBMIT_OLD, SUBMIT_NEW),
)


def patch_driver(text):
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, (
            "%s: anchor matched %d times, expected 1" % (name, text.count(old)))
        text = text.replace(old, new)
    return text


def main():
    text = TARGET.read_text(encoding="utf-8")
    patched = patch_driver(text)
    if patched == text:
        print("patch_ar6014_ap_preinit_abort: already applied")
        return 0
    TARGET.write_text(patched, encoding="utf-8")
    print("patch_ar6014_ap_preinit_abort: applied %d hunks" % len(HUNKS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
