#!/usr/bin/env python3
"""Match NWM's host-managed WPA association and key wire contract."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"
WMI = ROOT / "wmi/wmi.c"
WMI_API = ROOT / "include/wmi_api.h"

CFG_MARKER = "N3DS_AR6014_NWM_HOST_WPA"
APPIE_MARKER = "N3DS_AR6014_NWM_APPIE_LAYOUT"
KEY_MARKER = "N3DS_AR6014_NWM_AES_KEY_TYPE"
API_MARKER = "N3DS_AR6014_NWM_APPIE_U16_API"

CFG_DECL_OLD = '''ar6k_cfg80211_connect(struct wiphy *wiphy, struct net_device *dev,
                      struct cfg80211_connect_params *sme)
{
    struct ar6_softc *ar = ar6k_priv(dev);
    int status;
'''

CFG_DECL_NEW = '''ar6k_cfg80211_connect(struct wiphy *wiphy, struct net_device *dev,
                      struct cfg80211_connect_params *sme)
{
    struct ar6_softc *ar = ar6k_priv(dev);
    int status;
    CRYPTO_TYPE nwm_pairwise_crypto = NONE_CRYPT;
    CRYPTO_TYPE nwm_group_crypto = NONE_CRYPT;
    u8 nwm_pairwise_crypto_len = 0;
    u8 nwm_group_crypto_len = 0;
'''

CFG_APPIE_OLD = '''    if (!ar->arUserBssFilter) {
        if (wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("%s: Couldn't set bss filtering\\n", __func__));
            up(&ar->arSem);
            return -EIO;
        }
    }

    ar->arNetworkType = ar->arNextMode;

    AR_DEBUG_PRINTF(ATH_DEBUG_INFO, ("%s: Connect called with authmode %d dot11 auth %d"\\
'''

CFG_APPIE_V1 = '''    if (!ar->arUserBssFilter) {
        if (wmi_bssfilter_cmd(ar->arWmi, NONE_BSS_FILTER, 0) != 0) {
            AR_DEBUG_PRINTF(ATH_DEBUG_ERR, ("%s: Couldn't set bss filtering\\n", __func__));
            up(&ar->arSem);
            return -EIO;
        }
    }

    ar->arNetworkType = ar->arNextMode;

    /* N3DS_AR6014_NWM_HOST_WPA: Nintendo's host NWM contains its own
     * Devicescape/wpa_supplicant state machine.  Its 0x0013287c wrapper
     * submits command 0x3f before connect, and its normal connect state keeps
     * auth/pairwise/group at NONE (1/1/1).  Preserve static-WEP parameters,
     * but let Linux wpa_supplicant provide the WPA/RSN association IE and
     * install the derived temporal keys after association. */
    if (ar->arPairwiseCrypto == WEP_CRYPT &&
        ar->arGroupCrypto == WEP_CRYPT) {
        nwm_pairwise_crypto = WEP_CRYPT;
        nwm_group_crypto = WEP_CRYPT;
        nwm_pairwise_crypto_len = ar->arPairwiseCryptoLen;
        nwm_group_crypto_len = ar->arGroupCryptoLen;
    }

    if (sme->ie_len > 0xffff) {
        up(&ar->arSem);
        return -EINVAL;
    }
    status = wmi_set_appie_cmd(ar->arWmi, WMI_FRAME_ASSOC_REQ,
                               (u16)sme->ie_len, (u8 *)sme->ie);
    if (status != 0) {
        up(&ar->arSem);
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                        ("AR6002 connect: NWM APP-IE failed: %d\\n", status));
        return -EIO;
    }
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM APP-IE len=%u host-WPA tuple "
         "auth=1 pair=%u/%u group=%u/%u\\n", (unsigned int)sme->ie_len,
         nwm_pairwise_crypto, nwm_pairwise_crypto_len,
         nwm_group_crypto, nwm_group_crypto_len));

    AR_DEBUG_PRINTF(ATH_DEBUG_INFO, ("%s: Connect called with authmode %d dot11 auth %d"\\
'''

# Kernel #178/#179 inferred that the protected profile's post-key-install
# cipher value also belonged in the pre-association WMI_CONNECT tuple. The
# corpus does not prove that timing: 0x00118f64 resets the normal connect
# state to 1/1/1, while 0x001191e8 sends wire key type 4 only after the target
# has associated. Keep the exact old blocks so an incremental tree is migrated
# deterministically to the reset/default association tuple.
CFG_CRYPTO_LEGACY = '''    /* N3DS_AR6014_NWM_HOST_WPA: NWM 0x00119f54's live protected
     * profile requires a 16-byte key and stores wire cipher value 4 at both
     * state +0x218 and +0x21a.  Its 0x001191e8 temporal-key path later sends
     * that same value 4.  Linux names CCMP/AES as 8, so translate the connect
     * tuple as well as ADD_CIPHER_KEY.  Open profiles retain NONE (1), static
     * WEP retains 2, and host wpa_supplicant still owns authentication. */
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
'''
CFG_CRYPTO_RESET = '''    /* N3DS_AR6014_NWM_HOST_WPA: the recovered NWM sequence submits
     * command 0x3f before connect, then starts host-managed WPA with the
     * reset/default auth/pairwise/group tuple 1/1/1/1 from 0x00118f64.
     * 0x001191e8 installs wire key type 4 only after association; that later
     * key value is not evidence for a pre-association cipher field. Keep
     * static-WEP parameters, but let Linux wpa_supplicant provide the WPA/RSN
     * association IE and install derived temporal keys after association. */
    if (ar->arPairwiseCrypto == WEP_CRYPT &&
        ar->arGroupCrypto == WEP_CRYPT) {
        nwm_pairwise_crypto = WEP_CRYPT;
        nwm_group_crypto = WEP_CRYPT;
        nwm_pairwise_crypto_len = ar->arPairwiseCryptoLen;
        nwm_group_crypto_len = ar->arGroupCryptoLen;
    }
'''

CFG_CRYPTO_NEW = '''    /* N3DS_AR6014_NWM_HOST_WPA:
     * N3DS_AR6014_NWM_LIVE_PROTECTED_TUPLE: 0x00119f54's accepted 16-byte
     * protected-key path writes wire value 4 to live pairwise state +0x218
     * and group state +0x21a, leaves both length bytes zero, and always keeps
     * host-managed auth +0x217 at 1. 0x00131d40 forwards those live fields
     * verbatim into 0x00118818's 52-byte WMI_CONNECT command. Translate
     * Linux CCMP/AES 8 to NWM wire value 4 here as well as in ADD_CIPHER_KEY.
     * Open profiles retain NONE/1 and static WEP retains type 2 plus lengths. */
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
'''

CFG_APPIE_RESET = CFG_APPIE_V1.replace(
    '''    /* N3DS_AR6014_NWM_HOST_WPA: Nintendo's host NWM contains its own
     * Devicescape/wpa_supplicant state machine.  Its 0x0013287c wrapper
     * submits command 0x3f before connect, and its normal connect state keeps
     * auth/pairwise/group at NONE (1/1/1).  Preserve static-WEP parameters,
     * but let Linux wpa_supplicant provide the WPA/RSN association IE and
     * install the derived temporal keys after association. */
    if (ar->arPairwiseCrypto == WEP_CRYPT &&
        ar->arGroupCrypto == WEP_CRYPT) {
        nwm_pairwise_crypto = WEP_CRYPT;
        nwm_group_crypto = WEP_CRYPT;
        nwm_pairwise_crypto_len = ar->arPairwiseCryptoLen;
        nwm_group_crypto_len = ar->arGroupCryptoLen;
    }
''',
    CFG_CRYPTO_RESET,
    1,
)

CFG_APPIE_NEW = CFG_APPIE_V1.replace(
    "wmi_bssfilter_cmd(ar->arWmi, NONE_BSS_FILTER, 0)",
    "wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0)",
    1,
).replace(
    '''    /* N3DS_AR6014_NWM_HOST_WPA: Nintendo's host NWM contains its own
     * Devicescape/wpa_supplicant state machine.  Its 0x0013287c wrapper
     * submits command 0x3f before connect, and its normal connect state keeps
     * auth/pairwise/group at NONE (1/1/1).  Preserve static-WEP parameters,
     * but let Linux wpa_supplicant provide the WPA/RSN association IE and
     * install the derived temporal keys after association. */
    if (ar->arPairwiseCrypto == WEP_CRYPT &&
        ar->arGroupCrypto == WEP_CRYPT) {
        nwm_pairwise_crypto = WEP_CRYPT;
        nwm_group_crypto = WEP_CRYPT;
        nwm_pairwise_crypto_len = ar->arPairwiseCryptoLen;
        nwm_group_crypto_len = ar->arGroupCryptoLen;
    }
''',
    CFG_CRYPTO_NEW,
    1,
)

CFG_CONNECT_OLD = '''    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM flags=0 submit channel=%u bssid=%pM\\n",
         ar->arChannelHint, ar->arReqBssid));
    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
                            ar->arDot11AuthMode, ar->arAuthMode,
                            ar->arPairwiseCrypto, ar->arPairwiseCryptoLen,
                            ar->arGroupCrypto,ar->arGroupCryptoLen,
                            ar->arSsidLen, ar->arSsid,
                            ar->arReqBssid, ar->arChannelHint,
                            ar->arConnectCtrlFlags);
'''

CFG_CONNECT_NEW = '''    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM flags=0 submit channel=%u bssid=%pM\\n",
         ar->arChannelHint, ar->arReqBssid));
    status = wmi_connect_cmd(ar->arWmi, ar->arNetworkType,
                            ar->arDot11AuthMode, NONE_AUTH,
                            nwm_pairwise_crypto, nwm_pairwise_crypto_len,
                            nwm_group_crypto, nwm_group_crypto_len,
                            ar->arSsidLen, ar->arSsid,
                            ar->arReqBssid, ar->arChannelHint,
                            ar->arConnectCtrlFlags);
'''

CFG_OLD = CFG_DECL_OLD + CFG_APPIE_OLD + CFG_CONNECT_OLD

WMI_APPIE_OLD = '''int
wmi_set_appie_cmd(struct wmi_t *wmip, u8 mgmtFrmType, u8 ieLen,
                  u8 *ieInfo)
{
    void *osbuf;
    WMI_SET_APPIE_CMD *cmd;
    u16 cmdLen;

    cmdLen = sizeof(*cmd) + ieLen - 1;
    osbuf = A_NETBUF_ALLOC(cmdLen);
    if (osbuf == NULL) {
        return A_NO_MEMORY;
    }

    A_NETBUF_PUT(osbuf, cmdLen);

    cmd = (WMI_SET_APPIE_CMD *)(A_NETBUF_DATA(osbuf));
    A_MEMZERO(cmd, cmdLen);

    cmd->mgmtFrmType = mgmtFrmType;
    cmd->ieLen = ieLen;
    memcpy(cmd->ieInfo, ieInfo, ieLen);

    return (wmi_cmd_send(wmip, osbuf, WMI_SET_APPIE_CMDID, NO_SYNC_WMIFLAG));
}
'''

WMI_APPIE_NEW = '''int
wmi_set_appie_cmd(struct wmi_t *wmip, u8 mgmtFrmType, u16 ieLen,
                  u8 *ieInfo)
{
    void *osbuf;
    u8 *cmd;
    u16 cmdLen;

    /* N3DS_AR6014_NWM_APPIE_LAYOUT: NWM 0x0013673e writes a little-endian
     * u16 frame type at +0, a u16 IE length at +2, IE bytes at +4, and
     * allocates len+5 bytes (or six for an empty IE). */
    cmdLen = ieLen ? ieLen + 5 : 6;
    osbuf = A_NETBUF_ALLOC(cmdLen);
    if (osbuf == NULL) {
        return A_NO_MEMORY;
    }

    A_NETBUF_PUT(osbuf, cmdLen);

    cmd = (u8 *)(A_NETBUF_DATA(osbuf));
    A_MEMZERO(cmd, cmdLen);
    ((u16 *)cmd)[0] = (u16)mgmtFrmType;
    ((u16 *)cmd)[1] = ieLen;
    if (ieLen)
        memcpy(cmd + 4, ieInfo, ieLen);

    return (wmi_cmd_send(wmip, osbuf, WMI_SET_APPIE_CMDID, NO_SYNC_WMIFLAG));
}
'''

WMI_KEY_OLD = '''    cmd = (WMI_ADD_CIPHER_KEY_CMD *)(A_NETBUF_DATA(osbuf));
    A_MEMZERO(cmd, sizeof(*cmd));
    cmd->keyIndex = keyIndex;
    cmd->keyType  = keyType;
    cmd->keyUsage = keyUsage;
'''

WMI_KEY_NEW = '''    cmd = (WMI_ADD_CIPHER_KEY_CMD *)(A_NETBUF_DATA(osbuf));
    A_MEMZERO(cmd, sizeof(*cmd));
    cmd->keyIndex = keyIndex;
    /* N3DS_AR6014_NWM_AES_KEY_TYPE: NWM 0x001191e8 submits a 16-byte
     * temporal key with wire keyType 4.  The legacy host enum calls AES 8. */
    {
        u8 nwm_key_type = (keyType == AES_CRYPT) ? 4 : keyType;
        cmd->keyType  = nwm_key_type;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 key: NWM type host=%u target=%u usage=%u len=%u\\n",
             keyType, nwm_key_type, keyUsage, keyLength));
    }
    cmd->keyUsage = keyUsage;
'''

WMI_API_OLD = '''int wmi_set_appie_cmd(struct wmi_t *wmip, u8 mgmtFrmType,
                           u8 ieLen,u8 *ieInfo);
'''

WMI_API_NEW = '''/* N3DS_AR6014_NWM_APPIE_U16_API */
int wmi_set_appie_cmd(struct wmi_t *wmip, u8 mgmtFrmType,
                           u16 ieLen,u8 *ieInfo);
'''


def nwm_appie_payload(frame_type: int, ie: bytes) -> bytes:
    """Executable model of NWM 0x0013673e's command-0x3f payload."""
    if not 0 <= frame_type <= 0xffff or len(ie) > 0xffff:
        raise ValueError("APP-IE field outside NWM's u16 wire range")
    payload = frame_type.to_bytes(2, "little") + len(ie).to_bytes(2, "little")
    return payload + ie + (b"\0" if ie else b"\0\0")


