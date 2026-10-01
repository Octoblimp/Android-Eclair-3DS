#!/usr/bin/env python3
"""Stop handing channel 14 to an 802.11g WMI_SET_CHANNEL_PARAMS list.

WMI_SET_CHANNEL_PARAMS carries a single phyMode for the whole channel list,
and 802.11g is not legal on channel 14 (2484 MHz).  The 2026-09-01 hardware
capture logged 40 WMI_CMDERROR events in one boot, all of them

    AR6002 WMI CMDERROR: cmd=0x0011 (17) errorCode=1 (illegal parameter)

fired 2-50 ms after a discovery scan that had just submitted its 14-entry
2.4 GHz table with phyMode = WMI_11G_MODE -- and never once after a connect
attempt that submitted a single legal channel.  Correlation is exact in both
directions across the whole capture.

The consequence is worse than the log noise.  A rejected command changes
nothing on the target, so the persistent channel table that WMI_CONNECT's own
profile search reads was never actually reprogrammed by discovery: it kept
whatever the previous connect attempt had left behind.  Channel 14 is 11b-only
and Japan-only, so drop it from the 2.4 GHz table rather than splitting
discovery into a second 11b pass for a channel no AP here uses.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
CFG = ROOT / "os/linux/cfg80211.c"

MARKER = "N3DS_AR6014_11G_CHANNEL_LIST"

HELPER_OLD = '''static int n3ds_ar6014_set_search_channel(struct ar6_softc *ar, u16 mhz)
{
    u16 channel_list[1] = { mhz };
    int status;

    if (mhz != 2484 &&
        (mhz < 2412 || mhz > 2472 || ((mhz - 2412) % 5)))
        return -EINVAL;
'''

HELPER_NEW = '''/* N3DS_AR6014_11G_CHANNEL_LIST: WMI_SET_CHANNEL_PARAMS carries one phyMode
 * for the whole list and 802.11g is not legal on channel 14, so a list that
 * contains 2484 MHz is rejected outright with WMI_CMDERROR errorCode=1.  A
 * rejected command changes nothing on the target, which means the persistent
 * channel table WMI_CONNECT's own profile search reads was never reprogrammed
 * by discovery at all -- it kept whatever the previous connect attempt left
 * behind.  Hardware logged 40 of those rejections in one boot, every one of
 * them right after a 14-entry discovery table and never after a single-channel
 * connect table.  Channel 14 is 11b-only and Japan-only; drop it instead of
 * running discovery a second time in 11b just to cover it. */
static bool n3ds_ar6014_channel_is_11g(u16 mhz)
{
    return mhz >= 2412 && mhz <= 2472 && !((mhz - 2412) % 5);
}

static int n3ds_ar6014_set_search_channel(struct ar6_softc *ar, u16 mhz)
{
    u16 channel_list[1] = { mhz };
    int status;

    if (!n3ds_ar6014_channel_is_11g(mhz))
        return -EINVAL;
'''

SCAN_OLD = '''        u16 freq = request->channels[channel_index]->center_freq;

        if (freq == 2484 ||
            (freq >= 2412 && freq <= 2472 && !((freq - 2412) % 5)))
            channel_list[num_channels++] = freq;
    }
    if (!num_channels) {
        static const u16 ar6014_2ghz_channels[] = {
            2412, 2417, 2422, 2427, 2432, 2437, 2442,
            2447, 2452, 2457, 2462, 2467, 2472, 2484
        };
'''

SCAN_NEW = '''        u16 freq = request->channels[channel_index]->center_freq;

        /* N3DS_AR6014_11G_CHANNEL_LIST: 11G-legal frequencies only, or the
         * target rejects the whole WMI_SET_CHANNEL_PARAMS command below and
         * silently keeps its previous table. */
        if (n3ds_ar6014_channel_is_11g(freq))
            channel_list[num_channels++] = freq;
    }
    if (!num_channels) {
        static const u16 ar6014_2ghz_channels[] = {
            2412, 2417, 2422, 2427, 2432, 2437, 2442,
            2447, 2452, 2457, 2462, 2467, 2472
        };
'''

CONNECT_OLD = '''    if (cv->one_channel && ar->arChannelHint)
        status = n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
'''

CONNECT_NEW = '''    if (cv->one_channel && n3ds_ar6014_channel_is_11g(ar->arChannelHint))
        status = n3ds_ar6014_set_search_channel(ar, ar->arChannelHint);
'''

LOG_OLD = "AR6002 scan: START_SCAN submitted explicit_channels=%d"

LOG_NEW = "AR6002 scan: START_SCAN submitted explicit_11g_channels=%d"

HUNKS = (
    ("11g predicate", HELPER_OLD, HELPER_NEW),
    ("discovery channel filter", SCAN_OLD, SCAN_NEW),
    ("connect channel guard", CONNECT_OLD, CONNECT_NEW),
    ("scan submit log", LOG_OLD, LOG_NEW),
)


def patch_cfg(text: str) -> str:
    """Apply the 11G channel-list restriction to cfg80211.c source text.

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
        print("ar6014_11g_channel_list: already applied")
        return
    CFG.write_text(patched, encoding="utf-8")
    print(f"ar6014_11g_channel_list: patched {CFG}")


if __name__ == "__main__":
    main()
