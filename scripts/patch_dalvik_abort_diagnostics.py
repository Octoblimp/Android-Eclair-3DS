#!/usr/bin/env python3
"""Preserve the direct dvmAbort caller in kmsg before stdio flushing."""
from a3ds_paths import A3DS_ROOT

from pathlib import Path


ROOT = Path(A3DS_ROOT)
INIT = ROOT / "third_party/dalvik/vm/Init.c"
BOOT = (
    ROOT
    / "third_party/buildroot/board/nintendo3ds/rootfs_overlay/etc/boot_progress.sh"
)
MARKER = "N3DS_DALVIK_ABORT_CALLER"

OLD = '''void dvmAbort(void)
{
    LOGE("VM aborting\\n");

    fflush(NULL);       // flush all open file buffers
'''

NEW = '''void dvmAbort(void)
{
    /* N3DS_DALVIK_ABORT_CALLER: preserve the original fatal call site before
     * fflush(NULL) overwrites LR with stdio internals and the deliberate
     * 0xdeadd00d fault reaches the kernel. */
    void* caller = __builtin_return_address(0);
    char marker[96];
    int markerFd;
    int markerLen;

    markerLen = snprintf(marker, sizeof(marker),
        "N3DS_DALVIK_ABORT pid=%d caller=%p\\n", getpid(), caller);
    LOGE("%s", marker);
    markerFd = open("/dev/kmsg", O_WRONLY);
    if (markerFd >= 0) {
        if (markerLen > 0)
            write(markerFd, marker, markerLen < (int)sizeof(marker) ?
                  markerLen : (int)sizeof(marker) - 1);
        close(markerFd);
    }
    LOGE("VM aborting\\n");

    fflush(NULL);       // flush all open file buffers
'''


def patch_init(text: str) -> str:
    if MARKER in text:
        return text
    include = "#include <unistd.h>\n"
    if text.count(include) != 1:
        raise RuntimeError("Dalvik fcntl include anchor missing or duplicated")
    text = text.replace(include, include + "#include <fcntl.h>\n", 1)
    if text.count(OLD) != 1:
        raise RuntimeError("dvmAbort anchor missing or duplicated")
    return text.replace(OLD, NEW, 1)


def patch_boot(text: str) -> str:
    if "N3DS_DALVIK_ABORT|surfaceflinger" in text:
        return text
    old = 'grep -E "surfaceflinger|PC is at|'
    new = (
        'grep -E "N3DS_DALVIK_ABORT|surfaceflinger|Unhandled fault|'
        'Code:|r10:|PC is at|'
    )
    if text.count(old) != 1:
        raise RuntimeError("crash-signature grep anchor missing or duplicated")
    return text.replace(old, new, 1)


def main() -> None:
    for path in (INIT, BOOT):
        if not path.is_file():
            raise SystemExit(f"missing canonical source: {path}")
    INIT.write_text(patch_init(INIT.read_text(encoding="utf-8")), encoding="utf-8")
    BOOT.write_text(patch_boot(BOOT.read_text(encoding="utf-8")), encoding="utf-8")
    print("patch_dalvik_abort_diagnostics: caller+kmsg capture installed")


if __name__ == "__main__":
    main()
