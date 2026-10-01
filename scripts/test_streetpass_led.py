#!/usr/bin/env python3
"""Exercise the kernel-owned RGB hinge LED state machine on a fake sysfs tree."""

import os
import pathlib
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "native" / "streetpassd"


def main() -> None:
    daemon = (SRC / "streetpassd.c").read_text(encoding="utf-8")
    led = (SRC / "streetpass_led.c").read_text(encoding="utf-8")
    header = (SRC / "streetpass_led.h").read_text(encoding="utf-8")
    for marker in (
        '#define SP_LED_DEVICE_NAME "2d.mcu-led"',
        '"multi_intensity"',
        '"brightness"',
        "SP_LED_SOLID_GREEN",
        "SP_LED_RAPID_GREEN",
        "SP_LED_SLOW_GREEN",
        "if (!now_ms)",
        "sp_led_close(&led);",
    ):
        haystack = daemon + led + header
        if marker not in haystack:
            raise AssertionError(f"StreetPass LED contract missing {marker!r}")
    compiler = os.environ.get("CC", "gcc")
    with tempfile.TemporaryDirectory(prefix="streetpass-led-test-") as tmp:
        binary = pathlib.Path(tmp) / "streetpass_led_test"
        subprocess.run(
            [
                compiler,
                "-std=c99",
                "-D_DEFAULT_SOURCE",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O2",
                "-I",
                str(SRC),
                str(SRC / "streetpass_led.c"),
                str(SRC / "streetpass_led_test.c"),
                "-o",
                str(binary),
            ],
            check=True,
        )
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    main()
