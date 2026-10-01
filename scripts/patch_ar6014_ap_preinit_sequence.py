#!/usr/bin/env python3
"""Send the stock AP pre-init sequence and trace the bring-up (A5 + A6).

Mobile Data stopped starting at all: the target now asserts during AP bring-up.
Both attempts in the 2026-09-01 capture produced byte-identical register dumps
and then ~10 s of nothing until mobiledata_apctl timed out at ready_timeout,
errno=110.  The host-side guards in ar6000_ap_mode_profile_commit() all print
on rejection and none of those lines appear, so the commit was not refused
locally -- it went out and the firmware died on it.

Two things are worth separating, and one patch can do both.

A6 -- ar6000_ap_mode_profile_commit() sends exactly one command, the commit.
Stock ath6kl AP bring-up first programs hidden-SSID, station count, ACL policy,
inactivity timeout and background-scan time, so the target here is being asked
to commit an AP profile against AP state it was never given.  Send that
sequence.  If the assert moves to an earlier command, the crash is about a
specific command rather than the commit; if it stays on the commit, the AP
state was not the problem.

A5 -- every step announces its command ID before it is sent, and the boundary
facts nobody has ever captured (the fwmode actually written at BMI time, the
network type in force when WMI comes up, the moment the commit goes out) are
printed too.  Between those and the WMI command-history ring, the next assert
should name the command that caused it.

n3ds_ap_preinit=0 disables the sequence for an A/B run without a reflash of a
different driver.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
DRV_C = ROOT / "os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_AP_PREINIT_SEQUENCE"

# --- 1. announce the firmware mode actually written to the target ------------

# "Firmware mode set" is printed twice in this file; anchor on the fwmode
# write's own error string so the ATH6KL_DISABLE_TARGET_DBGLOGS block that
# follows cannot be matched by accident.
FWMODE_OLD = """            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,("BMIWriteMemory for setting fwmode failed \\n"));
            return A_ERROR;
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_INFO,("Firmware mode set\\n"));
"""

FWMODE_NEW = """            AR_DEBUG_PRINTF(ATH_DEBUG_ERR,("BMIWriteMemory for setting fwmode failed \\n"));
            return A_ERROR;
        }
        AR_DEBUG_PRINTF(ATH_DEBUG_INFO,("Firmware mode set\\n"));
        /* N3DS_AR6014_AP_PREINIT_SEQUENCE: fwmode is consumed once, here, and
         * nothing downstream can report what the target actually booted as.
         * An AP run that silently came up in station mode looks exactly like
         * an AP run whose commit was ignored. */
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 AP: BMI fwmode=%u hi_option_flag=0x%08x\\n",
             fwmode, param));
"""

# --- 2. announce the mode in force when WMI comes up -------------------------

READY_OLD = """    /* Indicate to the waiting thread that the ready event was received */
    ar->arWmiReady = true;
"""

READY_NEW = """    /* N3DS_AR6014_AP_PREINIT_SEQUENCE: the AP path refuses to commit unless
     * arWmiReady is set and arNextMode is AP_NETWORK, and until now a failure
     * of either was indistinguishable from a firmware fault. */
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 AP: WMI ready nettype=%u nextmode=%u wlanstate=%u\\n",
         ar->arNetworkType, ar->arNextMode, ar->arWlanState));

    /* Indicate to the waiting thread that the ready event was received */
    ar->arWmiReady = true;
"""

# --- 3. the pre-init sequence and its trace ---------------------------------

COMMIT_OLD = """int
ar6000_ap_mode_profile_commit(struct ar6_softc *ar)
{
    WMI_CONNECT_CMD p;
    int status;
    unsigned long flags;
"""

COMMIT_NEW = """/* N3DS_AR6014_AP_PREINIT_SEQUENCE: stock ath6kl programs the AP parameters
 * before it commits a profile; this driver sends the commit alone, so the
 * target has been asked to bring an AP up against state it was never given.
 * That is a plausible cause of the firmware assert seen on both Mobile Data
 * attempts, and even if it is not, announcing each command ID before sending
 * it localises the assert to one command instead of "AP bring-up". */
static int n3ds_ap_preinit = 1;
module_param(n3ds_ap_preinit, int, 0644);
MODULE_PARM_DESC(n3ds_ap_preinit,
    "send the stock AP parameter commands before AP_CONFIG_COMMIT (0 = off)");

#define N3DS_AP_PREINIT_STEP(_ar, _what, _id, _call) do {                     \\
    A_PRINTF("AR6002 AP: preinit cmd=0x%04x %s submit\\n",                     \\
             (unsigned int)(_id), (_what));                                   \\
    A_PRINTF("AR6002 AP: preinit cmd=0x%04x %s status=%d\\n",                  \\
             (unsigned int)(_id), (_what), (_call));                          \\
} while (0)

