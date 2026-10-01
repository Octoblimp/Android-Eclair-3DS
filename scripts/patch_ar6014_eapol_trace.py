#!/usr/bin/env python3
"""Count EAPOL frames in both directions so the 10-second teardown is decidable.

Both associations in the 2026-09-01 capture were torn down about ten seconds
later with `reason=3` (DISCONNECT_CMD) -- host-initiated, i.e. wpa_supplicant's
own timer.  With `ap_scan=1` the supplicant arms a 10 s association timeout on
Connect and, on EVENT_ASSOC, re-arms the same 10 s as "timeout for receiving
the first EAPOL packet".  The two runs measured 9.83 s and 10.05 s from
association, which is exactly the ambiguity: run 1 fits "EVENT_ASSOC never
arrived, the original timer expired", run 2 fits "EVENT_ASSOC arrived, the
first EAPOL never did".  No capture can separate those two without knowing
whether any EAPOL frame moved.

WMI_CONNECT goes out with `ctrl_flags = 0x0008` (CONNECT_PROFILE_MATCH_DONE)
and *without* `CONNECT_DO_WPA_OFFLOAD` (0x0040), so the host owns the 4-way
handshake: for a WPA2-PSK AP the first EAPOL frame must arrive from the AP
within milliseconds of association.

This traces ethertype 0x888E at the two points where frames cross between the
driver and the network stack, capped at twelve lines per direction per
association so it cannot become another log firehose, and resets the counters
on each connect so every attempt is counted separately.

Reading the result:

  * `EAPOL rx #1` present  -> the AP really associated us and started the
    handshake; the failure is above the driver (supplicant never saw the frame,
    or never sent its reply).
  * `EAPOL rx` absent, `EAPOL tx` absent -> the supplicant was still waiting for
    EVENT_ASSOC and never began; look at the connect_result path.
  * `EAPOL tx` present with `conn=0` -> frames were being dropped by
    ar6000_data_tx()'s not-associated guard.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
DRV = ROOT / "os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_EAPOL_TRACE"

HELPER_OLD = '''static int
ar6000_data_tx(struct sk_buff *skb, struct net_device *dev)
{
'''

HELPER_NEW = '''/* N3DS_AR6014_EAPOL_TRACE: the host owns the 4-way handshake (WMI_CONNECT is
 * sent without CONNECT_DO_WPA_OFFLOAD), so on a WPA2-PSK AP the first EAPOL
 * frame must arrive within milliseconds of association.  Both associations on
 * hardware were torn down ~10 s later by the host, which is either
 * wpa_supplicant's association timeout or its first-EAPOL timeout -- the two
 * are the same duration and nothing in the log distinguishes them.  Counting
 * ethertype 0x888E in each direction does.  Bounded to twelve lines per
 * direction per association. */
#define N3DS_EAPOL_ETHERTYPE    0x888E
#define N3DS_EAPOL_TRACE_MAX    12

static atomic_t n3ds_eapol_tx_count = ATOMIC_INIT(0);
static atomic_t n3ds_eapol_rx_count = ATOMIC_INIT(0);

static void
n3ds_eapol_trace(struct sk_buff *skb, const char *dir, atomic_t *counter,
                 int connected)
{
    const u8 *eth;
    int n;

    if (!skb || A_NETBUF_LEN(skb) < 14)
        return;

    eth = (const u8 *)A_NETBUF_DATA(skb);
    if (((eth[12] << 8) | eth[13]) != N3DS_EAPOL_ETHERTYPE)
        return;

    n = atomic_inc_return(counter);
    if (n > N3DS_EAPOL_TRACE_MAX)
        return;

    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 EAPOL %s #%d len=%d conn=%d\\n",
         dir, n, (int)A_NETBUF_LEN(skb), connected));
}

static void
n3ds_eapol_trace_reset(void)
{
    atomic_set(&n3ds_eapol_tx_count, 0);
    atomic_set(&n3ds_eapol_rx_count, 0);
}

static int
ar6000_data_tx(struct sk_buff *skb, struct net_device *dev)
{
'''

# Traced before the not-associated guard, so a frame dropped there is still
# reported (with conn=0) instead of vanishing.
TX_OLD = '''    /* If target is not associated */
    if( (!ar->arConnected && !bypasswmi)
'''

TX_NEW = '''    n3ds_eapol_trace(skb, "tx", &n3ds_eapol_tx_count, ar->arConnected ? 1 : 0);

    /* If target is not associated */
    if( (!ar->arConnected && !bypasswmi)
'''

# Traced before eth_type_trans(), which pulls the ethernet header off.
RX_OLD = '''#endif /* CONFIG_PM */
            skb->protocol = eth_type_trans(skb, skb->dev);
'''

RX_NEW = '''#endif /* CONFIG_PM */
            n3ds_eapol_trace(skb, "rx", &n3ds_eapol_rx_count, 1);
            skb->protocol = eth_type_trans(skb, skb->dev);
'''

RESET_OLD = '''    netif_wake_queue(ar->arNetDev);

    /* Update connect & link status atomically */
    spin_lock_irqsave(&ar->arLock, flags);
    ar->arConnected  = true;
'''

RESET_NEW = '''    netif_wake_queue(ar->arNetDev);

    /* N3DS_AR6014_EAPOL_TRACE: count each association separately. */
    n3ds_eapol_trace_reset();

    /* Update connect & link status atomically */
    spin_lock_irqsave(&ar->arLock, flags);
    ar->arConnected  = true;
'''

HUNKS = (
    ("eapol trace helper", HELPER_OLD, HELPER_NEW),
    ("tx trace", TX_OLD, TX_NEW),
    ("rx trace", RX_OLD, RX_NEW),
    ("per-association reset", RESET_OLD, RESET_NEW),
)


def patch_drv(text: str) -> str:
    """Add bounded EAPOL tracing to ar6000_drv.c source text.

    Idempotent: an already-patched tree is returned untouched.
    """
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def main() -> None:
    original = DRV.read_text(encoding="utf-8")
    patched = patch_drv(original)
    if patched == original:
        print("ar6014_eapol_trace: already applied")
        return
    DRV.write_text(patched, encoding="utf-8")
    print(f"ar6014_eapol_trace: patched {DRV}")


if __name__ == "__main__":
    main()
