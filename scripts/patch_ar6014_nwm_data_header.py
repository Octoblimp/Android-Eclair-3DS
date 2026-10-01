#!/usr/bin/env python3
"""Install Nintendo NWM's two-byte data header for the CTR build only.

The canonical ath6kl source lives in WSL. This patcher is deliberately
anchor-driven and fail-closed: a partial patch is an error, while a complete
patch is a no-op on subsequent runs.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
DRIVER = ROOT / "third_party/linux/drivers/staging/ath6k_legacy"
WMI_H = DRIVER / "include/common/wmi.h"
WMI_C = DRIVER / "wmi/wmi.c"
CONFIG_H = DRIVER / "os/linux/include/config_linux.h"
DRIVER_C = DRIVER / "os/linux/ar6000_drv.c"

LAYOUT_MARKER = "N3DS_AR6014_NWM_DATA_HEADER"
INFO_MARKER = "N3DS_AR6014_NWM_DATA_INFO_LAYOUT"
META_MARKER = "N3DS_AR6014_NWM_DATA_METADATA_DISABLED"
SYNC_MARKER = "N3DS_AR6014_NWM_SYNC_HEADER_ZERO"
CONFIG_MARKER = "N3DS_AR6014_NWM_DATA_HEADER_CONFIG"
TX_MARKER = "N3DS_AR6014_NWM_CHECKSUM_FALLBACK"
RX_MARKER = "N3DS_AR6014_NWM_RX_8023_BOUNDS"
PARAM_MARKER = "N3DS_AR6014_NWM_CSUM_PARAM_DISABLED"
REORDER_MARKER = "N3DS_AR6014_NWM_RX_REORDER_BYPASS"
PREFIX_MARKER = "N3DS_AR6014_NWM_RX_PREFIX_BOUNDS"
RX_META_MARKER = "N3DS_AR6014_NWM_RX_METADATA_DISABLED"
LEGACY_SYNC_MARKER = "N3DS_AR6014_NWM_DATA_HDR_SYNC_ZERO"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one source anchor, found {count}")
    return text.replace(old, new, 1)


def require_complete(text: str, markers: tuple[str, ...], path: Path) -> bool:
    present = [marker for marker in markers if marker in text]
    if present and len(present) != len(markers):
        raise RuntimeError(f"{path}: partial NWM data-header patch: {present}")
    return bool(present)


OLD_INFO_FIELDS = """/* Macros for operating on WMI_DATA_HDR (info2) field */
#define WMI_DATA_HDR_SEQNO_MASK     0xFFF
#define WMI_DATA_HDR_SEQNO_SHIFT    0

#define WMI_DATA_HDR_AMSDU_MASK     0x1
#define WMI_DATA_HDR_AMSDU_SHIFT    12

#define WMI_DATA_HDR_META_MASK      0x7
#define WMI_DATA_HDR_META_SHIFT     13

#define GET_SEQ_NO(_v)                  ((_v) & WMI_DATA_HDR_SEQNO_MASK)
#define GET_ISMSDU(_v)                  ((_v) & WMI_DATA_HDR_AMSDU_MASK)

#define WMI_DATA_HDR_GET_SEQNO(h)        GET_SEQ_NO((h)->info2 >> WMI_DATA_HDR_SEQNO_SHIFT)
#define WMI_DATA_HDR_SET_SEQNO(h, _v)   ((h)->info2 = ((h)->info2 & ~(WMI_DATA_HDR_SEQNO_MASK << WMI_DATA_HDR_SEQNO_SHIFT)) | (GET_SEQ_NO(_v) << WMI_DATA_HDR_SEQNO_SHIFT))

#define WMI_DATA_HDR_IS_AMSDU(h)        GET_ISMSDU((h)->info2 >> WMI_DATA_HDR_AMSDU_SHIFT)
#define WMI_DATA_HDR_SET_AMSDU(h, _v)   ((h)->info2 = ((h)->info2 & ~(WMI_DATA_HDR_AMSDU_MASK << WMI_DATA_HDR_AMSDU_SHIFT)) | (GET_ISMSDU(_v) << WMI_DATA_HDR_AMSDU_SHIFT))

