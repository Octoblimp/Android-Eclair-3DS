#!/usr/bin/env python3
"""Localise the ath6kl receive-path drop that swallows every data frame.

Build #257 established, for the first time without ambiguity, that data-endpoint
packets reach ar6000_rx() and that none of them reach netif_rx():

    AR6002 census disconnect raw=161 ctrl=157 data=4 rawerr=0 frames=0 ...

frames=0 cannot say *where* they die.  n3ds_rx_census() is called inside the
IFF_UP branch of ar6000_deliver_frames_to_nw_stack(), so a frame freed for being
too short, one held by the reorder buffer, and one dropped because the interface
was down all produce the identical line.

Worse, the census cannot say whether those four packets are EAPOL at all.  Four
dropped EAPOL msg-1/4 retries and four discarded null-data frames are the same
census line, and they point at opposite root causes: the first is a driver bug,
the second means the AP never sent a handshake.  Every remaining theory hinges
on telling them apart, so this patch dumps the first bytes of the first few data
packets alongside a per-site drop counter.

The ACL site is deliberately left alone: it carries a WARN_ON, so it announces
itself in the log without help.
"""

import sys
from pathlib import Path

MARKER = "N3DS_AR6014_RX_DROP_CENSUS"

DRIVER = ("third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c")

COUNTERS_OLD = """static atomic_t n3ds_rx_raw_ctrl = ATOMIC_INIT(0);
static atomic_t n3ds_rx_raw_data = ATOMIC_INIT(0);
"""

COUNTERS_NEW = """static atomic_t n3ds_rx_raw_ctrl = ATOMIC_INIT(0);
static atomic_t n3ds_rx_raw_data = ATOMIC_INIT(0);

/* N3DS_AR6014_RX_DROP_CENSUS: data>0 frames=0 proves the driver drops what the
 * target delivers, but n3ds_rx_census() runs inside the IFF_UP branch of
 * ar6000_deliver_frames_to_nw_stack(), so every drop site collapses onto the
 * same counter.  Give each one its own, and dump the head of the first few
 * data packets -- four dropped EAPOL retries and four discarded null-data
 * frames are otherwise the same census line with opposite meanings. */
static atomic_t n3ds_rx_drop_short = ATOMIC_INIT(0);
static atomic_t n3ds_rx_drop_dix = ATOMIC_INIT(0);
static atomic_t n3ds_rx_drop_aggr = ATOMIC_INIT(0);
static atomic_t n3ds_rx_drop_down = ATOMIC_INIT(0);
static atomic_t n3ds_rx_deliver = ATOMIC_INIT(0);

/* Budget is global and is never reset: data packets only arrive while
 * associated, so 16 covers the first few associations of a sweep and cannot
 * grow into a firehose across 36 of them. */
static atomic_t n3ds_rx_dump_left = ATOMIC_INIT(16);
"""

DUMP_OLD = """    if (status != 0) {
        atomic_inc(&n3ds_rx_raw_err);
    }
}
"""

DUMP_NEW = """    if (status != 0) {
        atomic_inc(&n3ds_rx_raw_err);
    }
}

/* N3DS_AR6014_RX_DROP_CENSUS: 32 bytes reaches past the WMI data header, the
 * 802.3 addresses and the LLC/SNAP header to the EtherType, so an EAPOL frame
 * is identifiable by 88 8e appearing in the tail of the line even when a meta
 * header has shifted the offsets. */
static void
n3ds_rx_dump(const char *where, const u8 *d, int len)
{
    int n = len;

    if (d == NULL || len <= 0) {
        return;
    }
    if (atomic_read(&n3ds_rx_dump_left) <= 0) {
        return;
    }
    atomic_dec(&n3ds_rx_dump_left);
    if (n > 32) {
        n = 32;
    }
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 rxpkt %s len=%d %*ph\\n", where, len, n, d));
}
"""