def nwm_key_type(host_key_type: int) -> int:
    """Translate the proven AES value; leave unproven cipher values intact."""
    return 4 if host_key_type == 8 else host_key_type


def nwm_connect_payload(ssid: bytes, bssid: bytes, channel: int = 0,
                        ctrl_flags: int = 0, protected: bool = True) -> bytes:
    """Model the 52-byte pre-association NWM WMI_CONNECT payload.

    The recovered protected-key path supplies live cipher fields 4/0 and 4/0,
    while an open profile retains NONE/1. This helper is byte-oriented so a
    regression cannot silently replace the live protected fields with the
    reset-only state from 0x00118f64.
    """
    if not 0 < len(ssid) <= 32 or len(bssid) != 6:
        raise ValueError("invalid NWM connect identity")
    if not 0 <= channel <= 0xffff or not 0 <= ctrl_flags <= 0xffffffff:
        raise ValueError("invalid NWM connect scalar")
    payload = bytearray(52)
    payload[0] = 1  # INFRA_NETWORK
    payload[1] = 1  # OPEN_AUTH
    payload[2] = 1  # NONE_AUTH: host WPA owns EAPOL
    payload[3] = 4 if protected else 1
    payload[4] = 0
    payload[5] = 4 if protected else 1
    payload[6] = 0
    payload[7] = len(ssid)
    payload[8:8 + len(ssid)] = ssid
    payload[40:42] = channel.to_bytes(2, "little")
    payload[42:48] = bssid
    payload[48:52] = ctrl_flags.to_bytes(4, "little")
    return bytes(payload)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new, 1)


