#!/usr/bin/env python3
"""Count receives at the HTC boundary, not just at the netdev handover (W18).

W15's census counts frames in `ar6000_deliver_frames_to_nw_stack()`, which is
the last statement before `netif_rx()`.  Build #255 reported `frames=0
bcast=0` on every association, and that number cannot distinguish the two
faults that matter:

*   the target hands the driver nothing at all -- the association is nominal
    and no data ever leaves the firmware;
*   the target hands the driver plenty and the driver drops all of it before
    the handover, somewhere in the several hundred lines of `ar6000_rx()`
    between the HTC callback and the delivery call.

`bcast=0` on its own is not evidence of the first, either: before the four-way
handshake completes the station has no GTK, so the AP's broadcast traffic is
undecryptable and correctly discarded.  Zero broadcast is the *expected*
reading for an unauthorised link, which is why it settles nothing.

This adds two counters at the top of `ar6000_rx()`, before any early return:
every HTC packet the driver is handed, and how many arrived with a non-zero
`pPacket->Status`.  They ride the existing per-association reset and the
existing one-line report, so the cost is two atomics and no new print.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "third_party/linux/drivers/staging/ath6k_legacy/os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_RX_RAW_CENSUS"

COUNTER_OLD = """static atomic_t n3ds_rx_frames = ATOMIC_INIT(0);
static atomic_t n3ds_rx_bcast = ATOMIC_INIT(0);
"""

COUNTER_NEW = """static atomic_t n3ds_rx_frames = ATOMIC_INIT(0);
static atomic_t n3ds_rx_bcast = ATOMIC_INIT(0);

/* N3DS_AR6014_RX_RAW_CENSUS: frames=0 cannot tell "the target delivered
 * nothing" from "the driver dropped everything on the way to the stack".
 * Count at the HTC callback instead, before any early return. */
static atomic_t n3ds_rx_raw = ATOMIC_INIT(0);
static atomic_t n3ds_rx_raw_err = ATOMIC_INIT(0);

static void
n3ds_rx_raw_census(int status)
{
    atomic_inc(&n3ds_rx_raw);
    if (status != 0) {
        atomic_inc(&n3ds_rx_raw_err);
    }
}
"""

REPORT_OLD = """        ("AR6002 census %s frames=%d bcast=%d eapol_rx=%d eapol_tx=%d\\n",
         why, atomic_read(&n3ds_rx_frames), atomic_read(&n3ds_rx_bcast),
         atomic_read(&n3ds_eapol_rx_count), atomic_read(&n3ds_eapol_tx_count)));
"""

REPORT_NEW = """        ("AR6002 census %s raw=%d rawerr=%d frames=%d bcast=%d "
         "eapol_rx=%d eapol_tx=%d\\n",
         why, atomic_read(&n3ds_rx_raw), atomic_read(&n3ds_rx_raw_err),
         atomic_read(&n3ds_rx_frames), atomic_read(&n3ds_rx_bcast),
         atomic_read(&n3ds_eapol_rx_count), atomic_read(&n3ds_eapol_tx_count)));
"""

RESET_OLD = """    atomic_set(&n3ds_rx_frames, 0);
    atomic_set(&n3ds_rx_bcast, 0);
}
"""

RESET_NEW = """    atomic_set(&n3ds_rx_frames, 0);
    atomic_set(&n3ds_rx_bcast, 0);
    atomic_set(&n3ds_rx_raw, 0);          /* N3DS_AR6014_RX_RAW_CENSUS */
    atomic_set(&n3ds_rx_raw_err, 0);      /* N3DS_AR6014_RX_RAW_CENSUS */
}
"""

RX_OLD = """    int        status = pPacket->Status;
    HTC_ENDPOINT_ID   ept = pPacket->Endpoint;

    A_ASSERT((status) ||
"""

RX_NEW = """    int        status = pPacket->Status;
    HTC_ENDPOINT_ID   ept = pPacket->Endpoint;

    n3ds_rx_raw_census(status);    /* N3DS_AR6014_RX_RAW_CENSUS */

    A_ASSERT((status) ||
"""

HUNKS = (
    ("raw receive counters", COUNTER_OLD, COUNTER_NEW),
    ("report the raw counters", REPORT_OLD, REPORT_NEW),
    ("reset the raw counters per association", RESET_OLD, RESET_NEW),
    ("count at the HTC callback", RX_OLD, RX_NEW),
)


def patch_driver(text):
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, (
            "%s: anchor matched %d times, expected 1" % (name, text.count(old)))
        text = text.replace(old, new)
    return text


def main():
    text = TARGET.read_text(encoding="utf-8")
    patched = patch_driver(text)
    if patched == text:
        print("patch_ar6014_rx_raw_census: already applied")
        return 0
    TARGET.write_text(patched, encoding="utf-8")
    print("patch_ar6014_rx_raw_census: applied %d hunks" % len(HUNKS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
