"""Count what actually crosses the link while associated, and report it once.

Build #254 confirmed zero EAPOL frames in either direction across ten
associations, which says the 4-way handshake never starts but not why.  Two
very different faults produce that same log:

*   the receive path is dead -- nothing at all reaches the network stack, so
    the association is nominal and the target never really joined the BSS;
*   the receive path works -- beacons, ARP and broadcast traffic arrive -- but
    the AP never sends message 1/4, which points at the association itself
    being rejected upstream of EAPOL.

One counter distinguishes them.  This adds a bounded census (total frames,
broadcast frames, EAPOL frames) reset on each association and printed as a
single line when the link goes down, next to the reason code.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_RX_CENSUS"

COUNTER_OLD = r"""static void
n3ds_eapol_trace_reset(void)
{
    atomic_set(&n3ds_eapol_tx_count, 0);
    atomic_set(&n3ds_eapol_rx_count, 0);
}
"""

COUNTER_NEW = r"""/* N3DS_AR6014_RX_CENSUS: zero EAPOL frames is ambiguous between "nothing is
 * being received at all" and "the AP is not sending message 1/4".  Counting
 * every frame delivered to the stack, and how many were broadcast, separates
 * the two without adding a per-frame print. */
static atomic_t n3ds_rx_frames = ATOMIC_INIT(0);
static atomic_t n3ds_rx_bcast = ATOMIC_INIT(0);

static void
n3ds_rx_census(struct sk_buff *skb)
{
    const u8 *eth;

    if (!skb || A_NETBUF_LEN(skb) < 14)
        return;

    atomic_inc(&n3ds_rx_frames);
    eth = (const u8 *)A_NETBUF_DATA(skb);
    if (eth[0] & 0x01)
        atomic_inc(&n3ds_rx_bcast);
}

/* N3DS_AR6014_RX_CENSUS: one bounded line per link-down. */
static void
n3ds_rx_census_report(const char *why)
{
    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 census %s frames=%d bcast=%d eapol_rx=%d eapol_tx=%d\n",
         why, atomic_read(&n3ds_rx_frames), atomic_read(&n3ds_rx_bcast),
         atomic_read(&n3ds_eapol_rx_count), atomic_read(&n3ds_eapol_tx_count)));
}

static void
n3ds_eapol_trace_reset(void)
{
    atomic_set(&n3ds_eapol_tx_count, 0);
    atomic_set(&n3ds_eapol_rx_count, 0);
    atomic_set(&n3ds_rx_frames, 0);
    atomic_set(&n3ds_rx_bcast, 0);
}
"""

COUNT_OLD = r"""            n3ds_eapol_trace(skb, "rx", &n3ds_eapol_rx_count, 1);
"""

COUNT_NEW = r"""            n3ds_eapol_trace(skb, "rx", &n3ds_eapol_rx_count, 1);
            n3ds_rx_census(skb);    /* N3DS_AR6014_RX_CENSUS */
"""

REPORT_OLD = r"""    ar6k_cfg80211_disconnect_event(ar, reason, bssid,
                                   assocRespLen, assocInfo,
                                   protocolReasonStatus);
"""

REPORT_NEW = r"""    n3ds_rx_census_report("disconnect");    /* N3DS_AR6014_RX_CENSUS */

    ar6k_cfg80211_disconnect_event(ar, reason, bssid,
                                   assocRespLen, assocInfo,
                                   protocolReasonStatus);
"""

HUNKS = (
    ("rx census counters", COUNTER_OLD, COUNTER_NEW),
    ("count received frames", COUNT_OLD, COUNT_NEW),
    ("report the census on disconnect", REPORT_OLD, REPORT_NEW),
)


def patch_drv(text):
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, "%s: expected exactly one anchor, found %d" % (
            name,
            text.count(old),
        )
        text = text.replace(old, new)
    return text


def main():
    text = TARGET.read_text()
    patched = patch_drv(text)
    if patched == text:
        print("patch_ar6014_rx_census: already applied")
        return
    TARGET.write_text(patched)
    print("patch_ar6014_rx_census: applied to %s" % TARGET)


if __name__ == "__main__":
    main()