static void n3ds_ar6000_ap_preinit(struct ar6_softc *ar)
{
    if (!n3ds_ap_preinit) {
        A_PRINTF("AR6002 AP: preinit disabled by n3ds_ap_preinit=0\\n");
        return;
    }

    A_PRINTF("AR6002 AP: preinit begin channel=%u ssidlen=%u auth=%u "
             "pair=%u/%u group=%u/%u\\n",
             ar->arChannelHint, ar->arSsidLen, ar->arAuthMode,
             ar->arPairwiseCrypto, ar->arPairwiseCryptoLen,
             ar->arGroupCrypto, ar->arGroupCryptoLen);

    N3DS_AP_PREINIT_STEP(ar, "hidden_ssid", WMI_AP_HIDDEN_SSID_CMDID,
                         wmi_ap_set_hidden_ssid(ar->arWmi, 0));
    N3DS_AP_PREINIT_STEP(ar, "num_sta", WMI_AP_SET_NUM_STA_CMDID,
                         wmi_ap_set_num_sta(ar->arWmi, AP_MAX_NUM_STA));
    N3DS_AP_PREINIT_STEP(ar, "acl_policy", WMI_AP_ACL_POLICY_CMDID,
                         wmi_ap_set_acl_policy(ar->arWmi, AP_ACL_DISABLE));
    N3DS_AP_PREINIT_STEP(ar, "conn_inact", WMI_AP_CONN_INACT_CMDID,
                         wmi_ap_conn_inact_time(ar->arWmi, 60));
    N3DS_AP_PREINIT_STEP(ar, "prot_scan_time", WMI_AP_PROT_SCAN_TIME_CMDID,
                         wmi_ap_bgscan_time(ar->arWmi, 60, 100));

    A_PRINTF("AR6002 AP: preinit done\\n");
}

int
ar6000_ap_mode_profile_commit(struct ar6_softc *ar)
{
    WMI_CONNECT_CMD p;
    int status;
    unsigned long flags;
"""

# --- 4. do not inherit station ctrl_flags into an AP profile -----------------

FLAGS_OLD = """    p.ctrl_flags = ar->arConnectCtrlFlags;
"""

FLAGS_NEW = """    /* N3DS_AR6014_AP_PREINIT_SEQUENCE: the station connect path sweeps
     * arConnectCtrlFlags now, so an AP commit that inherits it would ship
     * whichever station variant happened to run last -- and with
     * CONNECT_PROFILE_MATCH_DONE in that set, it would be telling an AP to
     * skip a profile match it never makes.  An AP profile has no use for the
     * station association-policy bits; start it from zero. */
    ar->arConnectCtrlFlags = 0;
    p.ctrl_flags = ar->arConnectCtrlFlags;
"""

# --- 5. bracket the commit itself -------------------------------------------

SUBMIT_OLD = """    status = wmi_ap_profile_commit(ar->arWmi, &p);
    if (status != 0) {
"""

SUBMIT_NEW = """    n3ds_ar6000_ap_preinit(ar);

    /* N3DS_AR6014_AP_PREINIT_SEQUENCE: the last line before the target dies,
     * so an assert can be attributed to the commit rather than guessed at. */
    A_PRINTF("AR6002 AP: commit cmd=0x%04x submit nettype=%u chan=%u "
             "ssidlen=%u auth=%u dot11auth=%u pair=%u/%u group=%u/%u "
             "flags=0x%04x\\n",
             (unsigned int)WMI_AP_CONFIG_COMMIT_CMDID, p.networkType,
             p.channel, p.ssidLength, p.authMode, p.dot11AuthMode,
             p.pairwiseCryptoType, p.pairwiseCryptoLen,
             p.groupCryptoType, p.groupCryptoLen, p.ctrl_flags);
    status = wmi_ap_profile_commit(ar->arWmi, &p);
    A_PRINTF("AR6002 AP: commit cmd=0x%04x status=%d\\n",
             (unsigned int)WMI_AP_CONFIG_COMMIT_CMDID, status);
    if (status != 0) {
"""

HUNKS = (
    ("bmi fwmode trace", FWMODE_OLD, FWMODE_NEW),
    ("wmi ready trace", READY_OLD, READY_NEW),
    ("preinit sequence", COMMIT_OLD, COMMIT_NEW),
    ("ap ctrl_flags reset", FLAGS_OLD, FLAGS_NEW),
    ("commit bracket", SUBMIT_OLD, SUBMIT_NEW),
)


def patch_drv(text: str) -> str:
    """Add the AP pre-init sequence and bring-up traces.  Idempotent."""
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, (
            f"{name}: expected exactly one match, found {text.count(old)}")
        text = text.replace(old, new)
    return text


def main() -> None:
    original = DRV_C.read_text(encoding="utf-8")
    patched = patch_drv(original)
    if patched == original:
        print("ar6014_ap_preinit_sequence: already applied")
        return
    DRV_C.write_text(patched, encoding="utf-8")
    print(f"ar6014_ap_preinit_sequence: patched {DRV_C}")


if __name__ == "__main__":
    main()
