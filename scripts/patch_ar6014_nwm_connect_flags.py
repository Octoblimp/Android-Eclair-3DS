#!/usr/bin/env python3
"""Match Nintendo NWM's zero-valued WMI_CONNECT control flags."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


CFG = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
    "ath6k_legacy/os/linux/cfg80211.c"
)
MARKER = "N3DS_AR6014_NWM_CONNECT_FLAGS"

OLD = '''    ar->arConnectCtrlFlags |= DEFAULT_CONNECT_CTRL_FLAGS;
    if (ar->arReqBssid[0] || ar->arReqBssid[1] || ar->arReqBssid[2] ||
        ar->arReqBssid[3] || ar->arReqBssid[4] || ar->arReqBssid[5])
        ar->arConnectCtrlFlags |= CONNECT_PROFILE_MATCH_DONE;
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: submit channel=%u flags=0x%x bssid=%pM\\n",
         ar->arChannelHint, ar->arConnectCtrlFlags, ar->arReqBssid));
'''

NEW = '''    /* N3DS_AR6014_NWM_CONNECT_FLAGS: NWM zero-fills state +0x560 and
     * copies it unchanged to WMI_CONNECT +0x30 on the normal boot path. */
    ar->arConnectCtrlFlags = 0;
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM flags=0 submit channel=%u bssid=%pM\\n",
         ar->arChannelHint, ar->arReqBssid));
'''


def patch_cfg(text: str) -> str:
    if MARKER in text:
        return text
    count = text.count(OLD)
    if count != 1:
        raise RuntimeError(f"connect flags: expected one old block, found {count}")
    return text.replace(OLD, NEW, 1)


def main() -> None:
    if not CFG.is_file():
        raise SystemExit(f"missing canonical source: {CFG}")
    CFG.write_text(patch_cfg(CFG.read_text(encoding="utf-8")), encoding="utf-8")
    print("patch_ar6014_nwm_connect_flags: Nintendo flags=0 installed")


if __name__ == "__main__":
    main()
