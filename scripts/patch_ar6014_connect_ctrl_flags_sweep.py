#!/usr/bin/env python3
"""Re-aim the AR6014 connect sweep at WMI_CONNECT ctrl_flags (W5 + W7).

The previous sweep (patch_ar6014_connect_variant_sweep.py) ran to completion on
hardware and returned a clean negative: all 8 variants, 3 passes, ~36 attempts,
zero ASSOCIATED lines.  It swept auth (NONE_AUTH and WPA2_PSK_AUTH), crypto
(pair=1/0, 4/0 and 8/0 all observed on the wire -- which kills the TKIP-vs-CCMP
theory outright), BSSID (wildcard and both real mesh BSSIDs), the channel table
and the scan policy.  Every single attempt ended the same way:

    AR6002 connect: NWM disconnect len=11 reason=1 status=0
                    bssid=00:00:00:00:00:00 assoc=0

about 4.5 s after submit.  Two facts narrow this hard.  First, the firmware
demonstrably validates command parameters -- it rejected WMI_SET_CHANNEL_PARAMS
40 times in one boot with errorCode=1 -- and it never once complained about
WMI_CONNECT, so the 52-byte command is well formed and the command ID is right.
Second, reason=1 is NO_NETWORK_AVAIL: the firmware is reporting that *its own
internal connect-time scan* found nothing, against an AP the host scan sees at
-34 dBm.

That leaves the one field the driver has never varied: ctrl_flags, which has
been hardcoded to 0 on every attempt ever made.  CONNECT_PROFILE_MATCH_DONE
(0x0008) tells the target the host already matched the profile and to skip that
internal scan -- exactly the step that is failing.  This sweep centres on that
bit and covers the neighbouring policy bits around it.

W7 rides along: the per-attempt log now carries ctrl_flags, networkType and
dot11AuthMode, so a capture shows the whole submission rather than the half of
it the old log printed.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"

MARKER = "N3DS_AR6014_CONNECT_CTRL_FLAGS_SWEEP"

TABLE_OLD = """struct n3ds_connect_variant {
    const char *name;
    u8 real_auth;        /* send ar->arAuthMode instead of NONE_AUTH */
    u8 crypto;           /* 0 none, 4 NWM wire value, 8 Linux AES_CRYPT */
    u8 real_bssid;       /* lock sme->bssid instead of the wildcard */
    u8 one_channel;      /* restrict the target channel table to the hint */
    u8 stock_scan;       /* stock scan params instead of the NWM policy */
};

static const struct n3ds_connect_variant n3ds_connect_variants[] = {
    { "nwm",         0, 4, 0, 1, 0 },
    { "nwm-bssid",   0, 4, 1, 1, 0 },
    { "nwm-open",    0, 0, 0, 1, 0 },
    { "nwm-aes",     0, 8, 0, 1, 0 },
    { "stock",       1, 8, 1, 0, 1 },
    { "stock-wild",  1, 8, 0, 0, 1 },
    { "stock-chan",  1, 8, 1, 1, 0 },
    { "nwm-allchan", 0, 4, 0, 0, 1 },
};
"""

TABLE_NEW = """/* N3DS_AR6014_CONNECT_CTRL_FLAGS_SWEEP: the auth/crypto/bssid/channel/scan
 * sweep described above ran to completion on hardware and came back a clean
 * negative -- all 8 variants, 3 passes, roughly 36 attempts, zero ASSOCIATED
 * lines, every one ending "NWM disconnect ... reason=1" about 4.5 s after
 * submit.  The capture shows pair=1/0, pair=4/0 and pair=8/0 all going out on
 * the wire, so the TKIP-vs-CCMP reading of the NWM crypto value is settled and
 * wrong: crypto is not the problem, and neither is auth, BSSID, the channel
 * table nor the scan policy.
 *
 * Two observations from the same capture narrow what is left.  The firmware
 * plainly does validate what it is handed -- it rejected WMI_SET_CHANNEL_PARAMS
 * 40 times in a single boot with errorCode=1 (illegal parameter) -- and it
 * never once objected to WMI_CONNECT, so the 52-byte command is well formed
 * and its ID is correct.  And reason=1 is NO_NETWORK_AVAIL, which is the
 * target reporting that *its own* connect-time scan found nothing, for an AP
 * the host scan had logged at -34 dBm moments earlier.
 *
 * ctrl_flags is the one field of that command this driver has never varied:
 * it has been hardcoded to 0 on every attempt ever sent.  Bit 0x0008,
 * CONNECT_PROFILE_MATCH_DONE, tells the target the host has already matched
 * the profile and that it should associate directly instead of running the
 * internal scan that keeps coming up empty.  This table centres on that bit
 * and brackets it with the neighbouring association-policy bits; row 7 holds
 * flags=0 as the control, so one boot still contains the old behaviour to
 * compare against.  The other five axes stay in the struct at the settings
 * that got furthest before, and still vary enough to re-check them for free.
 */