#define WMI_DATA_HDR_GET_META(h)        (((h)->info2 >> WMI_DATA_HDR_META_SHIFT) & WMI_DATA_HDR_META_MASK)
#define WMI_DATA_HDR_SET_META(h, _v)    ((h)->info2 = ((h)->info2 & ~(WMI_DATA_HDR_META_MASK << WMI_DATA_HDR_META_SHIFT)) | ((_v) << WMI_DATA_HDR_META_SHIFT))

/* Macros for operating on WMI_DATA_HDR (info3) field */
#define WMI_DATA_HDR_DEVID_MASK      0xF
#define WMI_DATA_HDR_DEVID_SHIFT     0
#define GET_DEVID(_v)                ((_v) & WMI_DATA_HDR_DEVID_MASK)

#define WMI_DATA_HDR_GET_DEVID(h) \\
	(((h)->info3 >> WMI_DATA_HDR_DEVID_SHIFT) & WMI_DATA_HDR_DEVID_MASK)
#define WMI_DATA_HDR_SET_DEVID(h, _v) \\
	((h)->info3 = ((h)->info3 & ~(WMI_DATA_HDR_DEVID_MASK << WMI_DATA_HDR_DEVID_SHIFT)) | (GET_DEVID(_v) << WMI_DATA_HDR_DEVID_SHIFT))
"""

NEW_INFO_FIELDS = """#ifdef CONFIG_ARCH_CTR
/* N3DS_AR6014_NWM_DATA_INFO_LAYOUT: NWM's data-body prefix has only RSSI and
 * info. The legacy info2/info3 words are local/AP MAC bytes on RX. */
#define WMI_DATA_HDR_GET_SEQNO(h)     (0)
#define WMI_DATA_HDR_SET_SEQNO(h, v)  ((void)0)
#define WMI_DATA_HDR_IS_AMSDU(h)      (0)
#define WMI_DATA_HDR_SET_AMSDU(h, v)  ((void)0)
#define WMI_DATA_HDR_GET_META(h)      (0)
#define WMI_DATA_HDR_SET_META(h, v)   ((void)0)
#define WMI_DATA_HDR_GET_DEVID(h)     (0)
#define WMI_DATA_HDR_SET_DEVID(h, v)  ((void)0)
#else
""" + OLD_INFO_FIELDS + """#endif /* CONFIG_ARCH_CTR */
"""

OLD_STRUCT = """typedef PREPACK struct {
    s8 rssi;
    u8 info;               /* usage of 'info' field(8-bit):
                                     *  b1:b0       - WMI_MSG_TYPE
                                     *  b4:b3:b2    - UP(tid)
                                     *  b5          - Used in AP mode. More-data in tx dir, PS in rx.
                                     *  b7:b6       -  Dot3 header(0),
                                     *                 Dot11 Header(1),
                                     *                 ACL data(2)
                                     */

    u16 info2;              /* usage of 'info2' field(16-bit):
                                     * b11:b0       - seq_no
                                     * b12          - A-MSDU?
                                     * b15:b13      - META_DATA_VERSION 0 - 7
                                     */
    u16 info3;
} POSTPACK WMI_DATA_HDR;"""

NEW_STRUCT = """#ifdef CONFIG_ARCH_CTR
/* N3DS_AR6014_NWM_DATA_HEADER: exactly the two-byte NWM data prefix. */
typedef PREPACK struct {
    s8 rssi;
    u8 info;
} POSTPACK WMI_DATA_HDR;
#else
""" + OLD_STRUCT + """
#endif /* CONFIG_ARCH_CTR */"""