REPORT_OLD = """        ("AR6002 census %s raw=%d ctrl=%d data=%d rawerr=%d frames=%d "
         "bcast=%d eapol_rx=%d eapol_tx=%d\\n",
         why, atomic_read(&n3ds_rx_raw),
         atomic_read(&n3ds_rx_raw_ctrl),      /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
         atomic_read(&n3ds_rx_raw_data),      /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
         atomic_read(&n3ds_rx_raw_err),
         atomic_read(&n3ds_rx_frames), atomic_read(&n3ds_rx_bcast),
         atomic_read(&n3ds_eapol_rx_count), atomic_read(&n3ds_eapol_tx_count)));
"""

REPORT_NEW = """        ("AR6002 census %s raw=%d ctrl=%d data=%d rawerr=%d frames=%d "
         "bcast=%d eapol_rx=%d eapol_tx=%d "
         "short=%d dix=%d aggr=%d down=%d deliv=%d\\n",
         why, atomic_read(&n3ds_rx_raw),
         atomic_read(&n3ds_rx_raw_ctrl),      /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
         atomic_read(&n3ds_rx_raw_data),      /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
         atomic_read(&n3ds_rx_raw_err),
         atomic_read(&n3ds_rx_frames), atomic_read(&n3ds_rx_bcast),
         atomic_read(&n3ds_eapol_rx_count), atomic_read(&n3ds_eapol_tx_count),
         atomic_read(&n3ds_rx_drop_short),    /* N3DS_AR6014_RX_DROP_CENSUS */
         atomic_read(&n3ds_rx_drop_dix),      /* N3DS_AR6014_RX_DROP_CENSUS */
         atomic_read(&n3ds_rx_drop_aggr),     /* N3DS_AR6014_RX_DROP_CENSUS */
         atomic_read(&n3ds_rx_drop_down),     /* N3DS_AR6014_RX_DROP_CENSUS */
         atomic_read(&n3ds_rx_deliver)));     /* N3DS_AR6014_RX_DROP_CENSUS */
"""

RESET_OLD = """    atomic_set(&n3ds_rx_raw_ctrl, 0);     /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
    atomic_set(&n3ds_rx_raw_data, 0);     /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
}
"""

RESET_NEW = """    atomic_set(&n3ds_rx_raw_ctrl, 0);     /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
    atomic_set(&n3ds_rx_raw_data, 0);     /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
    atomic_set(&n3ds_rx_drop_short, 0);   /* N3DS_AR6014_RX_DROP_CENSUS */
    atomic_set(&n3ds_rx_drop_dix, 0);     /* N3DS_AR6014_RX_DROP_CENSUS */
    atomic_set(&n3ds_rx_drop_aggr, 0);    /* N3DS_AR6014_RX_DROP_CENSUS */
    atomic_set(&n3ds_rx_drop_down, 0);    /* N3DS_AR6014_RX_DROP_CENSUS */
    atomic_set(&n3ds_rx_deliver, 0);      /* N3DS_AR6014_RX_DROP_CENSUS */
}
"""

DUMPCALL_OLD = """                /*
                 * this is a wmi data packet
                 */
                 // NWF

                if (processDot11Hdr) {
"""

DUMPCALL_NEW = """                /*
                 * this is a wmi data packet
                 */
                 // NWF

                /* N3DS_AR6014_RX_DROP_CENSUS: dump before the length check, so
                 * a frame rejected as too short is still identifiable. */
                n3ds_rx_dump("data", (const u8 *)A_NETBUF_DATA(skb),
                             pPacket->ActualLength);

                if (processDot11Hdr) {
"""

SHORT_OLD = """                    AR_DEBUG_PRINTF(ATH_DEBUG_INFO,("TOO SHORT or TOO LONG\\n"));
                    AR6000_STAT_INC(ar, rx_errors);
                    AR6000_STAT_INC(ar, rx_length_errors);
                    A_NETBUF_FREE(skb);
"""

SHORT_NEW = """                    AR_DEBUG_PRINTF(ATH_DEBUG_INFO,("TOO SHORT or TOO LONG\\n"));
                    AR6000_STAT_INC(ar, rx_errors);
                    AR6000_STAT_INC(ar, rx_length_errors);
                    atomic_inc(&n3ds_rx_drop_short); /* N3DS_AR6014_RX_DROP_CENSUS */
                    A_NETBUF_FREE(skb);
"""