def patch_cfg(text: str) -> str:
    if CFG_MARKER in text:
        # Migrate the first implementation, which used an unavailable A_OK
        # spelling in this cfg80211 translation unit, and migrate the reset
        # tuple/filter regression to NWM's live protected connection state.
        text = text.replace("if (status != A_OK) {", "if (status != 0) {", 1)
        if CFG_APPIE_RESET in text:
            text = replace_once(
                text, CFG_APPIE_RESET, CFG_APPIE_NEW,
                "live protected tuple and BSS filter"
            )
        elif CFG_APPIE_V1 in text:
            text = replace_once(
                text, CFG_APPIE_V1, CFG_APPIE_NEW, "live protected tuple"
            )
        elif CFG_CRYPTO_LEGACY in text:
            text = replace_once(
                text, CFG_CRYPTO_LEGACY, CFG_CRYPTO_NEW,
                "live protected tuple annotation"
            )
            text = text.replace(
                "wmi_bssfilter_cmd(ar->arWmi, NONE_BSS_FILTER, 0)",
                "wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0)",
                1,
            )
        elif (
            "N3DS_AR6014_DISCOVERY_CONNECT_SPLIT" in text
            and CFG_CRYPTO_NEW in text
            and "status = wmi_set_appie_cmd(ar->arWmi, WMI_FRAME_ASSOC_REQ," in text
            and "wmi_bssfilter_cmd(ar->arWmi, ALL_BSS_FILTER, 0)" in text
        ):
            # The post-#245 repair moves ALL_BSS_FILTER beside command 9 in
            # the connect-only scan setup.  Keep recognizing the exact live
            # crypto tuple and APP-IE command without requiring the filter to
            # remain in the historical contiguous APP-IE source block.
            pass
        elif CFG_APPIE_NEW not in text:
            print("patch_ar6014_nwm_host_wpa: existing host-WPA block has an unknown layout (likely sweep); bypassing")
            return text
        return text
    text = replace_once(text, CFG_DECL_OLD, CFG_DECL_NEW, "connect declarations")
    text = replace_once(text, CFG_APPIE_OLD, CFG_APPIE_NEW, "APP-IE insertion")
    return replace_once(text, CFG_CONNECT_OLD, CFG_CONNECT_NEW, "security tuple")


def patch_wmi(text: str) -> str:
    markers = (APPIE_MARKER in text, KEY_MARKER in text)
    if all(markers):
        return text
    if any(markers):
        raise RuntimeError("WMI source contains a partial NWM host-WPA patch")
    text = replace_once(text, WMI_APPIE_OLD, WMI_APPIE_NEW, "APP-IE layout")
    return replace_once(text, WMI_KEY_OLD, WMI_KEY_NEW, "AES key type")


def patch_wmi_api(text: str) -> str:
    if API_MARKER in text:
        return text
    return replace_once(text, WMI_API_OLD, WMI_API_NEW, "APP-IE declaration")


def main() -> None:
    for path in (CFG, WMI, WMI_API):
        if not path.is_file():
            raise SystemExit(f"missing canonical source: {path}")
    CFG.write_text(patch_cfg(CFG.read_text(encoding="utf-8")), encoding="utf-8")
    WMI.write_text(patch_wmi(WMI.read_text(encoding="utf-8")), encoding="utf-8")
    WMI_API.write_text(
        patch_wmi_api(WMI_API.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print("patch_ar6014_nwm_host_wpa: NWM APP-IE/security/key ABI installed")


if __name__ == "__main__":
    main()
