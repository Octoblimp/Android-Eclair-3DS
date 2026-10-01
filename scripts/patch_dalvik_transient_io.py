#!/usr/bin/env python3
"""Retry bounded transient SD-card EIO while opening odex/dexopt.

The 3DS root filesystem is backed by the ARM9 virtio/FAT path.  Hardware logs
showed a valid 48 KiB side-by-side odex fail its first header read with EIO,
followed immediately by execv(/system/bin/dexopt) failing with EIO.  Treating
that one transient failure as a stale odex turns it into ClassNotFoundException.
"""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
DEXOPT = ROOT / "third_party/dalvik/vm/analysis/DexOptimize.c"


text = DEXOPT.read_text()

if "N3DS_TRANSIENT_ODEX_IO_RETRY" not in text:
    anchor = "static const size_t kMinDepSize = 4 * 4;\n"
    helper = r'''/* N3DS_TRANSIENT_ODEX_IO_RETRY: the ARM9-backed SD path can
 * return one transient EIO while another bounded writer owns the card.  An
 * odex is immutable here, so retry the same positioned read a few times. */
static ssize_t n3dsRetryReadAt(int fd, void* buf, size_t count)
{
    off_t start = lseek(fd, 0, SEEK_CUR);
    int attempt;

    if (start < 0)
        return -1;
    for (attempt = 0; attempt < 4; attempt++) {
        size_t done = 0;
        if (lseek(fd, start, SEEK_SET) != start)
            return -1;
        while (done < count) {
            ssize_t actual = read(fd, (u1*)buf + done, count - done);
            if (actual > 0) {
                done += actual;
                continue;
            }
            if (actual < 0 && errno == EINTR)
                continue;
            if (actual < 0 && errno == EIO && attempt + 1 < 4) {
                LOGW("DexOpt: transient SD EIO; retrying immutable read\n");
                usleep(20000);
                break;
            }
            return actual < 0 ? -1 : (ssize_t)done;
        }
        if (done == count)
            return (ssize_t)done;
    }
    return -1;
}

'''
    if text.count(anchor) != 1:
        raise SystemExit("DexOptimize dependency-size anchor missing")
    text = text.replace(anchor, helper + anchor, 1)

    old_header = "    if (read(fd, &optHdr, sizeof(optHdr)) != sizeof(optHdr)) {\n"
    new_header = "    if (n3dsRetryReadAt(fd, &optHdr, sizeof(optHdr)) != sizeof(optHdr)) {\n"
    if text.count(old_header) != 1:
        raise SystemExit("DexOptimize header read anchor missing")
    text = text.replace(old_header, new_header, 1)

    old_deps = "    actual = read(fd, depData, optHdr.depsLength);\n"
    new_deps = "    actual = n3dsRetryReadAt(fd, depData, optHdr.depsLength);\n"
    if text.count(old_deps) != 1:
        raise SystemExit("DexOptimize dependency read anchor missing")
    text = text.replace(old_deps, new_deps, 1)

if "N3DS_TRANSIENT_DEXOPT_EXEC_RETRY" not in text:
    old_exec = '''        if (kUseValgrind)
            execv(kValgrinder, argv);
        else
            execv(execFile, argv);

        LOGE("execv '%s'%s failed: %s\\n", execFile,
'''
    new_exec = '''        if (kUseValgrind) {
            execv(kValgrinder, argv);
        } else {
            /* N3DS_TRANSIENT_DEXOPT_EXEC_RETRY: exec must read the 5.5 MiB
             * static image from the same SD backend. Retry only EIO, with a
             * short finite delay; every other loader error remains fatal. */
            int execAttempt;
            for (execAttempt = 0; execAttempt < 4; execAttempt++) {
                execv(execFile, argv);
                if (errno != EIO || execAttempt == 3)
                    break;
                LOGW("execv '%s' hit transient SD EIO; retrying\\n", execFile);
                usleep(20000);
            }
        }

        LOGE("execv '%s'%s failed: %s\\n", execFile,
'''
    if text.count(old_exec) != 1:
        raise SystemExit("DexOptimize execv anchor missing")
    text = text.replace(old_exec, new_exec, 1)

DEXOPT.write_text(text)

for marker in ("N3DS_TRANSIENT_ODEX_IO_RETRY",
               "N3DS_TRANSIENT_DEXOPT_EXEC_RETRY"):
    if DEXOPT.read_text().count(marker) != 1:
        raise SystemExit(f"{marker} missing or duplicated")

print("patch_dalvik_transient_io: bounded odex read and dexopt exec EIO retry")
