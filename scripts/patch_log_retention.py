#!/usr/bin/env python3
"""Stop the Android log from evicting the evidence.

Two separate problems, both proven by sd:/linux/logcat.txt from the
2026-09-13 boot:

1. AOSP eclair ships Parcel.DEBUG_RECYCLE = true.  That makes every single
   Parcel.obtain() -- i.e. every binder call in every process -- allocate a
   RuntimeException purely to capture a stack trace, and makes every Parcel
   that reaches the finalizer without recycle() print that whole trace at
   W level.  In four minutes of an idle home screen it produced 422 of the
   1000 lines in logcat.txt, roughly eleven lines each.  It is a debug aid
   that AOSP left switched on; on a 268 MHz ARM11 it is also a per-binder-
   call fillInStackTrace() we pay for nothing.

2. logcat.sh kept 4 x 256 KB.  With the firehose above, the ring turned over
   in about ten minutes -- so when the Browser died at uptime 318 s (09:36:49
   by the RTC) and the card was read at 09:46, the crash trace had already
   been rotated out.  The one artefact that names the bug was the one
   artefact that did not survive.  6 x 1 MB is ~24x the history for no extra
   write volume: rotation size does not change how much is written, only how
   long it is kept.

Idempotent: re-running is a no-op.
"""
import io
import os
import sys

HOME = os.path.expanduser("~/android3ds")
PARCEL = os.path.join(
    HOME, "third_party/frameworks/base/core/java/android/os/Parcel.java")
LOGCAT = os.path.join(
    HOME, "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/logcat.sh")

PARCEL_OLD = "    private static final boolean DEBUG_RECYCLE = true;"
PARCEL_NEW = (
    "    /* N3DS: AOSP eclair ships this as true.  It costs a\n"
    "     * fillInStackTrace() on every Parcel.obtain() -- every binder call in\n"
    "     * every process -- and prints the captured trace from finalize() for\n"
    "     * any Parcel that was not recycled.  On 2026-09-13 that was 422 of the\n"
    "     * 1000 lines in four minutes of idle home screen, which is what rotated\n"
    "     * the Browser crash trace out of the log before the card could be read.\n"
    "     * Flip it back only for a targeted Parcel-leak hunt. */\n"
    "    private static final boolean DEBUG_RECYCLE = false;")

LOG_OLD = 'exec "$BIN" -v time -f "$LOGDIR/logcat.txt" -r 256 -n 3 "*:I"'
LOG_NEW = 'exec "$BIN" -v time -f "$LOGDIR/logcat.txt" -r 1024 -n 6 "*:I"'

LOG_COMMENT_OLD = "#   -f/-r/-n  4 x 256 KB rotating files: logcat.txt, .1, .2, .3"
LOG_COMMENT_NEW = (
    "#   -f/-r/-n  7 x 1 MB rotating files: logcat.txt, .1 .. .6.\n"
    "#             It used to be 4 x 256 KB, and that was not enough history:\n"
    "#             the Browser died at uptime 318 s on 2026-09-13 and by the\n"
    "#             time the card was read, nine minutes later, the trace had\n"
    "#             already been rotated out -- so the crash left nothing behind\n"
    "#             but a kernel line saying a process had gone.  Rotation size\n"
    "#             does not change how much is written, only how long it is\n"
    "#             kept, so this costs SD space and nothing else.")

LOG_ECHO_OLD = 'echo "logcat: writing $LOGDIR/logcat.txt (4 x 256K rotating)" \\'
LOG_ECHO_NEW = 'echo "logcat: writing $LOGDIR/logcat.txt (7 x 1M rotating)" \\'


def sub_once(text, old, new, what):
    n = text.count(old)
    if n != 1:
        sys.stderr.write("%s: anchor matched %d times\n" % (what, n))
        sys.exit(2)
    return text.replace(old, new)


def main():
    src = io.open(PARCEL, encoding="utf-8").read()
    if PARCEL_NEW.splitlines()[-1] in src:
        print("Parcel.java already patched")
    else:
        src = sub_once(src, PARCEL_OLD, PARCEL_NEW, "DEBUG_RECYCLE")
        io.open(PARCEL, "w", encoding="utf-8", newline="\n").write(src)
        print("patched %s" % PARCEL)

    rc = io.open(LOGCAT, encoding="utf-8").read()
    if LOG_NEW in rc:
        print("logcat.sh already patched")
        return 0
    rc = sub_once(rc, LOG_COMMENT_OLD, LOG_COMMENT_NEW, "logcat.sh comment")
    rc = sub_once(rc, LOG_ECHO_OLD, LOG_ECHO_NEW, "logcat.sh echo")
    rc = sub_once(rc, LOG_OLD, LOG_NEW, "logcat.sh exec")
    io.open(LOGCAT, "w", encoding="utf-8", newline="\n").write(rc)
    print("patched %s" % LOGCAT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
