#!/usr/bin/env python3
"""Use Nintendo NWM's two-byte WMI command/event header."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


WMI = Path(
    f"{A3DS_ROOT}/third_party/linux/"
    "drivers/staging/ath6k_legacy/wmi/wmi.c"
)
MARKER = "N3DS_AR6014_NWM_WMI_U16_HEADER"
SHORT_MARKER = "N3DS_AR6014_NWM_SHORT_DISCONNECT_LAYOUT"
LEGACY_SHORT_MARKER = "N3DS_AR6014_SHORT_DISCONNECT"

WMI_RX_OLD = '''    WMI_CMD_HDR *cmd;
    u16 id;
    u8 *datap;
    u32 len, i, loggingReq;
    int status = 0;

    A_ASSERT(osbuf != NULL);
    if (A_NETBUF_LEN(osbuf) < sizeof(WMI_CMD_HDR)) {
        A_NETBUF_FREE(osbuf);
        A_DPRINTF(DBG_WMI, (DBGFMT "bad packet 1\\n", DBGARG));
        wmip->wmi_stats.cmd_len_err++;
        return A_ERROR;
    }

    cmd = (WMI_CMD_HDR *)A_NETBUF_DATA(osbuf);
    id = cmd->commandId;

    if (A_NETBUF_PULL(osbuf, sizeof(WMI_CMD_HDR)) != 0) {
        A_NETBUF_FREE(osbuf);
        A_DPRINTF(DBG_WMI, (DBGFMT "bad packet 2\\n", DBGARG));
        wmip->wmi_stats.cmd_len_err++;
        return A_ERROR;
    }
'''

WMI_RX_NEW = '''    u16 id;
    u8 *datap;
    u32 len, i, loggingReq;
    int status = 0;

    /* N3DS_AR6014_NWM_WMI_U16_HEADER: NWM 0x001353ec requires two
     * bytes, reads the event id as one u16, and pulls exactly two bytes
     * before dispatching the event payload.  The stock four-byte header
     * discarded the first two bytes of every Nintendo event. */
    A_ASSERT(osbuf != NULL);
    if (A_NETBUF_LEN(osbuf) < sizeof(u16)) {
        A_NETBUF_FREE(osbuf);
        A_DPRINTF(DBG_WMI, (DBGFMT "bad packet 1\\n", DBGARG));
        wmip->wmi_stats.cmd_len_err++;
        return A_ERROR;
    }

    id = *(u16 *)A_NETBUF_DATA(osbuf);

    if (A_NETBUF_PULL(osbuf, sizeof(u16)) != 0) {
        A_NETBUF_FREE(osbuf);
        A_DPRINTF(DBG_WMI, (DBGFMT "bad packet 2\\n", DBGARG));
        wmip->wmi_stats.cmd_len_err++;
        return A_ERROR;
    }
'''

WMI_TX_OLD = '''    int status;
#define IS_OPT_TX_CMD(cmdId) ((cmdId == WMI_OPT_TX_FRAME_CMDID))
    WMI_CMD_HDR         *cHdr;
    HTC_ENDPOINT_ID     eid  = wmip->wmi_endpoint_id;

    A_ASSERT(osbuf != NULL);

    if (syncflag >= END_WMIFLAG) {
        A_NETBUF_FREE(osbuf);
        return A_EINVAL;
    }

    if ((syncflag == SYNC_BEFORE_WMIFLAG) || (syncflag == SYNC_BOTH_WMIFLAG)) {
        /*
         * We want to make sure all data currently queued is transmitted before
         * the cmd execution.  Establish a new sync point.
         */
        wmi_sync_point(wmip);
    }

    if (A_NETBUF_PUSH(osbuf, sizeof(WMI_CMD_HDR)) != 0) {
        A_NETBUF_FREE(osbuf);
        return A_NO_MEMORY;
    }

    cHdr = (WMI_CMD_HDR *)A_NETBUF_DATA(osbuf);
    cHdr->commandId = (u16) cmdId;
    cHdr->info1 = 0; // added for virtual interface
'''

WMI_TX_NEW = '''    int status;
    static bool n3ds_nwm_wmi_header_logged;
#define IS_OPT_TX_CMD(cmdId) ((cmdId == WMI_OPT_TX_FRAME_CMDID))
    HTC_ENDPOINT_ID     eid  = wmip->wmi_endpoint_id;

    A_ASSERT(osbuf != NULL);

    if (syncflag >= END_WMIFLAG) {
        A_NETBUF_FREE(osbuf);
        return A_EINVAL;
    }

    if ((syncflag == SYNC_BEFORE_WMIFLAG) || (syncflag == SYNC_BOTH_WMIFLAG)) {
        /*
         * We want to make sure all data currently queued is transmitted before
         * the cmd execution.  Establish a new sync point.
         */
        wmi_sync_point(wmip);
    }

    /* N3DS_AR6014_NWM_WMI_U16_HEADER: NWM 0x00118140 pushes two bytes
     * and writes only the u16 command id.  Stock ath6kl's extra info1 u16
     * shifted every command payload, including APP-IE and WMI_CONNECT. */
    if (A_NETBUF_PUSH(osbuf, sizeof(u16)) != 0) {
        A_NETBUF_FREE(osbuf);
        return A_NO_MEMORY;
    }

    *(u16 *)A_NETBUF_DATA(osbuf) = (u16)cmdId;
    if (!n3ds_nwm_wmi_header_logged) {
        n3ds_nwm_wmi_header_logged = true;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 WMI: NWM u16 command/event header active\\n"));
    }
'''

WMI_SHORT_OLD = '''        /* N3DS_AR6014_SHORT_DISCONNECT: Nintendo reports failed connects as
         * seven bytes, with the reason at offset four. */
        u8 shortBssid[ATH_MAC_LEN];
        u8 reason = len > 4 ? datap[4] : NO_NETWORK_AVAIL;
        A_MEMZERO(shortBssid, sizeof(shortBssid));
        A_MEMZERO(wmip->wmi_bssid, sizeof(wmip->wmi_bssid));
        wmip->wmi_is_wmm_enabled = false;
        wmip->wmi_pair_crypto_type = NONE_CRYPT;
        wmip->wmi_grp_crypto_type = NONE_CRYPT;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: short disconnect len=%d reason=%u raw=%*ph\\n",
             len, reason, len, datap));
        A_WMI_DISCONNECT_EVENT(wmip->wmi_devt, reason, shortBssid,
                               0, NULL, 0);
        return 0;
'''

WMI_SHORT_NEW = '''        /* N3DS_AR6014_SHORT_DISCONNECT:
         * N3DS_AR6014_NWM_SHORT_DISCONNECT_LAYOUT: after removing NWM's
         * exact two-byte event header, the compact failure event is
         * BSSID[6], reason, and two reserved bytes.  The former offset four
         * accidentally compensated for discarding two payload bytes. */
        u8 shortBssid[ATH_MAC_LEN];
        u8 reason;
        if (len < ATH_MAC_LEN + 1)
            return A_EINVAL;
        memcpy(shortBssid, datap, ATH_MAC_LEN);
        reason = datap[ATH_MAC_LEN];
        A_MEMZERO(wmip->wmi_bssid, sizeof(wmip->wmi_bssid));
        wmip->wmi_is_wmm_enabled = false;
        wmip->wmi_pair_crypto_type = NONE_CRYPT;
        wmip->wmi_grp_crypto_type = NONE_CRYPT;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 connect: short disconnect len=%d reason=%u raw=%*ph\\n",
             len, reason, len, datap));
        A_WMI_DISCONNECT_EVENT(wmip->wmi_devt, reason, shortBssid,
                               0, NULL, 0);
        return 0;
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new, 1)


def patch_wmi(text: str) -> str:
    if SHORT_MARKER in text:
        if LEGACY_SHORT_MARKER not in text:
            text = text.replace(
                "        /* N3DS_AR6014_NWM_SHORT_DISCONNECT_LAYOUT:",
                "        /* N3DS_AR6014_SHORT_DISCONNECT:\n"
                "         * N3DS_AR6014_NWM_SHORT_DISCONNECT_LAYOUT:",
                1,
            )
        text = text.replace(
            "        A_MEMCPY(shortBssid, datap, ATH_MAC_LEN);\n",
            "        memcpy(shortBssid, datap, ATH_MAC_LEN);\n",
            1,
        )
    marker_count = text.count(MARKER)
    short_patched = SHORT_MARKER in text
    if marker_count == 2 and short_patched:
        return text
    if marker_count not in (0, 2):
        raise RuntimeError("WMI source contains a partial NWM header patch")
    if marker_count == 0:
        text = replace_once(text, WMI_RX_OLD, WMI_RX_NEW, "receive header")
        text = replace_once(text, WMI_TX_OLD, WMI_TX_NEW, "transmit header")
    if not short_patched:
        text = replace_once(
            text, WMI_SHORT_OLD, WMI_SHORT_NEW, "short disconnect layout"
        )
    return text


def main() -> None:
    if not WMI.is_file():
        raise SystemExit(f"missing canonical source: {WMI}")
    WMI.write_text(patch_wmi(WMI.read_text(encoding="utf-8")), encoding="utf-8")
    print("patch_ar6014_nwm_wmi_header: two-byte NWM WMI header installed")


if __name__ == "__main__":
    main()
