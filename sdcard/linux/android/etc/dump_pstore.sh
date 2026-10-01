#!/bin/sh
# dump_pstore.sh — copies any pstore/ramoops crash records from the previous
# boot to the SD card as boot_progress.txt and crash_log.txt.
# Runs early in init.rc before the main bootlog service.
#
# pstore mounts at /sys/fs/pstore.  ramoops writes:
#   dmesg-ramoops-N   — kernel oops/panic kmsg records
#   console-ramoops-0 — full kernel console ring
#   pmsg-ramoops-0    — userspace logcat-via-pmsg records
#
# On a clean boot (no previous crash) these files simply don't exist and
# this script silently exits in under 1ms.

set -C   # noclobber: never overwrite existing files

PSTORE=/sys/fs/pstore
SD=/mnt/sd/linux

mount -t pstore pstore "$PSTORE" 2>/dev/null || true

# Nothing to do if pstore is empty (clean boot)
if ! ls "$PSTORE"/dmesg-ramoops-* "$PSTORE"/console-ramoops-0 2>/dev/null | grep -q .; then
    exit 0
fi

echo "[pstore] crash records found from previous boot" > /dev/tty0

# Find a unique filename slot (crash_log.txt, crash_log_1.txt, ...)
find_slot() {
    local base="$1"
    local i=0
    while [ "$i" -lt 100 ]; do
        if [ "$i" -eq 0 ]; then
            echo "${SD}/${base}.txt"
        else
            echo "${SD}/${base}_${i}.txt"
        fi
        i=$((i + 1))
    done
}

write_to_first_free() {
    local base="$1"
    local i=0
    while [ "$i" -lt 100 ]; do
        if [ "$i" -eq 0 ]; then
            target="${SD}/${base}.txt"
        else
            target="${SD}/${base}_${i}.txt"
        fi
        if (
            echo "=== N3DS Android crash log — captured from previous boot ==="
            echo "=== date at dump time ===" ; date
            echo "=== uname ===" ; uname -a
            echo ""
            echo "=== dmesg-ramoops (kernel panic record) ==="
            cat "$PSTORE"/dmesg-ramoops-* 2>/dev/null || echo "(none)"
            echo ""
            echo "=== console-ramoops (full console ring) ==="
            cat "$PSTORE"/console-ramoops-0 2>/dev/null || echo "(none)"
        ) > "$target" 2>/dev/null; then
            echo "[pstore] crash log written to $(basename $target)" > /dev/tty0
            return 0
        fi
        i=$((i + 1))
    done
    return 1
}

write_pmsg_to_first_free() {
    local base="$1"
    local i=0
    while [ "$i" -lt 100 ]; do
        if [ "$i" -eq 0 ]; then
            target="${SD}/${base}.txt"
        else
            target="${SD}/${base}_${i}.txt"
        fi
        if (
            echo "=== N3DS Android userspace logcat (pmsg) — previous boot ==="
            echo "=== date at dump time ===" ; date
            echo ""
            cat "$PSTORE"/pmsg-ramoops-0 2>/dev/null || echo "(none)"
        ) > "$target" 2>/dev/null; then
            echo "[pstore] logcat dump written to $(basename $target)" > /dev/tty0
            return 0
        fi
        i=$((i + 1))
    done
    return 1
}

write_to_first_free "crash_log"
write_pmsg_to_first_free "logcat_crash"

# Also update/append to a rolling boot_progress.txt so every boot has
# a note that says whether a crash was detected.
{
    echo "=== CRASH DETECTED ON PREVIOUS BOOT ==="
    echo "See crash_log.txt (or crash_log_N.txt) on this SD card."
    echo "Timestamp of this note: $(date)"
} >> "${SD}/boot_progress.txt" 2>/dev/null

# Remove the pstore records now that we've saved them, so next clean boot
# they don't re-appear and confuse the analysis.
rm -f "$PSTORE"/dmesg-ramoops-* "$PSTORE"/console-ramoops-0 "$PSTORE"/pmsg-ramoops-0 2>/dev/null

sync
