#!/usr/bin/env python3
"""Keep stderr capturable in QEMU without changing physical app_process."""
from a3ds_paths import A3DS_ROOT, A3DS_WIN

from pathlib import Path


ROOT = Path(A3DS_ROOT)
PROJECT = Path(A3DS_WIN)
APP_MAIN = ROOT / "third_party/frameworks/base/cmds/app_process/app_main.cpp"
BUILD_DEBUG = PROJECT / "scripts/build_app_process_debug.sh"
MARKER = "N3DS_QEMU_HOST_TEST"


def patch_app(text: str) -> str:
    if "#ifndef N3DS_QEMU_HOST_TEST" in text:
        return text
    old = '''#include <fcntl.h>
#include <unistd.h>
__attribute__((constructor)) static void redirect_stderr_to_kmsg() {
    int fd = open("/dev/kmsg", O_WRONLY);
    if (fd >= 0) {
        dup2(fd, STDERR_FILENO);
        close(fd);
    }
}
'''
    new = '''#include <fcntl.h>
#include <unistd.h>
#ifndef N3DS_QEMU_HOST_TEST
__attribute__((constructor)) static void redirect_stderr_to_kmsg() {
    int fd = open("/dev/kmsg", O_WRONLY);
    if (fd >= 0) {
        dup2(fd, STDERR_FILENO);
        close(fd);
    }
}
#endif
'''
    if text.count(old) != 1:
        raise RuntimeError("app_main kmsg constructor anchor missing or duplicated")
    return text.replace(old, new, 1)


def patch_build(text: str) -> str:
    if "HOST_TEST_DEFINE=-DN3DS_QEMU_HOST_TEST" in text:
        return text
    qemu = '''    CUTILS_ARCHIVE=$BUILD/libcutils_qemu/libcutils.a
else
    OUT=$BUILD/app_process_debug
'''
    qemu_new = '''    CUTILS_ARCHIVE=$BUILD/libcutils_qemu/libcutils.a
    HOST_TEST_DEFINE=-DN3DS_QEMU_HOST_TEST
else
    OUT=$BUILD/app_process_debug
'''
    physical = '''    CUTILS_ARCHIVE=$BUILD/libcutils/libcutils.a
fi
'''
    physical_new = '''    CUTILS_ARCHIVE=$BUILD/libcutils/libcutils.a
    HOST_TEST_DEFINE=""
fi
'''
    flags = '''-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \\
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DLINUX \\
'''
    flags_new = '''-Wno-attributes -Wno-invalid-offsetof -Wno-write-strings \\
$HOST_TEST_DEFINE \\
-D__ARM_EABI__ -DANDROID -DHAVE_ARM_TLS_REGISTER -DLINUX \\
'''
    for old, new, label in (
        (qemu, qemu_new, "QEMU branch"),
        (physical, physical_new, "physical branch"),
        (flags, flags_new, "CXX flags"),
    ):
        if text.count(old) != 1:
            raise RuntimeError(f"{label} anchor missing or duplicated")
        text = text.replace(old, new, 1)
    return text


def main() -> None:
    APP_MAIN.write_text(patch_app(APP_MAIN.read_text(encoding="utf-8")), encoding="utf-8")
    BUILD_DEBUG.write_text(
        patch_build(BUILD_DEBUG.read_text(encoding="utf-8")), encoding="utf-8"
    )
    print("patch_app_process_qemu_logging: host stderr preserved; hardware kmsg retained")


if __name__ == "__main__":
    main()
