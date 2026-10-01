#!/usr/bin/env python3
"""Parse Nintendo NWM's MAC-first 16-byte WMI READY event exactly."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


WMI = Path(
    f"{A3DS_ROOT}/third_party/linux/"
    "drivers/staging/ath6k_legacy/wmi/wmi.c"
)
MARKER = "N3DS_AR6014_NWM_READY_LAYOUT"

READY_OLD = '''static int
wmi_ready_event_rx(struct wmi_t *wmip, u8 *datap, int len)
{
    WMI_READY_EVENT_2 *ev = (WMI_READY_EVENT_2 *)datap;

    if (len >= sizeof(WMI_READY_EVENT_2)) {'''

READY_NEW = '''static int
wmi_ready_event_rx(struct wmi_t *wmip, u8 *datap, int len)
{
    typedef PREPACK struct {
        u8 macaddr[ATH_MAC_LEN];
        u8 phyCapability;
        u8 reserved;
        u32 sw_version;
        u16 version_12;
        u16 version_14;
    } POSTPACK NWM_READY_EVENT;
    WMI_READY_EVENT_2 *ev = (WMI_READY_EVENT_2 *)datap;

    /* N3DS_AR6014_NWM_READY_LAYOUT: NWM 0x001353ec consumes a complete
     * 16-byte MAC-first payload.  Its two trailing u16 version fields are
     * not Linux's single u32 ABI field, so retain the existing AR6014-only
     * ABI-zero compatibility gate while preserving the proven software
     * version, MAC, and PHY fields. */
    if (len == sizeof(NWM_READY_EVENT)) {
        NWM_READY_EVENT *nwm = (NWM_READY_EVENT *)datap;

        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 WMI NWM READY len=%d mac=%pM phy=%u sw=0x%x versions=%u/%u\\n",
             len, nwm->macaddr, nwm->phyCapability, nwm->sw_version,
             nwm->version_12, nwm->version_14));
        wmip->wmi_ready = true;
        A_WMI_READY_EVENT(wmip->wmi_devt, nwm->macaddr,
                          nwm->phyCapability, nwm->sw_version, 0);
        return 0;
    }

    if (len >= sizeof(WMI_READY_EVENT_2)) {'''


def patch_wmi(text: str) -> str:
    if MARKER in text:
        return text
    count = text.count(READY_OLD)
    if count != 1:
        raise RuntimeError(f"READY layout: expected one source anchor, found {count}")
    return text.replace(READY_OLD, READY_NEW, 1)


def main() -> None:
    if not WMI.is_file():
        raise SystemExit(f"missing canonical source: {WMI}")
    WMI.write_text(patch_wmi(WMI.read_text(encoding="utf-8")), encoding="utf-8")
    print("patch_ar6014_nwm_ready_layout: exact 16-byte READY layout installed")


if __name__ == "__main__":
    main()
