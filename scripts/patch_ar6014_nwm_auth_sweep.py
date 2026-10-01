#!/usr/bin/env python3
"""Sweep AR6014 authMode/crypto, and stop latching on bare association.

Build #256 associated to HomeWifi and then carried nothing.  The link stayed
up for a full ten seconds, the census read frames=0 eapol_rx=0, and
wpa_supplicant gave up by itself ("Authentication with 8c:dd:0b:00:53:c8
timed out") and issued a locally generated deauth.  So association is not the
milestone worth latching on -- it is reached by the very tuple that fails.

Two things follow, and this patcher does both.

1. The old latch fired on association, which froze the sweep on row 0 for all
   19 connect attempts of the boot.  Every other row has been unreachable on
   hardware since the ctrl_flags fix landed in #253.  Latch on the link
   actually carrying an EAPOL frame instead.

2. With the sweep unfrozen, spend it on the axis the NWM disassembly says we
   have wrong.  That disassembly reads authMode as always 1 (NONE_AUTH) with
   the host owning WPA, and writes wire value 4 into both cipher fields with
   the length bytes left at zero.  The #256 wire dump shows we send authMode
   0x10 (WPA2_PSK_AUTH) with 8/8.  Handing NWM a real authMode plausibly puts
   the firmware in charge of WPA -- it then consumes message 1/4 internally,
   has no PSK, and never forwards the handshake to the host.  That single
   mechanism produces association-succeeds, frames=0, eapol_rx=0 and the AP
   giving up, all at once.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"
DRV = ROOT / "os/linux/ar6000_drv.c"
HDR = ROOT / "os/linux/include/ar6000_drv.h"

MARKER = "N3DS_AR6014_NWM_AUTH_SWEEP"

TABLE_OLD = '''static const struct n3ds_connect_variant n3ds_connect_variants[] = {
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
'''

TABLE_NEW = '''/* N3DS_AR6014_NWM_AUTH_SWEEP: #253 proved the geometry -- a pinned BSSID, a
 * single channel and CONNECT_PROFILE_MATCH_DONE are what make NWM associate
 * at all -- so those are held fixed here and no longer swept.  What varies
 * is authMode and the cipher wire values, the one axis the NWM disassembly
 * says this driver still has wrong: it reads authMode as always 1
 * (NONE_AUTH) with the host owning WPA and wire value 4 in both cipher
 * fields with zero lengths, while #256 sent 0x10 (WPA2_PSK_AUTH) with 8/8.
 * If a real authMode hands WPA to the firmware, NWM eats message 1/4 with no
 * PSK to answer it, which is exactly the observed failure.  Row 3 reproduces
 * #256 byte for byte as the control. */
static const struct n3ds_connect_variant n3ds_connect_variants[] = {
    { "nwm-auth",    0, 4, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE },
    { "nwm-open",    0, 0, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE },
    { "nwm-aes",     0, 8, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE },
    { "match-done",  1, 8, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE },
    { "real-nwm",    1, 4, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE },
    { "nwm-user",    0, 4, 1, 1, 1, CONNECT_PROFILE_MATCH_DONE |
                                    CONNECT_ASSOC_POLICY_USER },
    { "nwm-noflags", 0, 4, 1, 1, 1, 0 },
    { "nwm-nwmscan", 0, 4, 1, 1, 0, CONNECT_PROFILE_MATCH_DONE },
};
'''

STATE_OLD = '''static unsigned int n3ds_connect_attempt;
static int n3ds_connect_latched = -1;
static int n3ds_connect_current = -1;
'''

STATE_NEW = '''static unsigned int n3ds_connect_attempt;
static int n3ds_connect_latched = -1;
static int n3ds_connect_current = -1;

/* N3DS_AR6014_NWM_AUTH_SWEEP: which variant produced the most recent
 * association.  It is latched later, and only if that association went on to
 * carry a handshake frame.  n3ds_eapol_rx_count is zeroed by
 * ar6000_connect_event() on every association, so a non-zero read at the next
 * connect attempt belongs to the association this variable names. */
static int n3ds_connect_assoc_variant = -1;
'''

SELECT_OLD = '''    if (n3ds_connvar >= 0 &&
        n3ds_connvar < (int)ARRAY_SIZE(n3ds_connect_variants))
        n3ds_connect_current = n3ds_connvar;
'''

SELECT_NEW = '''    /* N3DS_AR6014_NWM_AUTH_SWEEP: latch the previous variant only if the
     * association it produced actually carried EAPOL.  Latching on
     * association alone pinned row 0 for all 19 attempts of #256 and left
     * every other row untried on hardware. */
    if (n3ds_connect_latched < 0 && n3ds_connect_assoc_variant >= 0 &&
        atomic_read(&n3ds_eapol_rx_count) > 0) {
        n3ds_connect_latched = n3ds_connect_assoc_variant;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: VARIANT %d %s CARRIED EAPOL rx=%d, latching\\n",
             n3ds_connect_latched,
             n3ds_connect_variants[n3ds_connect_latched].name,
             atomic_read(&n3ds_eapol_rx_count)));
    }

    if (n3ds_connvar >= 0 &&
        n3ds_connvar < (int)ARRAY_SIZE(n3ds_connect_variants))
        n3ds_connect_current = n3ds_connvar;
'''

LATCH_OLD = '''    /* N3DS_AR6014_CONNECT_VARIANT_SWEEP: name the winner loudly and stop
     * sweeping, so the rest of the session keeps using whatever worked. */
    if (n3ds_connect_current >= 0 && n3ds_connect_latched < 0) {
        n3ds_connect_latched = n3ds_connect_current;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: VARIANT %d %s ASSOCIATED channel=%u bssid=%pM\\n",
             n3ds_connect_current,
             n3ds_connect_variants[n3ds_connect_current].name,
             channel, bssid));
    }
'''

LATCH_NEW = '''    /* N3DS_AR6014_NWM_AUTH_SWEEP: associating is not winning.  Record the
     * variant and let the next connect attempt decide, once it can see
     * whether this association carried a handshake.  prev_eapol_rx is the
     * count still standing from the *previous* association, because
     * ar6000_connect_event() zeroes the counter just after this returns. */
    if (n3ds_connect_current >= 0) {
        n3ds_connect_assoc_variant = n3ds_connect_current;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: VARIANT %d %s ASSOCIATED channel=%u bssid=%pM "
             "prev_eapol_rx=%d\\n",
             n3ds_connect_current,
             n3ds_connect_variants[n3ds_connect_current].name,
             channel, bssid, atomic_read(&n3ds_eapol_rx_count)));
    }
'''

DRV_OLD = '''static atomic_t n3ds_eapol_tx_count = ATOMIC_INIT(0);
static atomic_t n3ds_eapol_rx_count = ATOMIC_INIT(0);
'''

DRV_NEW = '''static atomic_t n3ds_eapol_tx_count = ATOMIC_INIT(0);
/* N3DS_AR6014_NWM_AUTH_SWEEP: the connect-variant latch in cfg80211.c keys
 * off this counter, so it has to leave this translation unit. */
atomic_t n3ds_eapol_rx_count = ATOMIC_INIT(0);
'''

HDR_OLD = '''extern u8 bcast_mac[];
'''

HDR_NEW = '''/* N3DS_AR6014_NWM_AUTH_SWEEP: EAPOL receive counter, defined in
 * ar6000_drv.c, read by the connect-variant latch in cfg80211.c. */
extern atomic_t n3ds_eapol_rx_count;

extern u8 bcast_mac[];
'''

CFG_HUNKS = (
    ("variant table", TABLE_OLD, TABLE_NEW),
    ("latch state", STATE_OLD, STATE_NEW),
    ("latch decision", SELECT_OLD, SELECT_NEW),
    ("association record", LATCH_OLD, LATCH_NEW),
)

DRV_HUNKS = (("eapol counter linkage", DRV_OLD, DRV_NEW),)

HDR_HUNKS = (("eapol counter extern", HDR_OLD, HDR_NEW),)


def _apply(text, hunks):
    if MARKER in text:
        return text
    for name, old, new in hunks:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def patch_cfg(text: str) -> str:
    """Apply the auth/crypto sweep and the EAPOL latch to cfg80211.c.

    Idempotent: an already-patched tree is returned untouched so the patcher
    can be re-run after an unrelated driver change.
    """
    return _apply(text, CFG_HUNKS)


def patch_drv(text: str) -> str:
    """Give n3ds_eapol_rx_count external linkage in ar6000_drv.c."""
    return _apply(text, DRV_HUNKS)


def patch_hdr(text: str) -> str:
    """Declare n3ds_eapol_rx_count in the shared ar6000_drv.h."""
    return _apply(text, HDR_HUNKS)


def main() -> None:
    changed = False
    for path, fn in ((CFG, patch_cfg), (DRV, patch_drv), (HDR, patch_hdr)):
        original = path.read_text(encoding="utf-8")
        patched = fn(original)
        if patched != original:
            path.write_text(patched, encoding="utf-8")
            print(f"ar6014_nwm_auth_sweep: patched {path}")
            changed = True
    if not changed:
        print("ar6014_nwm_auth_sweep: already applied")


if __name__ == "__main__":
    main()
