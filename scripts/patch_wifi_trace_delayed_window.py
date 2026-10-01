"""Give the delayed Wi-Fi trace stages room for a whole AP failure.

The Mobile Data failure lands ~220 s into the boot, so it is captured by a
"delayed" stage of the Wi-Fi trace, and those stages kept only the last 64
filtered dmesg lines.  A single target assert used to emit 60 register lines on
its own, so every ``AR6002 AP:`` line and the entire WMI command-history ring
were pushed out of the window by the dump that was meant to explain them --
twice, in both AP runs captured so far.

N3DS_AR6014_REGDUMP_COMPACT fixes the cause (60 register lines become 8).  This
widens the window as well, because what has to fit is now the assert lines plus
~10 AP profile lines plus a 16-entry command ring, and 64 leaves no margin for
the ordinary AR6002 chatter interleaved with them.  96 does, at a cost of about
30 extra lines per stage in a file that is currently ~60 KB.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    ROOT
    / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh"
)

MARKER = "N3DS_WIFI_TRACE_DELAYED_WINDOW"

WINDOW_OLD = r"""WIFI_INITIAL_LINES=256
WIFI_DELAYED_LINES=64
"""

WINDOW_NEW = r"""WIFI_INITIAL_LINES=256
# N3DS_WIFI_TRACE_DELAYED_WINDOW: the Mobile Data AP failure lands ~220 s in,
# so it is only ever captured by a delayed stage.  At 64 lines a single target
# assert (60 register lines before N3DS_AR6014_REGDUMP_COMPACT) evicted every
# AR6002 AP: line and the whole WMI command-history ring -- the dump destroyed
# the evidence it was printed to explain, in both AP runs captured so far.
# What has to fit now is ~8 register lines + ~10 AP profile lines + a 16-entry
# command ring plus the AR6002 chatter interleaved with them.
WIFI_DELAYED_LINES=96
"""

HUNKS = (("widen the delayed trace window", WINDOW_OLD, WINDOW_NEW),)


def patch_boot_progress(text):
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
    patched = patch_boot_progress(text)
    if patched == text:
        print("patch_wifi_trace_delayed_window: already applied")
        return
    TARGET.write_text(patched)
    print("patch_wifi_trace_delayed_window: applied to %s" % TARGET)


if __name__ == "__main__":
    main()