def patch_wmi_h(text: str) -> str:
    if require_complete(text, (LAYOUT_MARKER, INFO_MARKER), WMI_H):
        return text
    text = replace_once(text, OLD_INFO_FIELDS, NEW_INFO_FIELDS,
                        "WMI info2/info3 helpers")
    return replace_once(text, OLD_STRUCT, NEW_STRUCT, "WMI data-header struct")


def patch_wmi(text: str) -> str:
    """Public fixture transform used by focused source tests."""
    return patch_wmi_h(text)


OLD_DATA_ADD_DECL = """    WMI_DATA_HDR     *dtHdr;
//    u8 metaVersion = 0;
    int status;

    A_ASSERT(osbuf != NULL);"""

NEW_DATA_ADD_DECL = """    WMI_DATA_HDR     *dtHdr;
//    u8 metaVersion = 0;
    int status;
#ifdef CONFIG_ARCH_CTR
    static bool n3ds_nwm_data_header_logged;
#endif

    A_ASSERT(osbuf != NULL);

#ifdef CONFIG_ARCH_CTR
    BUILD_BUG_ON(sizeof(WMI_DATA_HDR) != 2);
    /* N3DS_AR6014_NWM_DATA_METADATA_DISABLED: NWM has no TX metadata area. */
    if (!n3ds_nwm_data_header_logged) {
        n3ds_nwm_data_header_logged = true;
        AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
            ("AR6002 data: NWM two-byte header active; checksum metadata disabled\\n"));
    }
    metaVersion = 0;
#endif"""

OLD_SYNC_BODY = """    dtHdr = (WMI_DATA_HDR *)A_NETBUF_DATA(osbuf);
    dtHdr->info =
      (SYNC_MSGTYPE & WMI_DATA_HDR_MSG_TYPE_MASK) << WMI_DATA_HDR_MSG_TYPE_SHIFT;

    dtHdr->info3 = 0;"""

NEW_SYNC_BODY = """    dtHdr = (WMI_DATA_HDR *)A_NETBUF_DATA(osbuf);
    /* N3DS_AR6014_NWM_SYNC_HEADER_ZERO: no legacy words exist on CTR. */
    A_MEMZERO(dtHdr, sizeof(WMI_DATA_HDR));
    dtHdr->info =
      (SYNC_MSGTYPE & WMI_DATA_HDR_MSG_TYPE_MASK) << WMI_DATA_HDR_MSG_TYPE_SHIFT;

#ifndef CONFIG_ARCH_CTR
    dtHdr->info3 = 0;
#endif"""


def patch_wmi_c(text: str) -> str:
    if LEGACY_SYNC_MARKER in text and SYNC_MARKER not in text:
        text = text.replace(LEGACY_SYNC_MARKER, SYNC_MARKER, 1)
    if require_complete(text, (META_MARKER, SYNC_MARKER), WMI_C):
        return text
    text = replace_once(text, OLD_DATA_ADD_DECL, NEW_DATA_ADD_DECL,
                        "WMI data-header TX metadata guard")
    text = replace_once(
        text,
        """    WMI_DATA_HDR_SET_META(dtHdr, metaVersion);

    dtHdr->info3 = 0;""",
        """    WMI_DATA_HDR_SET_META(dtHdr, metaVersion);

#ifndef CONFIG_ARCH_CTR
    dtHdr->info3 = 0;
#endif""",
        "WMI data-header info3 guard",
    )
    return replace_once(text, OLD_SYNC_BODY, NEW_SYNC_BODY,
                        "WMI sync data-header zeroing")


OLD_CONFIG = """#ifndef __LP64__
#define CONFIG_CHECKSUM_OFFLOAD
#endif /* __LP64__ */"""

NEW_CONFIG = """#ifndef __LP64__
#define CONFIG_CHECKSUM_OFFLOAD
#endif /* __LP64__ */

#ifdef CONFIG_ARCH_CTR
/* N3DS_AR6014_NWM_DATA_HEADER_CONFIG: CTR NWM has no checksum metadata ABI. */
#undef CONFIG_CHECKSUM_OFFLOAD
#endif"""


