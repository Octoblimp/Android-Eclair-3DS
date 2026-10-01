#!/usr/bin/env python3
"""Split the raw RX census into control-endpoint and data-endpoint counts.

W18 added `raw=` at the top of ar6000_rx(), before any early return, so that
`frames=0` could be told apart from "the driver dropped everything".  It sits
above the `ept == ar->arControlEp` split, though, so it counts WMI control
events and data frames in one bucket -- and that made the #256 capture
ambiguous in exactly the way it was meant to prevent.

`raw=47 frames=0` reads at first glance as 47 delivered packets thrown away by
the driver.  It is not.  An unknown WMI event, ID 0x1025, arrives on the
control endpoint roughly every 300 ms with a 1-byte payload; over the ten
seconds the link was up that alone accounts for about 33 of the 47, and the
remaining control traffic covers the rest.  The correct reading is that the
target delivered zero *data* frames, which is a different failure and points
somewhere else entirely.

Counting the two endpoints separately makes that unambiguous without adding a
per-frame print: `ctrl` is WMI event traffic, `data` is everything HTC
delivered on a data endpoint, and `data=0 frames=0` now means the radio heard
nothing while `data>0 frames=0` means the driver dropped it.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
DRV = ROOT / "os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_RX_ENDPOINT_CENSUS"

COUNTERS_OLD = '''static atomic_t n3ds_rx_raw = ATOMIC_INIT(0);
static atomic_t n3ds_rx_raw_err = ATOMIC_INIT(0);

static void
n3ds_rx_raw_census(int status)
{
    atomic_inc(&n3ds_rx_raw);
    if (status != 0) {
        atomic_inc(&n3ds_rx_raw_err);
    }
}
'''

COUNTERS_NEW = '''static atomic_t n3ds_rx_raw = ATOMIC_INIT(0);
static atomic_t n3ds_rx_raw_err = ATOMIC_INIT(0);

/* N3DS_AR6014_RX_ENDPOINT_CENSUS: raw alone mixes WMI control events with
 * data frames, and in #256 that made 47 packets look like 47 dropped frames
 * when almost all of them were one unknown control event repeating every
 * ~300 ms.  Split the two: data=0 frames=0 means the radio heard nothing,
 * data>0 frames=0 means the driver dropped what arrived. */
static atomic_t n3ds_rx_raw_ctrl = ATOMIC_INIT(0);
static atomic_t n3ds_rx_raw_data = ATOMIC_INIT(0);

static void
n3ds_rx_raw_census(int status, int is_ctrl)
{
    atomic_inc(&n3ds_rx_raw);
    if (is_ctrl) {
        atomic_inc(&n3ds_rx_raw_ctrl);
    } else {
        atomic_inc(&n3ds_rx_raw_data);
    }
    if (status != 0) {
        atomic_inc(&n3ds_rx_raw_err);
    }
}
'''

REPORT_OLD = '''    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 census %s raw=%d rawerr=%d frames=%d bcast=%d "
         "eapol_rx=%d eapol_tx=%d\\n",
         why, atomic_read(&n3ds_rx_raw), atomic_read(&n3ds_rx_raw_err),
         atomic_read(&n3ds_rx_frames), atomic_read(&n3ds_rx_bcast),
         atomic_read(&n3ds_eapol_rx_count), atomic_read(&n3ds_eapol_tx_count)));
'''

REPORT_NEW = '''    AR_DEBUG_PRINTF(ATH_DEBUG_ERR,
        ("AR6002 census %s raw=%d ctrl=%d data=%d rawerr=%d frames=%d "
         "bcast=%d eapol_rx=%d eapol_tx=%d\\n",
         why, atomic_read(&n3ds_rx_raw),
         atomic_read(&n3ds_rx_raw_ctrl),      /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
         atomic_read(&n3ds_rx_raw_data),      /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
         atomic_read(&n3ds_rx_raw_err),
         atomic_read(&n3ds_rx_frames), atomic_read(&n3ds_rx_bcast),
         atomic_read(&n3ds_eapol_rx_count), atomic_read(&n3ds_eapol_tx_count)));
'''

RESET_OLD = '''    atomic_set(&n3ds_rx_raw, 0);          /* N3DS_AR6014_RX_RAW_CENSUS */
    atomic_set(&n3ds_rx_raw_err, 0);      /* N3DS_AR6014_RX_RAW_CENSUS */
'''

RESET_NEW = '''    atomic_set(&n3ds_rx_raw, 0);          /* N3DS_AR6014_RX_RAW_CENSUS */
    atomic_set(&n3ds_rx_raw_err, 0);      /* N3DS_AR6014_RX_RAW_CENSUS */
    atomic_set(&n3ds_rx_raw_ctrl, 0);     /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
    atomic_set(&n3ds_rx_raw_data, 0);     /* N3DS_AR6014_RX_ENDPOINT_CENSUS */
'''

CALLSITE_OLD = '''    n3ds_rx_raw_census(status);    /* N3DS_AR6014_RX_RAW_CENSUS */
'''

CALLSITE_NEW = '''    /* N3DS_AR6014_RX_ENDPOINT_CENSUS: ept is already read above, so the
     * control/data split costs nothing here and removes the ambiguity that
     * made the #256 raw count unreadable. */
    n3ds_rx_raw_census(status, (ept == ar->arControlEp) ? 1 : 0);
'''

HUNKS = (
    ("raw counters", COUNTERS_OLD, COUNTERS_NEW),
    ("census report", REPORT_OLD, REPORT_NEW),
    ("census reset", RESET_OLD, RESET_NEW),
    ("rx call site", CALLSITE_OLD, CALLSITE_NEW),
)


def patch_driver(text: str) -> str:
    """Split the raw RX census by HTC endpoint in ar6000_drv.c source text.

    Idempotent: an already-patched tree is returned untouched so the patcher
    can be re-run after an unrelated driver change.
    """
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def main() -> None:
    original = DRV.read_text(encoding="utf-8")
    patched = patch_driver(original)
    if patched == original:
        print("ar6014_rx_endpoint_census: already applied")
        return
    DRV.write_text(patched, encoding="utf-8")
    print(f"ar6014_rx_endpoint_census: patched {DRV}")


if __name__ == "__main__":
    main()
