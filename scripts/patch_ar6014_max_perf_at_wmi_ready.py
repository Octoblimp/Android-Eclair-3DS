#!/usr/bin/env python3
"""Send MAX_PERF_POWER at WMI-ready, where it can actually be sent.

W17 (patch_ar6014_max_perf_power.py) claims two call sites: once at init and
again on every association.  Only the second one has ever produced a line.
Build #256 logged `AR6002 power: MAX_PERF at connect status=0` twenty-five
times and `at init` exactly zero times.

That is not a firmware refusal.  n3ds_set_max_perf() returns early unless
ar->arWmiReady is true, and the init call site sits inside ar6000_init(),
which runs before the WMI_READY event handler sets that flag.  The init call
has therefore been silently returning on every boot since it was written.

The first moment the command can go out is immediately after
`ar->arWmiReady = true;` in ar6000_ready_event().  Sending it there rather
than only on association also means the radio leaves power save before the
connect-time scan, not several seconds after the station has already joined
asleep -- which is the failure mode the power-save work was chasing to begin
with.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(f"{A3DS_ROOT}/third_party/linux/drivers/staging/"
            "ath6k_legacy")
DRV = ROOT / "os/linux/ar6000_drv.c"

MARKER = "N3DS_AR6014_MAX_PERF_AT_WMI_READY"

READY_OLD = '''    /* Indicate to the waiting thread that the ready event was received */
    ar->arWmiReady = true;
    wake_up(&arEvent);
'''

READY_NEW = '''    /* Indicate to the waiting thread that the ready event was received */
    ar->arWmiReady = true;

    /* N3DS_AR6014_MAX_PERF_AT_WMI_READY: W17's init-time call lives inside
     * ar6000_init(), which runs before this line, so n3ds_set_max_perf()
     * hit its !arWmiReady early return every time and "MAX_PERF at init"
     * has never appeared in a single log.  This is the first point where
     * the command can actually reach the target, and sending it here takes
     * the radio out of power save before the connect-time scan instead of
     * after the station has already associated asleep. */
    n3ds_set_max_perf(ar, "wmiready");

    wake_up(&arEvent);
'''

HUNKS = (
    ("wmi ready max perf", READY_OLD, READY_NEW),
)


def patch_driver(text: str) -> str:
    """Send MAX_PERF_POWER from the WMI-ready handler in ar6000_drv.c.

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
        print("ar6014_max_perf_at_wmi_ready: already applied")
        return
    DRV.write_text(patched, encoding="utf-8")
    print(f"ar6014_max_perf_at_wmi_ready: patched {DRV}")


if __name__ == "__main__":
    main()
