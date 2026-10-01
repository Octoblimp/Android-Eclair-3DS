#!/usr/bin/env python3
"""Keep the supplicant lines that matter for the whole boot, not the last 128 K.

`wpa_supplicant.log` on the SD card is `tail -c 131072` of a live log that is
itself rotated at 192 K down to its last 128 K.  In the 2026-09-01 capture that
window covered uptime 271-375 s.  The only two connect attempts in the entire
boot that ever reached the driver -- and the only two that ever associated --
happened at 128 s and 258 s.  Both were truncated away before the file was ever
written.  Every conclusion about what wpa_supplicant did around a successful
association has had to be inferred from kernel messages instead.

A head window does not fix it either: at the observed rate (~128 K per 100 s of
`-d` output) the first 128 K would have ended before the 128 s attempt.

So keep a third file that is selected by *content* rather than position: every
line naming an association, authentication, EAPOL exchange, state change,
control event, disconnect or failure, written until the file is full and never
rotated.  At roughly 5-10% of the line volume, 96 K covers a whole boot, and
because it stops growing once full it costs the SD card a bounded number of
writes -- which matters here, see the SD write-path collapse notes.

The existing tail snapshot is untouched: it still gives full `-d` detail around
whatever the daemon was doing most recently.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


DIAG = Path(f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds/"
            "rootfs_overlay/etc/wpa_supplicant_diag.sh")

MARKER = "N3DS_WPA_SUPPLICANT_KEY_LOG"

PATHS_OLD = '''PREV_BYTES=64512
LIVE_MAX_BYTES=196608
LIVE_KEEP_BYTES=131072
SNAPSHOT_SECONDS=30
'''

PATHS_NEW = '''PREV_BYTES=64512
LIVE_MAX_BYTES=196608
LIVE_KEEP_BYTES=131072
SNAPSHOT_SECONDS=30

# N3DS_WPA_SUPPLICANT_KEY_LOG: the live log is rotated and then snapshotted as
# a tail, so only the last ~100 s of a boot ever reaches the SD card.  Both
# associations in the 2026-09-01 capture happened well before that window and
# were lost.  This second file is selected by content instead of position: it
# holds the association / authentication / EAPOL / state / control-event /
# disconnect / failure lines for the whole boot, is never rotated, and stops
# growing once full.
KEY=/tmp/wpa_supplicant.key.$$
KEY_LOG=/mnt/sd/linux/wpa_supplicant.key.log
KEY_TMP=/mnt/sd/linux/.wpa_supplicant.key.tmp
KEY_MAX_BYTES=98304
KEY_RE='MLME|CTRL-EVENT|EAPOL|WPA:|RSN:|State:|ssociat|uthentic|eauthentic|isconnect|ignore list|Consecutive|Timeout|timed out|Failed|failed|SME:|nl80211: Connect|wlan0: Trying'
key_committed=0
'''

INIT_OLD = ''': > "$LIVE" 2>/dev/null || exit 127
'''

INIT_NEW = ''': > "$LIVE" 2>/dev/null || exit 127
: > "$KEY" 2>/dev/null || exit 127
'''

AWK_OLD = '''\t-v max="$LIVE_MAX_BYTES" -v keep="$LIVE_KEEP_BYTES" \\
\t-v bytes="$start_bytes" '
{
\tprint $0 >> out_path
\tclose(out_path)
\tbytes += length($0) + 1
'''

AWK_NEW = '''\t-v max="$LIVE_MAX_BYTES" -v keep="$LIVE_KEEP_BYTES" \\
\t-v key_path="$KEY" -v key_max="$KEY_MAX_BYTES" -v key_re="$KEY_RE" \\
\t-v bytes="$start_bytes" '
{
\tprint $0 >> out_path
\tclose(out_path)
\tbytes += length($0) + 1
\tif (key_bytes < key_max && $0 ~ key_re) {
\t\tprint $0 >> key_path
\t\tclose(key_path)
\t\tkey_bytes += length($0) + 1
\t}
'''

SNAPSHOT_OLD = '''snapshot()
{
\tif [ -d /mnt/sd/linux ]; then
\t\tLOG=/mnt/sd/linux/wpa_supplicant.log
\t\tSNAP_TMP=/mnt/sd/linux/.wpa_supplicant.log.tmp
\tfi
\tif tail -c "$LIVE_KEEP_BYTES" "$LIVE" > "$SNAP_TMP" 2>/dev/null; then
\t\tmv -f "$SNAP_TMP" "$LOG" 2>/dev/null || true
\tfi
}
'''

SNAPSHOT_NEW = '''snapshot_key()
{
\t# N3DS_WPA_SUPPLICANT_KEY_LOG: the key log stops growing once it is full,
\t# so this writes the card a handful of times per boot and then never
\t# again.  Skipping unchanged copies is the whole point -- an SD write on
\t# every snapshot is what the tail snapshot already costs.
\tkey_size=$(wc -c < "$KEY" 2>/dev/null) || return 0
\t[ -n "$key_size" ] || return 0
\t[ "$key_size" -gt "$key_committed" ] 2>/dev/null || return 0
\tif cp "$KEY" "$KEY_TMP" 2>/dev/null; then
\t\tif mv -f "$KEY_TMP" "$KEY_LOG" 2>/dev/null; then
\t\t\tkey_committed=$key_size
\t\tfi
\tfi
}

snapshot()
{
\tif [ -d /mnt/sd/linux ]; then
\t\tLOG=/mnt/sd/linux/wpa_supplicant.log
\t\tSNAP_TMP=/mnt/sd/linux/.wpa_supplicant.log.tmp
\t\tKEY_LOG=/mnt/sd/linux/wpa_supplicant.key.log
\t\tKEY_TMP=/mnt/sd/linux/.wpa_supplicant.key.tmp
\telse
\t\tKEY_LOG=/tmp/wpa_supplicant.key.log
\t\tKEY_TMP=/tmp/wpa_supplicant.key.tmp
\tfi
\tif tail -c "$LIVE_KEEP_BYTES" "$LIVE" > "$SNAP_TMP" 2>/dev/null; then
\t\tmv -f "$SNAP_TMP" "$LOG" 2>/dev/null || true
\tfi
\tsnapshot_key
}
'''

CLEANUP_OLD = '''rm -f "$STATUS" "$ROTATE_TMP" "$LIVE" "$SNAP_TMP"
'''

CLEANUP_NEW = '''rm -f "$STATUS" "$ROTATE_TMP" "$LIVE" "$SNAP_TMP" "$KEY" "$KEY_TMP"
'''

HUNKS = (
    ("key log paths", PATHS_OLD, PATHS_NEW),
    ("key log init", INIT_OLD, INIT_NEW),
    ("awk key selection", AWK_OLD, AWK_NEW),
    ("key snapshot", SNAPSHOT_OLD, SNAPSHOT_NEW),
    ("cleanup", CLEANUP_OLD, CLEANUP_NEW),
)


def patch_text(text: str) -> str:
    """Add the content-selected key log to wpa_supplicant_diag.sh.

    Idempotent: an already-patched tree is returned untouched.
    """
    if MARKER in text:
        return text
    for name, old, new in HUNKS:
        assert text.count(old) == 1, f"{name}: expected exactly one match"
        text = text.replace(old, new)
    return text


def main() -> None:
    original = DIAG.read_text(encoding="utf-8")
    patched = patch_text(original)
    if patched == original:
        print("wpa_supplicant_key_log: already applied")
        return
    DIAG.write_text(patched, encoding="utf-8")
    print(f"wpa_supplicant_key_log: patched {DIAG}")


if __name__ == "__main__":
    main()
