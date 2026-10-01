#!/usr/bin/env python3
"""Match NWM's proven keepalive-zero command immediately before connect."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


WMI = Path(
    f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
    "ath6k_legacy/wmi/wmi.c"
)
MARKER = "N3DS_AR6014_NWM_PRECONNECT_KEEPALIVE"

OLD = '''    wmip->wmi_pair_crypto_type  = pairwiseCrypto;
    wmip->wmi_grp_crypto_type   = groupCrypto;

    return (wmi_cmd_send(wmip, osbuf, WMI_CONNECT_CMDID, NO_SYNC_WMIFLAG));
'''

NEW = '''    wmip->wmi_pair_crypto_type  = pairwiseCrypto;
    wmip->wmi_grp_crypto_type   = groupCrypto;

    /* N3DS_AR6014_NWM_PRECONNECT_KEEPALIVE: NWM's 0x00135d20
     * constructor zeroes the 0x38-byte WMI context.  At 0x00118894 it loads
     * context byte +0x24, sends command 0x3d with that byte (zero), checks
     * success, and only then sends WMI_CONNECT.  The legacy Linux path had
     * left its startup keepalive value at 60 and omitted this sequence. */
    if (wmi_set_keepalive_cmd(wmip, 0) != 0) {
        A_NETBUF_FREE(osbuf);
        return A_ERROR;
    }
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 connect: NWM pre-connect keepalive=0 submitted\\n"));
    return (wmi_cmd_send(wmip, osbuf, WMI_CONNECT_CMDID, NO_SYNC_WMIFLAG));
'''


def patch_wmi(text: str) -> str:
    if MARKER in text:
        return text
    count = text.count(OLD)
    if count != 1:
        raise RuntimeError(f"connect tail: expected one anchor, found {count}")
    return text.replace(OLD, NEW, 1)


def main() -> None:
    if not WMI.is_file():
        raise SystemExit(f"missing canonical source: {WMI}")
    WMI.write_text(patch_wmi(WMI.read_text()), encoding="utf-8")
    print("patch_ar6014_nwm_keepalive: keepalive-zero connect prerequisite installed")


if __name__ == "__main__":
    main()
