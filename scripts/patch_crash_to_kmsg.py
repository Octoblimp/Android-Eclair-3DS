#!/usr/bin/env python3
"""Mirror every uncaught Java exception to /dev/kmsg.

Why this exists.  When the Browser died twice on 2026-09-13 the kernel log
showed only "binder: undelivered transaction NNNN, process died" -- no fatal
signal, which with print-fatal-signals=1 and user_debug=24 on the command line
means it was not a fault but a clean exit, i.e. RuntimeInit killing the process
after an uncaught exception.  The stack trace went to the log ring, logcat.sh
rotates that ring at 256 KB, and by the time the card was read the trace had
been evicted.  So the one artefact that would have named the bug was the one
artefact that did not survive.

/dev/kmsg does survive: boot_progress.sh appends the whole of dmesg to
sd:/linux/boot_progress.txt every 30 s, and the kernel ring is far quieter than
the Android one.  A crash trace is at most a few dozen lines, once.

Everything here is wrapped so that it can never make a crash worse: if
/dev/kmsg is not writable, or the trace cannot be formatted, the failure is
swallowed and the normal path continues untouched.

Idempotent: guarded by N3DS_CRASH_TO_KMSG.
"""
import io
import os
import sys

BASE = os.path.expanduser("~/android3ds/third_party/frameworks/base")
RUNTIME_INIT = os.path.join(
    BASE, "core/java/com/android/internal/os/RuntimeInit.java")
INIT_RC = os.path.expanduser(
    "~/android3ds/third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/init.rc")

GUARD = "N3DS_CRASH_TO_KMSG"

HELPER = '''    /*
     * N3DS_CRASH_TO_KMSG: put the trace somewhere that survives.
     *
     * Log.e() goes to /dev/log/main, logcat.sh rotates that at 256 KB, and a
     * crash five minutes before the card is read is simply gone -- which is
     * how the 2026-09-13 Browser crash left nothing behind but "binder:
     * undelivered transaction, process died".  /dev/kmsg is picked up in full
     * by boot_progress.sh every 30 s, so a copy there reaches
     * sd:/linux/boot_progress.txt and outlives the ring.
     *
     * Bounded on purpose: kmsg takes one record per write and drops anything
     * past about a kilobyte, and a runaway trace must not push the driver
     * probe lines out of the kernel ring the way the Android ring already
     * gets pushed.  One header plus at most MAX_KMSG_LINES frames.
     *
     * Never throws.  A crash handler that crashes leaves the process alive
     * and wedged, which is worse than no diagnostics at all.
     */
    private static final int MAX_KMSG_LINES = 48;
    private static final int MAX_KMSG_LINE_CHARS = 700;

    /* Zygote renames the forked process with Process.setArgV0(), so
     * /proc/self/cmdline is the package name -- which is the first thing
     * anyone reading a crash line wants to know. */
    private static String procName() {
        FileInputStream in = null;
        try {
            in = new FileInputStream("/proc/self/cmdline");
            byte[] buf = new byte[128];
            int n = in.read(buf);
            if (n <= 0) {
                return "?";
            }
            int end = 0;
            while (end < n && buf[end] != 0) {
                end++;
            }
            return new String(buf, 0, end);
        } catch (Throwable ignored) {
            return "?";
        } finally {
            try {
                if (in != null) {
                    in.close();
                }
            } catch (Throwable ignored) {
            }
        }
    }

    private static void logCrashToKmsg(String tag, Throwable t) {
        FileOutputStream kmsg = null;
        try {
            String trace = Log.getStackTraceString(t);
            StringBuilder head = new StringBuilder();
            head.append("N3DS-CRASH pid=").append(Process.myPid());
            head.append(" tag=").append(tag);
            head.append(" proc=").append(procName());
            head.append(" ").append(t.toString());

            kmsg = new FileOutputStream("/dev/kmsg");
            writeKmsgLine(kmsg, head.toString());

            int written = 0;
            int from = 0;
            while (from < trace.length() && written < MAX_KMSG_LINES) {
                int nl = trace.indexOf(10, from);
                String line = (nl < 0) ? trace.substring(from)
                                       : trace.substring(from, nl);
                if (line.length() > 0) {
                    writeKmsgLine(kmsg, "N3DS-CRASH   " + line);
                    written++;
                }
                if (nl < 0) {
                    break;
                }
                from = nl + 1;
            }
            if (from < trace.length()) {
                writeKmsgLine(kmsg, "N3DS-CRASH   ...trace truncated at "
                        + MAX_KMSG_LINES + " lines; full text is in logcat");
            }
        } catch (Throwable ignored) {
            // Deliberately silent: see the comment above.
        } finally {
            try {
                if (kmsg != null) {
                    kmsg.close();
                }
            } catch (Throwable ignored) {
            }
        }
    }

    private static void writeKmsgLine(FileOutputStream kmsg, String line)
            throws IOException {
        if (line.length() > MAX_KMSG_LINE_CHARS) {
            line = line.substring(0, MAX_KMSG_LINE_CHARS);
        }
        kmsg.write((line + "\\n").getBytes());
    }

'''

CRASH_OLD = """    public static void crash(String tag, Throwable t) {
        if (mApplicationObject != null) {
"""

CRASH_NEW = """    public static void crash(String tag, Throwable t) {
        // N3DS_CRASH_TO_KMSG: before anything that can itself fail, and
        // before the mApplicationObject check, so a crash in the zygote or
        // in system_server is recorded too.
        logCrashToKmsg(tag, t);

        if (mApplicationObject != null) {
"""


def main():
    src = io.open(RUNTIME_INIT, encoding="utf-8").read()
    if GUARD in src:
        print("RuntimeInit.java already patched")
    else:
        if src.count(CRASH_OLD) != 1:
            sys.stderr.write("crash() anchor matched %d times\n"
                             % src.count(CRASH_OLD))
            return 2
        for imp in ("java.io.FileInputStream", "java.io.FileOutputStream"):
            line = "import " + imp + ";"
            if line not in src:
                src = src.replace("import java.io.IOException;",
                                  line + chr(10) +
                                  "import java.io.IOException;", 1)
        src = src.replace(CRASH_OLD, HELPER + CRASH_NEW)
        io.open(RUNTIME_INIT, "w", encoding="utf-8", newline="\n").write(src)
        print("patched %s" % RUNTIME_INIT)

    rc = io.open(INIT_RC, encoding="utf-8").read()
    if GUARD in rc:
        print("init.rc already patched")
        return 0
    anchor = "    chmod 0666 /dev/eac\n"
    if rc.count(anchor) != 1:
        sys.stderr.write("init.rc anchor matched %d times\n" % rc.count(anchor))
        return 2
    rc = rc.replace(anchor, anchor +
                    "    # N3DS_CRASH_TO_KMSG: RuntimeInit mirrors uncaught\n"
                    "    # exceptions here so a crash trace reaches\n"
                    "    # boot_progress.txt instead of being rotated out of the\n"
                    "    # 256 KB logcat ring. devtmpfs makes this 0600 root:root\n"
                    "    # and apps are not root, so without this the mirror is a\n"
                    "    # silent no-op for every process that matters.\n"
                    "    # Write-only: nothing needs to read the kernel ring back.\n"
                    "    chmod 0622 /dev/kmsg\n")
    io.open(INIT_RC, "w", encoding="utf-8", newline="\n").write(rc)
    print("patched %s" % INIT_RC)
    return 0


if __name__ == "__main__":
    sys.exit(main())
