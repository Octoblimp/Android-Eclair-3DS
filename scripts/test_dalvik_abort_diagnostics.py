#!/usr/bin/env python3
"""Static contract for preserving the original Dalvik fatal caller."""

from pathlib import Path


PATCH = Path(__file__).with_name("patch_dalvik_abort_diagnostics.py").read_text(
    encoding="utf-8"
)


def main() -> None:
    for marker in (
        "N3DS_DALVIK_ABORT_CALLER",
        "__builtin_return_address(0)",
        'open("/dev/kmsg", O_WRONLY)',
        "N3DS_DALVIK_ABORT pid=%d caller=%p",
        "N3DS_DALVIK_ABORT|",
    ):
        assert marker in PATCH, marker
    replacement = PATCH.split("NEW = '''", 1)[1].split("'''", 1)[0]
    caller = replacement.index("__builtin_return_address(0)")
    flush = replacement.index("    fflush(NULL);")
    assert caller < flush
    print("dalvik_abort_diagnostics: PASS")


if __name__ == "__main__":
    main()