DIX_OLD = """                    if (status) {
                        /* Drop frames that could not be processed (lack of memory, etc.) */
                        A_NETBUF_FREE(skb);
                        goto rx_done;
                    }
"""

DIX_NEW = """                    if (status) {
                        /* Drop frames that could not be processed (lack of memory, etc.) */
                        atomic_inc(&n3ds_rx_drop_dix); /* N3DS_AR6014_RX_DROP_CENSUS */
                        A_NETBUF_FREE(skb);
                        goto rx_done;
                    }
"""

AGGR_OLD = """                    aggr_process_recv_frm(ar->aggr_cntxt, tid, seq_no, is_amsdu, (void **)&skb);
                    ar6000_deliver_frames_to_nw_stack((void *) ar->arNetDev, (void *)skb);
"""

AGGR_NEW = """                    aggr_process_recv_frm(ar->aggr_cntxt, tid, seq_no, is_amsdu, (void **)&skb);
                    /* N3DS_AR6014_RX_DROP_CENSUS: the reorder buffer keeps the
                     * frame and NULLs the pointer, which every counter we had
                     * scored exactly like a successful delivery. */
                    if (skb == NULL) {
                        atomic_inc(&n3ds_rx_drop_aggr);
                    }
                    ar6000_deliver_frames_to_nw_stack((void *) ar->arNetDev, (void *)skb);
"""

DELIVER_OLD = """            n3ds_eapol_trace(skb, "rx", &n3ds_eapol_rx_count, 1);
            n3ds_rx_census(skb);    /* N3DS_AR6014_RX_CENSUS */
"""

DELIVER_NEW = """            atomic_inc(&n3ds_rx_deliver);   /* N3DS_AR6014_RX_DROP_CENSUS */
            n3ds_eapol_trace(skb, "rx", &n3ds_eapol_rx_count, 1);
            n3ds_rx_census(skb);    /* N3DS_AR6014_RX_CENSUS */
"""

DOWN_OLD = """        } else {
            A_NETBUF_FREE(skb);
        }
    }
}

#if 0
static void
ar6000_deliver_frames_to_bt_stack(void *dev, void *osbuf)
"""

DOWN_NEW = """        } else {
            atomic_inc(&n3ds_rx_drop_down);  /* N3DS_AR6014_RX_DROP_CENSUS */
            A_NETBUF_FREE(skb);
        }
    }
}

#if 0
static void
ar6000_deliver_frames_to_bt_stack(void *dev, void *osbuf)
"""

HUNKS = (
    ("counters", COUNTERS_OLD, COUNTERS_NEW),
    ("dump helper", DUMP_OLD, DUMP_NEW),
    ("census report", REPORT_OLD, REPORT_NEW),
    ("census reset", RESET_OLD, RESET_NEW),
    ("dump call", DUMPCALL_OLD, DUMPCALL_NEW),
    ("too-short drop", SHORT_OLD, SHORT_NEW),
    ("dot3-to-dix drop", DIX_OLD, DIX_NEW),
    ("reorder-buffer hold", AGGR_OLD, AGGR_NEW),
    ("delivery counter", DELIVER_OLD, DELIVER_NEW),
    ("interface-down drop", DOWN_OLD, DOWN_NEW),
)


def patch(root: Path) -> int:
    path = root / DRIVER
    if not path.is_file():
        print("SKIP  %s (not present in this workspace)" % DRIVER)
        return 0

    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    if MARKER in text:
        print("OK    %s already carries %s" % (path.name, MARKER))
        return 0

    for name, old, new in HUNKS:
        count = text.count(old)
        assert count == 1, "hunk %r matched %d times, expected 1" % (name, count)
        text = text.replace(old, new, 1)

    path.write_text(text, encoding="utf-8", errors="surrogateescape")
    print("PATCH %s (%d hunks, %s)" % (path.name, len(HUNKS), MARKER))
    return 0


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    return patch(root)


if __name__ == "__main__":
    raise SystemExit(main())