def patch_config(text: str) -> str:
    if require_complete(text, (CONFIG_MARKER,), CONFIG_H):
        return text
    return replace_once(text, OLD_CONFIG, NEW_CONFIG, "CTR checksum feature guard")


OLD_MODULE_INIT = """static int __init
ar6000_init_module(void)
{
    static int probed = 0;
    int r;"""

NEW_MODULE_INIT = """static int __init
ar6000_init_module(void)
{
    static int probed = 0;
    int r;
#ifdef CONFIG_ARCH_CTR
    /* N3DS_AR6014_NWM_DATA_HEADER_CONFIG: reject runtime enablement too. */
    csumOffload = 0;
#endif"""

OLD_RX_META = """    if(csumOffload){
        /*if external frame work is also needed, change and use an extended rxMetaVerion*/
        ar->rxMetaVersion=WMI_META_VERSION_2;
    }"""

NEW_RX_META = """#ifdef CONFIG_ARCH_CTR
    /* N3DS_AR6014_NWM_RX_METADATA_DISABLED: NWM has no RX metadata area. */
    ar->rxMetaVersion = 0;
#else
""" + OLD_RX_META + """
#endif"""

OLD_CSUM_PARAM = """module_param(processDot11Hdr, uint, 0644);
module_param(csumOffload, uint, 0644);"""

NEW_CSUM_PARAM = """module_param(processDot11Hdr, uint, 0644);
#ifndef CONFIG_ARCH_CTR
module_param(csumOffload, uint, 0644);
#else
/* N3DS_AR6014_NWM_CSUM_PARAM_DISABLED: no runtime metadata enablement. */
#endif"""

OLD_TX_DECL = """        u8 csumStart=0;
        u8 csumDest=0;
        u8 csum=skb->ip_summed;
        if(csumOffload && (csum==CHECKSUM_PARTIAL)){"""

NEW_TX_DECL = """        u8 csumStart=0;
        u8 csumDest=0;
        u8 csum=skb->ip_summed;
#ifdef CONFIG_ARCH_CTR
        /* N3DS_AR6014_NWM_CHECKSUM_FALLBACK: complete partial
         * checksums in software before NWM framing; metadata is unavailable. */
        if (csum == CHECKSUM_PARTIAL) {
            if (skb_checksum_help(skb) != 0) {
                AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
                    ("AR6002 data: checksum completion failed\\n"));
                AR6000_STAT_INC(ar, tx_dropped);
                A_NETBUF_FREE(skb);
                return 0;
            }
            skb->ip_summed = CHECKSUM_NONE;
            csum = skb->ip_summed;
        }
#endif
        if(csumOffload && (csum==CHECKSUM_PARTIAL)){"""

OLD_RX_ANCHOR = """                if (processDot11Hdr) {
                    minHdrLen = sizeof(WMI_DATA_HDR) + sizeof(struct ieee80211_frame) + sizeof(ATH_LLC_SNAP_HDR);
                } else {
                    minHdrLen = sizeof (WMI_DATA_HDR) + sizeof(ATH_MAC_HDR) +
                          sizeof(ATH_LLC_SNAP_HDR);
                }

                /* In the case of AP mode we may receive NULL data frames"""

