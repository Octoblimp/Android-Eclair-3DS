#!/usr/bin/env python3
"""Stop the Wi-Fi trace's sliding tail from evicting the driver bring-up window.

boot_progress.sh takes a filtered dmesg snapshot every 30 s and keeps the last
WIFI_DELAYED_LINES (96) matching lines.  In build #257 the ath6kl module loaded
between the snapshot at uptime 111.8 s (wlan0 absent) and the one at 144.3 s
(wlan0 present), and by the time that later snapshot ran the driver had already
emitted more than 96 matching lines.  The whole bring-up window -- the BMI
download, the HTC setup and the "AR6002 AP: WMI ready" banner -- was pushed out
of the tail and appeared in no capture at all.

That cost a real answer: W19b's n3ds_set_max_perf(ar, "wmiready") call could not
be confirmed, because its log line is emitted in exactly the window the tail
discards.  The strings are present in the shipped ath6kl.ko, so the code is
there; only the evidence was missing.

Take one extra, much larger snapshot the first time wlan0 exists.  It is
one-shot -- guarded by a stamp file in tmpfs -- so it cannot grow into
continuous SD traffic, which is what the bounded snapshots exist to avoid.
"""

import sys
from pathlib import Path

MARKER = "N3DS_WIFI_TRACE_BRINGUP_SNAPSHOT"

TARGETS = (
    "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh",
)

VARS_OLD = "WIFI_DELAYED_LINES=96\n"

VARS_NEW = """WIFI_DELAYED_LINES=96
# N3DS_WIFI_TRACE_BRINGUP_SNAPSHOT: the delayed tail above is sized for a
# steady-state stage, and the driver emits far more than 96 matching lines in
# the 30 s that contain its own bring-up.  In #257 that silently evicted the
# BMI download, the HTC setup and the WMI-ready banner from every capture, so
# a patch whose only evidence is printed there could not be confirmed at all.
# Take one much larger snapshot the first time wlan0 exists.
WIFI_BRINGUP_LINES=600
WIFI_BRINGUP_STAMP=/tmp/.wifi_bringup_captured
"""

SNAP_OLD = """\t\t\tcat "$WIFI_SNAPSHOT_TMP" >> "$WIFI_OUT" 2>/dev/null || true
\t\t\trm -f "$WIFI_SNAPSHOT_TMP"
\t\tfi
\tfi
"""

SNAP_NEW = """\t\t\tcat "$WIFI_SNAPSHOT_TMP" >> "$WIFI_OUT" 2>/dev/null || true
\t\t\trm -f "$WIFI_SNAPSHOT_TMP"
\t\tfi
\tfi

\t# N3DS_WIFI_TRACE_BRINGUP_SNAPSHOT: one-shot, taken the first interval in
\t# which wlan0 exists, so the module-load window survives the sliding tail.
\tif [ ! -f "$WIFI_BRINGUP_STAMP" ] && [ -d /sys/class/net/wlan0 ]; then
\t\tif {
\t\t\techo "=== $(date) uptime=$(cat /proc/uptime 2>/dev/null) stage=bringup ==="
\t\t\tprintf '%s\\n' "$snap" | grep -iE "$WIFI_RE" | tail -n "$WIFI_BRINGUP_LINES" || true
\t\t\techo "=== end stage=bringup ==="
\t\t} >> "$WIFI_OUT" 2>/dev/null; then
\t\t\t: > "$WIFI_BRINGUP_STAMP" 2>/dev/null || true
\t\tfi
\tfi
"""

HUNKS = (
    ("bring-up budget", VARS_OLD, VARS_NEW),
    ("one-shot snapshot", SNAP_OLD, SNAP_NEW),
)


def patch_one(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="surrogateescape")
    if MARKER in text:
        print("OK    %s already carries %s" % (path, MARKER))
        return False

    for name, old, new in HUNKS:
        count = text.count(old)
        assert count == 1, "hunk %r matched %d times in %s, expected 1" % (
            name, count, path)
        text = text.replace(old, new, 1)

    # Explicit newline: this file is an LF-only shell script that also lives in
    # the Windows workspace, where the default translation would emit CRLF and
    # make it unrunnable on the device.
    with path.open("w", encoding="utf-8", errors="surrogateescape",
                   newline="\n") as handle:
        handle.write(text)
    print("PATCH %s (%d hunks, %s)" % (path, len(HUNKS), MARKER))
    return True


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    seen = 0
    for rel in TARGETS:
        path = root / rel
        if not path.is_file():
            print("SKIP  %s (not present in this workspace)" % rel)
            continue
        seen += 1
        patch_one(path)
    if seen == 0:
        print("SKIP  no boot_progress.sh in this workspace")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
