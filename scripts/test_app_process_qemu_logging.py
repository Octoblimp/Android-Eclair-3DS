#!/usr/bin/env python3
"""Keep physical kmsg logging while preserving QEMU test stderr."""

from pathlib import Path


PATCH = Path(__file__).with_name("patch_app_process_qemu_logging.py").read_text(
    encoding="utf-8"
)


def main() -> None:
    for marker in (
        "N3DS_QEMU_HOST_TEST",
        "#ifndef N3DS_QEMU_HOST_TEST",
        "HOST_TEST_DEFINE=-DN3DS_QEMU_HOST_TEST",
        'HOST_TEST_DEFINE=""',
        "$HOST_TEST_DEFINE",
    ):
        assert marker in PATCH, marker
    print("app_process_qemu_logging: PASS")


if __name__ == "__main__":
    main()