NEW_RX_ANCHOR = """                if (processDot11Hdr) {
                    minHdrLen = sizeof(WMI_DATA_HDR) + sizeof(struct ieee80211_frame) + sizeof(ATH_LLC_SNAP_HDR);
                } else {
                    minHdrLen = sizeof (WMI_DATA_HDR) + sizeof(ATH_MAC_HDR) +
                          sizeof(ATH_LLC_SNAP_HDR);
                }

#ifdef CONFIG_ARCH_CTR
                {
                    const u8 *n3ds_frame = (const u8 *)A_NETBUF_DATA(skb);
                    u32 n3ds_available = 0;
                    u32 n3ds_length = A_NETBUF_LEN(skb);
                    u16 n3ds_declared = 0;
                    bool n3ds_valid = true;
                    WMI_DATA_HDR_DATA_TYPE n3ds_expected_type =
                        processDot11Hdr ? WMI_DATA_HDR_DATA_TYPE_802_11 :
                        WMI_DATA_HDR_DATA_TYPE_802_3;
                    bool n3ds_ap_short =
                        (ar->arNetworkType == AP_NETWORK &&
                         n3ds_expected_type == WMI_DATA_HDR_DATA_TYPE_802_3 &&
                         WMI_DATA_HDR_GET_DATA_TYPE(dhdr) ==
                         WMI_DATA_HDR_DATA_TYPE_802_3 &&
                         n3ds_length ==
                         sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR));
                    /* N3DS_AR6014_NWM_RX_8023_BOUNDS: fail closed on a type
                     * mismatch; only full CTR 802.3 frames get unaligned-safe
                     * length/LLC validation. */
                    if (WMI_DATA_HDR_GET_DATA_TYPE(dhdr) !=
                        n3ds_expected_type) {
                        n3ds_valid = false;
                    } else if (n3ds_ap_short) {
                        /* Preserve the exact AP NULL-data exception; the
                         * existing AP path consumes its power-save state and
                         * then drops it before Ethernet conversion. */
                    } else if (n3ds_length < minHdrLen ||
                               n3ds_length > AR6000_MAX_RX_MESSAGE_SIZE) {
                        n3ds_valid = false;
                    } else if (!processDot11Hdr) {
                        n3ds_declared =
                            ((u16)n3ds_frame[sizeof(WMI_DATA_HDR) + 12] << 8) |
                            n3ds_frame[sizeof(WMI_DATA_HDR) + 13];
                        n3ds_available = n3ds_length -
                            sizeof(WMI_DATA_HDR) - sizeof(ATH_MAC_HDR);
                        if (n3ds_declared < sizeof(ATH_LLC_SNAP_HDR) ||
                            n3ds_declared > n3ds_available ||
                            n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR)] != 0xaa ||
                            n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR) + 1] != 0xaa ||
                            n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR) + 2] != 0x03) {
                            n3ds_valid = false;
                        }
                    }
                    if (!n3ds_valid) {
                        AR_DEBUG_PRINTF(ATH_DEBUG_INFO,
                            ("AR6002 data: malformed NWM 802.3 frame len=%u declared=%u\\n",
                             n3ds_length, n3ds_declared));
                        AR6000_STAT_INC(ar, rx_errors);
                        AR6000_STAT_INC(ar, rx_length_errors);
                        atomic_inc(&n3ds_rx_drop_short);
                        A_NETBUF_FREE(skb);
                        goto rx_done;
                    }
                }
#endif

                /* In the case of AP mode we may receive NULL data frames"""

OLD_RX_PREFIX_ANCHOR = """        } else {
                WMI_DATA_HDR *dhdr = (WMI_DATA_HDR *)A_NETBUF_DATA(skb);
                bool is_amsdu;
                u8 tid;

		/*"""

NEW_RX_PREFIX_ANCHOR = """        } else {
                WMI_DATA_HDR *dhdr = (WMI_DATA_HDR *)A_NETBUF_DATA(skb);
                bool is_amsdu;
                u8 tid;

#ifdef CONFIG_ARCH_CTR
                /* N3DS_AR6014_NWM_RX_PREFIX_BOUNDS: the info-byte access
                 * below is valid only after the complete two-byte NWM prefix
                 * has arrived. Fail before any target-controlled dereference. */
                if (A_NETBUF_LEN(skb) < sizeof(WMI_DATA_HDR)) {
                    AR6000_STAT_INC(ar, rx_errors);
                    AR6000_STAT_INC(ar, rx_length_errors);
                    atomic_inc(&n3ds_rx_drop_short);
                    A_NETBUF_FREE(skb);
                    goto rx_done;
                }
#endif

		/*"""

