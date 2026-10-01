#!/usr/bin/env python3
"""Program AR6014's persistent channel table like Nintendo NWM."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


CFG = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
    "ath6k_legacy/os/linux/cfg80211.c"
)
MARKER = "N3DS_AR6014_NWM_CHANNEL_TABLE"

HELPER_OLD = '''/* N3DS_AR6014_ASSOCIATION_COMPAT: this exact Nintendo type-4 image keeps
 * connect-time channel entry zero at 0x525548.  The public 3DS capture proved
 * WMI_CONNECT's channel field is ignored.  Validate entries 1..3 before
 * changing entry zero so a different firmware build fails closed. */
#define N3DS_AR6014_CHANNEL_TABLE 0x00525548
static int n3ds_ar6014_set_search_channel(struct ar6_softc *ar, u16 mhz)
{
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: search channel %u -> %u MHz\\n", mhz, mhz));
    return 0;
}
'''

HELPER_NEW = '''/* N3DS_AR6014_ASSOCIATION_COMPAT:
 * N3DS_AR6014_NWM_CHANNEL_TABLE: NWM 0x0012ad70 calls 0x0011aa2c before
 * its discovery/connect scan.  The 0x00136830 serializer sends command 17
 * with scanParam=0, phyMode=2 (11G), and a MHz channel list.  cfg80211 had
 * supplied channels only to START_SCAN, leaving the persistent target table
 * used by WMI_CONNECT's own search unprogrammed.  Use the command ABI rather
 * than the retired direct target-RAM experiment. */
static int n3ds_ar6014_set_search_channel(struct ar6_softc *ar, u16 mhz)
{
    u16 channel_list[1] = { mhz };
    int status;

    if (mhz != 2484 &&
        (mhz < 2412 || mhz > 2472 || ((mhz - 2412) % 5)))
        return -EINVAL;

    status = wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE,
                                       ARRAY_SIZE(channel_list), channel_list);
    if (status != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: NWM channel table failed channel=%u status=%d\\n",
             mhz, status));
        return status;
    }

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: search channel %u; NWM channel table mode=11G count=1\\n",
         mhz));
    return 0;
}
'''

CONNECT_OLD = '''    if (ar->arChannelHint)
        n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
'''

CONNECT_NEW = '''    if (ar->arChannelHint) {
        status = n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
        if (status != 0) {
            up(&ar->arSem);
            return -EIO;
        }
    }
'''

SCAN_ANCHOR = '''    /* N3DS_CFG80211_SCAN_REQUEST_ORDER: the Nintendo target can report an
'''

SCAN_SETUP = '''    /* N3DS_AR6014_NWM_CHANNEL_TABLE: command 17 persists the 11G MHz
     * channel set used by the target-owned WMI_CONNECT search.  START_SCAN's
     * separate list is retained because it bounds this host-requested scan. */
    if (wmi_set_channelParams_cmd(ar->arWmi, 0, WMI_11G_MODE,
                                  num_channels, channel_list) != 0) {
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: NWM channel table programming failed channels=%d\\n",
             num_channels));
        return -EIO;
    }
    if (trace_scan)
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 scan: NWM channel table mode=11G channels=%d\\n",
             num_channels));

'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def nwm_channel_payload(channels: list[int]) -> bytes:
    """Model NWM command-17 payload bytes for focused ABI tests."""
    if not channels or len(channels) > 32:
        raise ValueError("channel count must be 1..32")
    for channel in channels:
        if channel != 2484 and (
            channel < 2412 or channel > 2472 or (channel - 2412) % 5
        ):
            raise ValueError(f"invalid AR6014 2.4-GHz channel: {channel}")
    payload = bytearray((0, 0, 2, len(channels)))
    for channel in channels:
        payload += channel.to_bytes(2, "little")
    return bytes(payload)


def patch_cfg(text: str) -> str:
    if MARKER in text:
        return text
    text = replace_once(text, HELPER_OLD, HELPER_NEW, "channel helper")
    text = replace_once(text, CONNECT_OLD, CONNECT_NEW, "connect propagation")
    return replace_once(
        text, SCAN_ANCHOR, SCAN_SETUP + SCAN_ANCHOR, "scan channel setup"
    )


def main() -> None:
    original = CFG.read_text(encoding="utf-8")
    patched = patch_cfg(original)
    if patched != original:
        CFG.write_text(patched, encoding="utf-8")
        print("ar6014_nwm_channel_table: patched")
    else:
        print("ar6014_nwm_channel_table: already patched")


if __name__ == "__main__":
    main()
