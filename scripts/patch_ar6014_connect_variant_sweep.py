#!/usr/bin/env python3
"""Sweep the AR6014 WMI_CONNECT parameter space one attempt at a time.

Every WMI_CONNECT this driver has sent to the NWM firmware comes back as
DISCONNECT reason 1 (NO_NETWORK_AVAIL) about 4.5 s later, while the host
discovery scan lists the very same BSS at -34 dBm moments earlier.  Four
independent single-variable guesses have each cost a full flash/boot/
photograph cycle and none of them moved the failure, because the connect
submission carries four genuinely independent unknowns at once (auth mode,
crypto wire values, BSSID locking, and scan policy).

Sweeping one variant per connect attempt turns a single boot into the whole
experiment: wpa_supplicant retries roughly every 5 s, so a dozen or more
variants get tried and the one that associates names itself in the log.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"

MARKER = "N3DS_AR6014_CONNECT_VARIANT_SWEEP"

TABLE_OLD = '''static int
ar6k_cfg80211_connect(struct wiphy *wiphy, struct net_device *dev,
                      struct cfg80211_connect_params *sme)
{
    struct ar6_softc *ar = ar6k_priv(dev);
    int status;
    CRYPTO_TYPE nwm_pairwise_crypto = NONE_CRYPT;
    CRYPTO_TYPE nwm_group_crypto = NONE_CRYPT;
    u8 nwm_pairwise_crypto_len = 0;
    u8 nwm_group_crypto_len = 0;

    AR_DEBUG_PRINTF(ATH_DEBUG_INFO, ("%s: \\n", __func__));
    ar->smeState = SME_CONNECTING;
'''

TABLE_NEW = '''/* N3DS_AR6014_CONNECT_VARIANT_SWEEP: every WMI_CONNECT this driver has sent
 * to the NWM firmware comes back as DISCONNECT reason 1 (NO_NETWORK_AVAIL)
 * about 4.5 s later, while the host discovery scan lists that same BSS at
 * -34 dBm moments earlier.  Several single-variable guesses have each cost a
 * full flash/boot/photograph cycle and none of them moved the failure,
 * because the submission carries four genuinely independent unknowns at once:
 *
 *   auth   - the NWM disassembly reads authMode as always 1 (NONE_AUTH) with
 *            the host owning WPA, while stock ath6kl sends WPA2_PSK_AUTH.
 *   crypto - the disassembly's "wire value 4" is TKIP_CRYPT in this header's
 *            CRYPTO_TYPE enum, so a CCMP-only AP may simply never match the
 *            profile the target is searching for.
 *   bssid  - a locked BSSID and a wildcard have both been tried, but never
 *            against a known-good setting of the other three.
 *   scan   - the NWM scan policy (0xffff periods, 20 ms dwell, single-channel
 *            table) against this driver's stock scan defaults.
 *
 * One variant per connect attempt turns a single boot into the whole
 * experiment: wpa_supplicant retries roughly every 5 s and gets a dozen or
 * more attempts in, so the association that works names itself in the log.
 * The first variant that associates is latched for the rest of the session so
 * the link stays up.  n3ds_connvar pins one variant for a confirmation run.
 */
struct n3ds_connect_variant {
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

static int n3ds_connvar = -1;
module_param(n3ds_connvar, int, 0644);
MODULE_PARM_DESC(n3ds_connvar,
    "pin one AR6014 connect variant (-1 sweeps until one associates)");

static unsigned int n3ds_connect_attempt;
static int n3ds_connect_latched = -1;
static int n3ds_connect_current = -1;

/* numChannels 0 hands the channel list back to the target's own phy-mode
 * default, undoing a single-channel table left behind by an earlier variant. */
static int n3ds_ar6014_set_all_channels(struct ar6_softc *ar)
{
    int status = wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE,
                                           0, NULL);

    if (status != 0)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: full channel table failed status=%d\\n", status));
    return status;
}

static int
ar6k_cfg80211_connect(struct wiphy *wiphy, struct net_device *dev,
                      struct cfg80211_connect_params *sme)
{
    struct ar6_softc *ar = ar6k_priv(dev);
    const struct n3ds_connect_variant *cv;
    int status;
    CRYPTO_TYPE nwm_pairwise_crypto = NONE_CRYPT;
    CRYPTO_TYPE nwm_group_crypto = NONE_CRYPT;
    u8 nwm_pairwise_crypto_len = 0;
    u8 nwm_group_crypto_len = 0;

    AR_DEBUG_PRINTF(ATH_DEBUG_INFO, ("%s: \\n", __func__));
    ar->smeState = SME_CONNECTING;

    if (n3ds_connvar >= 0 &&
        n3ds_connvar < (int)ARRAY_SIZE(n3ds_connect_variants))
        n3ds_connect_current = n3ds_connvar;
    else if (n3ds_connect_latched >= 0)
        n3ds_connect_current = n3ds_connect_latched;
    else
        n3ds_connect_current =
            (int)(n3ds_connect_attempt % ARRAY_SIZE(n3ds_connect_variants));
    n3ds_connect_attempt++;
    cv = &n3ds_connect_variants[n3ds_connect_current];
'''

BSSID_OLD = '''     * already does. */
    A_MEMZERO(ar->arReqBssid, sizeof(ar->arReqBssid));
'''

BSSID_NEW = '''     * already does.  The sweep still tries a locked BSSID, because that
     * reading was never tested against a known-good auth/crypto tuple. */
    A_MEMZERO(ar->arReqBssid, sizeof(ar->arReqBssid));
    if (cv->real_bssid && sme->bssid)
        memcpy(ar->arReqBssid, sme->bssid, ATH_MAC_LEN);
'''

CRYPTO_OLD = '''    if (ar->arPairwiseCrypto == AES_CRYPT &&
        ar->arGroupCrypto == AES_CRYPT) {
        nwm_pairwise_crypto = (CRYPTO_TYPE)4;
        nwm_group_crypto = (CRYPTO_TYPE)4;
    } else if (ar->arPairwiseCrypto == WEP_CRYPT &&
               ar->arGroupCrypto == WEP_CRYPT) {
        nwm_pairwise_crypto = WEP_CRYPT;
        nwm_group_crypto = WEP_CRYPT;
        nwm_pairwise_crypto_len = ar->arPairwiseCryptoLen;
        nwm_group_crypto_len = ar->arGroupCryptoLen;
    }
'''

CRYPTO_NEW = '''    if (cv->crypto == 8) {
        /* What stock ath6kl_legacy sends: the ciphers cfg80211 asked for. */
        nwm_pairwise_crypto = (CRYPTO_TYPE)ar->arPairwiseCrypto;
        nwm_group_crypto = (CRYPTO_TYPE)ar->arGroupCrypto;
        nwm_pairwise_crypto_len = ar->arPairwiseCryptoLen;
        nwm_group_crypto_len = ar->arGroupCryptoLen;
    } else if (cv->crypto == 4) {
        if (ar->arPairwiseCrypto == AES_CRYPT &&
            ar->arGroupCrypto == AES_CRYPT) {
            nwm_pairwise_crypto = (CRYPTO_TYPE)4;
            nwm_group_crypto = (CRYPTO_TYPE)4;
        } else if (ar->arPairwiseCrypto == WEP_CRYPT &&
                   ar->arGroupCrypto == WEP_CRYPT) {
            nwm_pairwise_crypto = WEP_CRYPT;
            nwm_group_crypto = WEP_CRYPT;
            nwm_pairwise_crypto_len = ar->arPairwiseCryptoLen;
            nwm_group_crypto_len = ar->arGroupCryptoLen;
        }
    }
    /* cv->crypto == 0 leaves NONE/NONE: a bare open association with every
     * cipher left to the host supplicant. */
'''

SCAN_OLD = '''    status = wmi_scanparams_cmd(ar->arWmi, 0xffff, 0xffff, 0xffff,
                                N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                0, N3DS_NWM_CONNECT_SCAN_FLAGS, 0,
                                N3DS_NWM_SCAN_PROBES_PER_SSID);
    if (status != 0) {
        wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);
        up(&ar->arSem);
        return -EIO;
    }
    if (ar->arChannelHint) {
        status = n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
        if (status != 0) {
            wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);
            up(&ar->arSem);
            return -EIO;
        }
    }
'''

SCAN_NEW = '''    if (cv->stock_scan)
        status = wmi_scanparams_cmd(ar->arWmi, 0, 0, 0, 0, 0, 0,
                                    WMI_SHORTSCANRATIO_DEFAULT,
                                    DEFAULT_SCAN_CTRL_FLAGS, 0,
                                    N3DS_NWM_SCAN_PROBES_PER_SSID);
    else
        status = wmi_scanparams_cmd(ar->arWmi, 0xffff, 0xffff, 0xffff,
                                    N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                    N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                    N3DS_NWM_CONNECT_SCAN_DWELL_MS,
                                    0, N3DS_NWM_CONNECT_SCAN_FLAGS, 0,
                                    N3DS_NWM_SCAN_PROBES_PER_SSID);
    if (status != 0) {
        wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);
        up(&ar->arSem);
        return -EIO;
    }
    if (cv->one_channel && ar->arChannelHint)
        status = n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
    else
        status = n3ds_ar6014_set_all_channels(ar);
    if (status != 0) {
        wmi_probedSsid_cmd(ar->arWmi, 0, DISABLE_SSID_FLAG, 0, NULL);
        up(&ar->arSem);
        return -EIO;
    }
'''

LOG_OLD = '''    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM scan policy flags=0x%x dwell=%u slot=0 channel=%u\\n",
         N3DS_NWM_CONNECT_SCAN_FLAGS, N3DS_NWM_CONNECT_SCAN_DWELL_MS,
         ar->arChannelHint));
'''

LOG_NEW = '''    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: VARIANT %d %s auth=%u pair=%u/%u group=%u/%u "
         "bssid=%pM chan=%u onechan=%u stockscan=%u\\n",
         n3ds_connect_current, cv->name,
         cv->real_auth ? ar->arAuthMode : (unsigned int)NONE_AUTH,
         nwm_pairwise_crypto, nwm_pairwise_crypto_len,
         nwm_group_crypto, nwm_group_crypto_len,
         ar->arReqBssid, ar->arChannelHint,
         cv->one_channel, cv->stock_scan));
'''

AUTH_OLD = '''    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
                            ar->arDot11AuthMode, NONE_AUTH,
'''

AUTH_NEW = '''    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
                            ar->arDot11AuthMode,
                            cv->real_auth ? (AUTH_MODE)ar->arAuthMode
                                          : NONE_AUTH,
'''

LATCH_OLD = '''    ar->arAutoAuthStage = AUTH_IDLE;

    if((ADHOC_NETWORK & networkType)) {
'''

LATCH_NEW = '''    ar->arAutoAuthStage = AUTH_IDLE;

    /* N3DS_AR6014_CONNECT_VARIANT_SWEEP: name the winner loudly and stop
     * sweeping, so the rest of the session keeps using whatever worked. */
    if (n3ds_connect_current >= 0 && n3ds_connect_latched < 0) {
        n3ds_connect_latched = n3ds_connect_current;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: VARIANT %d %s ASSOCIATED channel=%u bssid=%pM\\n",
             n3ds_connect_current,
             n3ds_connect_variants[n3ds_connect_current].name,
             channel, bssid));
    }

    if((ADHOC_NETWORK & networkType)) {
'''

HUNKS = (
    ("variant table", TABLE_OLD, TABLE_NEW),
    ("bssid", BSSID_OLD, BSSID_NEW),
    ("crypto", CRYPTO_OLD, CRYPTO_NEW),
    ("scan params", SCAN_OLD, SCAN_NEW),
    ("variant log", LOG_OLD, LOG_NEW),
    ("auth mode", AUTH_OLD, AUTH_NEW),
    ("association latch", LATCH_OLD, LATCH_NEW),
)


def patch_cfg(text: str) -> str:
    """Apply the sweep to cfg80211.c source text.

    Idempotent: an already-patched tree is returned untouched so the patcher
    can be re-run after an unrelated driver change without duplicating the
    variant table.
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
        print("ar6014_connect_variant_sweep: already applied")
        return
    CFG.write_text(patched, encoding="utf-8")
    print(f"ar6014_connect_variant_sweep: patched {CFG}")


if __name__ == "__main__":
    main()