OLD_RX_CURRENT = """#ifdef CONFIG_ARCH_CTR
                if (WMI_DATA_HDR_GET_DATA_TYPE(dhdr) ==
                    WMI_DATA_HDR_DATA_TYPE_802_3) {
                    const u8 *n3ds_frame = (const u8 *)A_NETBUF_DATA(skb);
                    u32 n3ds_available = 0;
                    u16 n3ds_declared = 0;
                    bool n3ds_valid = true;
                    /* N3DS_AR6014_NWM_RX_8023_BOUNDS: the CTR 802.3
                     * length field is unaligned and follows the 12-byte MAC
                     * address pair after the two-byte NWM prefix. */
                    if (pPacket->ActualLength < minHdrLen ||
                        pPacket->ActualLength > AR6000_MAX_RX_MESSAGE_SIZE) {
                        n3ds_valid = false;
                    } else {
                        n3ds_declared =
                            ((u16)n3ds_frame[sizeof(WMI_DATA_HDR) + 12] << 8) |
                            n3ds_frame[sizeof(WMI_DATA_HDR) + 13];
                        n3ds_available = pPacket->ActualLength -
                            sizeof(WMI_DATA_HDR) - sizeof(ATH_MAC_HDR);
                        if (n3ds_declared < sizeof(ATH_LLC_SNAP_HDR) ||
                            n3ds_declared > n3ds_available ||
                            n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR)] != 0xaa ||
                            n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR) + 1] != 0xaa ||
                            n3ds_frame[sizeof(WMI_DATA_HDR) + sizeof(ATH_MAC_HDR) + 2] != 0x03) {
                            n3ds_valid = false;
                        }
                    }
                    if (!n3ds_valid) {
                        AR_DEBUG_PRINTF(ATH_DEBUG_INFO,
                            ("AR6002 data: malformed NWM 802.3 frame len=%u declared=%u\\n",
                             pPacket->ActualLength, n3ds_declared));
                        AR6000_STAT_INC(ar, rx_errors);
                        AR6000_STAT_INC(ar, rx_length_errors);
                        atomic_inc(&n3ds_rx_drop_short);
                        A_NETBUF_FREE(skb);
                        goto rx_done;
                    }
                }
#endif"""


def migrate_rx_validator(text: str) -> str:
    if RX_MARKER not in text:
        return text
    if "u32 n3ds_length = A_NETBUF_LEN(skb);" in text:
        return text
    start = NEW_RX_ANCHOR.index("#ifdef CONFIG_ARCH_CTR")
    end = NEW_RX_ANCHOR.index("\n#endif\n\n                /* In the case")
    new_body = NEW_RX_ANCHOR[start:end + len("\n#endif")]
    return replace_once(text, OLD_RX_CURRENT, new_body,
                        "migrate CTR 802.3 RX validator")


