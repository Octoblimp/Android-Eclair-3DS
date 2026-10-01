#!/usr/bin/env python3
"""N3DS_BOOT_PROGRESS_FSYNC: make appended ticks actually reach the card.

The 2026-09-12 capture contains exactly ONE tick (uptime=57.09) even though
the machine ran well past 113 s and MAX_SNAPSHOTS allows twenty.  The loop is
correct -- what is missing is durability.  Tick 0 lands because it truncates
and rewrites, which forces cluster allocation; every append after it only
dirties page cache, and on this board nothing ever flushes that.  A bare
`sync` is banned (N3DS_NO_GLOBAL_SYNC, right below this change) because it
blocks on every SD-backed mount, and the only other flush in the system is
the `mount -o remount,ro` at poweroff -- which a hang or a battery pull never
reaches.

fsync() of one file has none of that blast radius: it waits on this file's
own dirty pages and its FAT/dirent metadata, a few KB per tick.  busybox has
no fsync applet in this config (CONFIG_FSYNC is not set) but dd's
conv=fsync is unconditional under FEATURE_DD_IBS_OBS, which is enabled; with
if=/dev/null and conv=notrunc it writes nothing, truncates nothing, and
fsyncs the output fd on the way out.
"""
from a3ds_paths import A3DS_ROOT
import io
import sys

PATH = (f"{A3DS_ROOT}/third_party/buildroot/board/nintendo3ds"
        "/rootfs_overlay/etc/boot_progress.sh")

src = io.open(PATH, encoding="utf-8").read()
orig = src

# ------------------------------------------------------------- helper ---
old = '''kmsg() {
	echo "boot-progress: $1" > /dev/kmsg 2>/dev/null
}
'''
new = '''kmsg() {
	echo "boot-progress: $1" > /dev/kmsg 2>/dev/null
}

# N3DS_BOOT_PROGRESS_FSYNC: flush ONE file, not the world.  See the
# N3DS_NO_GLOBAL_SYNC note in the loop below for why `sync` is banned here.
# busybox in this config has no fsync applet, but dd conv=fsync is compiled
# in; if=/dev/null + conv=notrunc means it writes nothing and truncates
# nothing, it just fsync()s the fd it opened.
fsync_file() {
	[ -f "$1" ] || return 0
	dd if=/dev/null of="$1" conv=notrunc,fsync 2>/dev/null || true
}
'''
assert old in src, "kmsg helper anchor missing"
src = src.replace(old, new, 1)

# --------------------------------------------------------- call sites ---
old = '''	# N3DS_NO_GLOBAL_SYNC: a bare `sync` here blocks until every dirty page on
'''
new = '''	# N3DS_BOOT_PROGRESS_FSYNC: without this, every tick after the first one
	# stays in FAT page cache and dies with the machine.  That is not a
	# theory: the 2026-09-12 capture has one tick at uptime=57 and nothing
	# after it, on a boot that ran for minutes -- which is why the
	# supplicant's own "attempt N died after Xs rc=" kmsg, emitted at
	# t~113 s, has never once appeared in a capture.
	fsync_file "$OUT"
	fsync_file "$WIFI_OUT"
	fsync_file "$CRASH_OUT"

	# N3DS_NO_GLOBAL_SYNC: a bare `sync` here blocks until every dirty page on
'''
assert old in src, "N3DS_NO_GLOBAL_SYNC anchor missing"
src = src.replace(old, new, 1)

# Keep the NO_GLOBAL_SYNC rationale honest now that a scoped flush exists.
old = '''	# never sees a half-written snapshot; ordinary kernel writeback flushes it
	# out shortly after without this script blocking on anyone else's I/O.
'''
new = '''	# never sees a half-written snapshot, and the scoped fsync_file() calls
	# above commit this script's own files without ever waiting on anyone
	# else's I/O -- which is the part `sync` gets wrong, not the flushing.
'''
assert old in src, "NO_GLOBAL_SYNC tail anchor missing"
src = src.replace(old, new, 1)

if src == orig:
    sys.stderr.write("no changes made\\n")
    sys.exit(1)

io.open(PATH, "w", encoding="utf-8", newline="\n").write(src)
print("patched " + PATH)
