#!/usr/bin/env python3
"""Run the dependency-free host StreetPass bridge regression suite."""

from __future__ import annotations

import pathlib
import subprocess
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def main() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            str(ROOT / "tests"),
            "-p",
            "test_streetpass_bridge.py",
            "-v",
        ],
        cwd=str(ROOT),
        check=True,
    )


if __name__ == "__main__":
    main()