def patch_driver(text: str) -> str:
    base_markers = (CONFIG_MARKER, PARAM_MARKER, TX_MARKER, RX_MARKER,
                    REORDER_MARKER)
    present = [marker for marker in base_markers if marker in text]
    if present:
        if len(present) != len(base_markers):
            raise RuntimeError(
                f"{DRIVER_C}: partial NWM data-header patch: {present}"
            )
        text = migrate_rx_validator(text)
        old_checksum = NEW_TX_DECL.replace(
            "            skb->ip_summed = CHECKSUM_NONE;\n", ""
        )
        if old_checksum in text:
            text = replace_once(text, old_checksum, NEW_TX_DECL,
                                "CTR checksum completion normalization")
        if PREFIX_MARKER not in text:
            text = replace_once(text, OLD_RX_PREFIX_ANCHOR,
                                NEW_RX_PREFIX_ANCHOR,
                                "CTR RX prefix bounds")
        if RX_META_MARKER not in text:
            text = replace_once(text, OLD_RX_META, NEW_RX_META,
                                "CTR RX metadata guard")
        return text
    text = replace_once(text, OLD_CSUM_PARAM, NEW_CSUM_PARAM,
                        "CTR csumOffload module parameter guard")
    text = replace_once(text, OLD_MODULE_INIT, NEW_MODULE_INIT,
                        "CTR csumOffload module guard")
    text = replace_once(text, OLD_RX_META, NEW_RX_META,
                        "CTR RX metadata guard")
    text = replace_once(text, OLD_TX_DECL, NEW_TX_DECL,
                        "CTR software checksum fallback")
    text = replace_once(text, OLD_RX_ANCHOR, NEW_RX_ANCHOR,
                        "CTR 802.3 RX validator")
    text = replace_once(text, OLD_RX_PREFIX_ANCHOR, NEW_RX_PREFIX_ANCHOR,
                        "CTR RX prefix bounds")
    old_reorder = """                    aggr_process_recv_frm(ar->aggr_cntxt, tid, seq_no, is_amsdu, (void **)&skb);
                    /* N3DS_AR6014_RX_DROP_CENSUS: the reorder buffer keeps the
                     * frame and NULLs the pointer, which every counter we had
                     * scored exactly like a successful delivery. */
                    if (skb == NULL) {
                        atomic_inc(&n3ds_rx_drop_aggr);
                    }
                    ar6000_deliver_frames_to_nw_stack((void *) ar->arNetDev, (void *)skb);"""
    new_reorder = """#ifdef CONFIG_ARCH_CTR
                    /* N3DS_AR6014_NWM_RX_REORDER_BYPASS: NWM's two-byte
                     * prefix carries no sequence/AMSDU fields. Do not feed
                     * validated 802.3 frames into legacy reorder state. */
                    ar6000_deliver_frames_to_nw_stack((void *) ar->arNetDev, (void *)skb);
#else
                    aggr_process_recv_frm(ar->aggr_cntxt, tid, seq_no, is_amsdu, (void **)&skb);
                    /* N3DS_AR6014_RX_DROP_CENSUS: the reorder buffer keeps the
                     * frame and NULLs the pointer, which every counter we had
                     * scored exactly like a successful delivery. */
                    if (skb == NULL) {
                        atomic_inc(&n3ds_rx_drop_aggr);
                    }
                    ar6000_deliver_frames_to_nw_stack((void *) ar->arNetDev, (void *)skb);
#endif"""
    return replace_once(text, old_reorder, new_reorder,
                        "CTR RX reorder bypass")


def patch_file(path: Path, transform, markers: tuple[str, ...]) -> bool:
    if not path.is_file():
        raise SystemExit(f"missing canonical source: {path}")
    original = path.read_text(encoding="utf-8")
    updated = transform(original)
    if updated == original:
        if not require_complete(original, markers, path):
            raise RuntimeError(f"{path}: transform made no change and is not complete")
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def main() -> None:
    changed = []
    if patch_file(WMI_H, patch_wmi_h, (LAYOUT_MARKER, INFO_MARKER)):
        changed.append(str(WMI_H))
    if patch_file(WMI_C, patch_wmi_c, (META_MARKER, SYNC_MARKER)):
        changed.append(str(WMI_C))
    if patch_file(CONFIG_H, patch_config, (CONFIG_MARKER,)):
        changed.append(str(CONFIG_H))
    if patch_file(DRIVER_C, patch_driver,
                  (CONFIG_MARKER, PARAM_MARKER, TX_MARKER, RX_MARKER,
                   REORDER_MARKER, PREFIX_MARKER, RX_META_MARKER)):
        changed.append(str(DRIVER_C))
    print("patch_ar6014_nwm_data_header: " +
          ("patched " + ", ".join(changed) if changed else "already complete"))


if __name__ == "__main__":
    main()