struct n3ds_connect_variant {
    const char *name;
    u8 real_auth;        /* send ar->arAuthMode instead of NONE_AUTH */
    u8 crypto;           /* 0 none, 4 NWM wire value, 8 Linux AES_CRYPT */
    u8 real_bssid;       /* lock sme->bssid instead of the wildcard */
    u8 one_channel;      /* restrict the target channel table to the hint */
    u8 stock_scan;       /* stock scan params instead of the NWM policy */
    u16 ctrl_flags;      /* WMI_CONNECT_CMD.ctrl_flags, never before varied */
};

static const struct n3ds_connect_variant n3ds_connect_variants[] = {
    { "match-done",  1, 8, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE },
    { "match-user",  1, 8, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE |
                                    CONNECT_ASSOC_POLICY_USER },
    { "match-nwm",   0, 4, 1, 1, 0, CONNECT_PROFILE_MATCH_DONE },
    { "match-open",  1, 0, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE |
                                    CONNECT_IGNORE_WPAx_GROUP_CIPHER },
    { "user-policy", 1, 8, 1, 0, 1, CONNECT_ASSOC_POLICY_USER },
    { "csa-default", 1, 8, 0, 0, 1, DEFAULT_CONNECT_CTRL_FLAGS },
    { "match-csa",   1, 8, 1, 1, 0, CONNECT_PROFILE_MATCH_DONE |
                                    CONNECT_CSA_FOLLOW_BSS },
    { "flags-none",  1, 8, 1, 1, 1, 0 },
};
"""

LOG_OLD = """    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: VARIANT %d %s auth=%u pair=%u/%u group=%u/%u "
         "bssid=%pM chan=%u onechan=%u stockscan=%u\\n",
         n3ds_connect_current, cv->name,
         cv->real_auth ? ar->arAuthMode : (unsigned int)NONE_AUTH,
         nwm_pairwise_crypto, nwm_pairwise_crypto_len,
         nwm_group_crypto, nwm_group_crypto_len,
         ar->arReqBssid, ar->arChannelHint,
         cv->one_channel, cv->stock_scan));
    /* N3DS_AR6014_NWM_CONNECT_FLAGS: NWM zero-fills state +0x560 and
     * copies it unchanged to WMI_CONNECT +0x30 on the normal boot path. */
    ar->arConnectCtrlFlags = 0;
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM flags=0 submit channel=%u bssid=%pM\\n",
         ar->arChannelHint, ar->arReqBssid));
"""

LOG_NEW = """    /* N3DS_AR6014_CONNECT_CTRL_FLAGS_SWEEP: ctrl_flags is swept now, not
     * pinned to 0 as the earlier NWM reading assumed.  Print every field of
     * the 52-byte WMI_CONNECT_CMD this driver chooses, so one capture pins the
     * whole submission instead of the half the old log covered. */
    ar->arConnectCtrlFlags = cv->ctrl_flags;
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: VARIANT %d %s auth=%u pair=%u/%u group=%u/%u "
         "bssid=%pM chan=%u onechan=%u stockscan=%u "
         "flags=0x%04x nettype=%u dot11auth=%u ssidlen=%u\\n",
         n3ds_connect_current, cv->name,
         cv->real_auth ? ar->arAuthMode : (unsigned int)NONE_AUTH,
         nwm_pairwise_crypto, nwm_pairwise_crypto_len,
         nwm_group_crypto, nwm_group_crypto_len,
         ar->arReqBssid, ar->arChannelHint,
         cv->one_channel, cv->stock_scan,
         ar->arConnectCtrlFlags, ar->arNetworkType, ar->arDot11AuthMode,
         ar->arSsidLen));
"""

HUNKS = (
    ("variant table", TABLE_OLD, TABLE_NEW),
    ("connect submit log", LOG_OLD, LOG_NEW),
)


def patch_cfg(text: str) -> str:
    """Swap the exhausted parameter sweep for a ctrl_flags sweep.

    Idempotent: an already-patched tree is returned untouched.
    """
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def main() -> None:
    original = CFG.read_text(encoding="utf-8")
    patched = patch_cfg(original)
    if patched == original:
        print("ar6014_connect_ctrl_flags_sweep: already applied")
        return
    CFG.write_text(patched, encoding="utf-8")
    print(f"ar6014_connect_ctrl_flags_sweep: patched {CFG}")


if __name__ == "__main__":
    main()
